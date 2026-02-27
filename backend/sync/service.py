from __future__ import annotations

import copy
import hashlib
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
import uuid
import zipfile

from backend.config import load_config, save_config
from backend.database.client import get_db
from backend.database.schema import PendingConflict
from backend.memory.conflicts import is_semantic_contradiction
from backend.memory.embedder import embed
from backend.memory.write_queue import enqueue_write
from backend.sync.crypto import derive_key_from_passphrase, encrypt_snapshot, decrypt_snapshot
from backend.sync.storage import download_latest_encrypted_snapshot, upload_encrypted_snapshot

logger = logging.getLogger(__name__)

_UNLOCKED_SYNC_KEY: bytes | None = None

_LEGACY_MEMORY_BASE_COLUMNS = {
    "id",
    "content",
    "level",
    "category",
    "importance_score",
    "confidence_score",
    "privacy",
    "tags",
    "source_llm",
    "source_conversation_id",
    "source_message_id",
    "source_excerpt",
    "version",
    "status",
    "created_at",
    "updated_at",
    "last_referenced_at",
    "reference_count",
    "decay_profile",
    "expires_at",
    "needs_review",
    "review_due_at",
    "event_date",
    "suggestion_reason",
    "review_note",
    "vector",
}

SYNC_TABLES = [
    "memories",
    "memory_versions",
    "conversations",
    "messages",
    "conflicts",
    "pending_conflicts",
    "sessions",
    "context_route_logs",
    "memory_graph_edges",
    "memory_events",
]


def _normalize_provider(value: Any) -> str:
    provider = str(value or "s3").strip().lower()
    aliases = {
        "aws": "s3",
        "amazon-s3": "s3",
        "cloudflare-r2": "r2",
        "cf-r2": "r2",
        "nextcloud": "webdav",
        "owncloud": "webdav",
    }
    return aliases.get(provider, provider)


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _to_jsonable(value: Any):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


def _from_jsonable_row(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, str) and ("_at" in k or k in {"event_date", "resolved_at", "started_at", "ended_at", "timestamp"}):
            try:
                out[k] = _to_dt(v)
                continue
            except Exception:
                pass
        out[k] = v
    return out


def _table_columns(tbl) -> set[str]:
    try:
        schema = getattr(tbl, "schema", None)
        names = getattr(schema, "names", None)
        if names:
            return {str(name) for name in names}
    except Exception:
        pass
    try:
        sample = tbl.search().limit(1).to_list()
        if sample and isinstance(sample[0], dict):
            return {str(k) for k in sample[0].keys()}
    except Exception:
        pass
    return set()


def _filter_for_columns(tbl, values: dict) -> dict:
    cols = _table_columns(tbl)
    if not cols:
        return {k: v for k, v in values.items() if k in _LEGACY_MEMORY_BASE_COLUMNS}
    return {k: v for k, v in values.items() if k in cols}


def _masked(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def get_sync_public_status() -> dict:
    cfg = load_config(force_reload=True)
    sync_cfg = cfg.get("sync", {})
    sync_status = cfg.get("sync_status", {})
    public_sync_cfg = {
        **sync_cfg,
        "secret_access_key": _masked(sync_cfg.get("secret_access_key", "")),
        "webdav_password": _masked(sync_cfg.get("webdav_password", "")),
    }
    return {
        "sync": public_sync_cfg,
        "sync_status": sync_status,
        "unlocked": _UNLOCKED_SYNC_KEY is not None,
    }


def update_sync_config(partial: dict) -> dict:
    cfg = load_config(force_reload=True)
    current = cfg.get("sync", {})
    merged = {**current, **(partial or {})}

    # Preserve existing secrets when clients send masked placeholders.
    for key in ("access_key_id", "secret_access_key", "webdav_password"):
        value = merged.get(key)
        if isinstance(value, str) and current.get(key):
            current_value = str(current.get(key))
            if (value and set(value) == {"*"}) or value == _masked(current_value):
                merged[key] = current_value

    # Normalize a few common fields.
    for key in (
        "endpoint_url",
        "bucket",
        "region",
        "object_prefix",
        "device_id",
        "provider",
        "access_key_id",
        "webdav_url",
        "webdav_username",
    ):
        value = merged.get(key)
        if isinstance(value, str):
            merged[key] = value.strip()
    if isinstance(merged.get("endpoint_url"), str):
        merged["endpoint_url"] = merged["endpoint_url"].rstrip("/")
    if isinstance(merged.get("webdav_url"), str):
        merged["webdav_url"] = merged["webdav_url"].rstrip("/")
    merged["provider"] = _normalize_provider(merged.get("provider"))
    if "force_path_style" in merged:
        merged["force_path_style"] = bool(merged.get("force_path_style"))
    if isinstance(merged.get("auto_sync_interval_minutes"), (int, float, str)):
        try:
            merged["auto_sync_interval_minutes"] = max(5, min(1440, int(merged["auto_sync_interval_minutes"])))
        except Exception:
            merged["auto_sync_interval_minutes"] = 60
    if not merged.get("device_id"):
        merged["device_id"] = str(uuid.uuid4())

    cfg["sync"] = merged
    save_config(copy.deepcopy(cfg))
    return get_sync_public_status()


def unlock_sync(passphrase: str) -> dict:
    global _UNLOCKED_SYNC_KEY
    _UNLOCKED_SYNC_KEY = derive_key_from_passphrase(passphrase)
    return {"status": "unlocked"}


def lock_sync() -> dict:
    global _UNLOCKED_SYNC_KEY
    _UNLOCKED_SYNC_KEY = None
    return {"status": "locked"}


def is_sync_unlocked() -> bool:
    return _UNLOCKED_SYNC_KEY is not None


def _ensure_sync_ready(sync_cfg: dict):
    provider = _normalize_provider(sync_cfg.get("provider"))
    if provider == "webdav":
        required = ["webdav_url", "webdav_username", "webdav_password"]
    else:
        required = ["bucket", "access_key_id", "secret_access_key"]
        if provider != "s3":
            required.append("endpoint_url")
    missing = [k for k in required if not sync_cfg.get(k)]
    if missing:
        raise ValueError(f"Sync config incomplete. Missing: {', '.join(missing)}")


def _build_plain_snapshot_zip() -> tuple[bytes, dict]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception as e:
        raise RuntimeError("Missing dependency 'pyarrow' required for snapshot export.") from e

    db = get_db()
    table_names = [t for t in SYNC_TABLES if t in db.table_names()]
    manifest = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
    }

    out = io.BytesIO()
    with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for table_name in table_names:
            rows = db.open_table(table_name).search().limit(200000).to_list()
            safe_rows = [_to_jsonable(r) for r in rows]
            manifest["tables"][table_name] = {"row_count": len(safe_rows)}
            if not safe_rows:
                continue
            table = pa.Table.from_pylist(safe_rows)
            table_buf = io.BytesIO()
            pq.write_table(table, table_buf, compression="zstd")
            zf.writestr(f"{table_name}.parquet", table_buf.getvalue())
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    payload = out.getvalue()
    manifest["size_bytes"] = len(payload)
    manifest["checksum_plain_sha256"] = hashlib.sha256(payload).hexdigest()
    return payload, manifest


def _load_plain_snapshot_zip(payload: bytes) -> tuple[dict[str, list[dict]], dict]:
    try:
        import pyarrow.parquet as pq
    except Exception as e:
        raise RuntimeError("Missing dependency 'pyarrow' required for snapshot import.") from e

    tables: dict[str, list[dict]] = {}
    manifest: dict = {}
    with zipfile.ZipFile(io.BytesIO(payload), mode="r") as zf:
        names = set(zf.namelist())
        if "manifest.json" in names:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        for name in names:
            if not name.endswith(".parquet"):
                continue
            table_name = name.removesuffix(".parquet")
            table = pq.read_table(io.BytesIO(zf.read(name)))
            rows = table.to_pylist()
            tables[table_name] = [_from_jsonable_row(r) for r in rows]
    return tables, manifest


def _normalize_memory_row(row: dict) -> dict:
    now = datetime.now(timezone.utc)
    normalized = dict(row)
    normalized.setdefault("id", str(uuid.uuid4()))
    normalized.setdefault("content", "")
    normalized.setdefault("level", "semantic")
    normalized.setdefault("category", "preferences")
    normalized.setdefault("importance_score", 0.5)
    normalized.setdefault("confidence_score", 0.7)
    normalized.setdefault("privacy", "public")
    normalized.setdefault("tags", [])
    normalized.setdefault("source_llm", "sync")
    normalized.setdefault("source_conversation_id", None)
    normalized.setdefault("source_message_id", None)
    normalized.setdefault("source_excerpt", None)
    normalized.setdefault("version", 1)
    normalized.setdefault("status", "active")
    normalized["created_at"] = _to_dt(normalized.get("created_at", now))
    normalized["updated_at"] = _to_dt(normalized.get("updated_at", now))
    normalized["last_referenced_at"] = _to_dt(normalized.get("last_referenced_at", now))
    normalized.setdefault("reference_count", 0)
    normalized.setdefault("decay_profile", "stable")
    normalized["expires_at"] = _to_dt(normalized["expires_at"]) if normalized.get("expires_at") else None
    normalized.setdefault("needs_review", False)
    normalized["review_due_at"] = _to_dt(normalized["review_due_at"]) if normalized.get("review_due_at") else None
    normalized["event_date"] = _to_dt(normalized["event_date"]) if normalized.get("event_date") else None
    normalized.setdefault("suggestion_reason", "")
    normalized.setdefault("review_note", "")
    if not normalized.get("vector"):
        normalized["vector"] = embed(normalized["content"])
    return normalized


async def _merge_memories(remote_rows: list[dict], remote_device: Optional[str]) -> dict:
    if not remote_rows:
        return {"added": 0, "updated": 0, "conflicts": 0}

    db = get_db()
    mem_tbl = db.open_table("memories")
    pending_tbl = db.open_table("pending_conflicts")

    local_rows = mem_tbl.search().limit(200000).to_list()
    local_by_id = {row.get("id"): row for row in local_rows if row.get("id")}
    now = datetime.now(timezone.utc)

    async def _write_op():
        added = 0
        updated = 0
        conflicts = 0

        to_add = []
        for remote in remote_rows:
            try:
                normalized_remote = _normalize_memory_row(remote)
            except Exception as e:
                logger.warning(f"Skipping invalid remote memory row: {e}")
                continue

            rid = normalized_remote["id"]
            local = local_by_id.get(rid)
            if not local:
                add_row = _filter_for_columns(mem_tbl, normalized_remote)
                to_add.append(add_row)
                added += 1
                continue

            local_updated = _to_dt(local.get("updated_at"))
            remote_updated = _to_dt(normalized_remote.get("updated_at"))
            if remote_updated <= local_updated:
                continue

            local_content = local.get("content", "")
            remote_content = normalized_remote.get("content", "")
            same_category = local.get("category") == normalized_remote.get("category")
            if same_category and local_content != remote_content and is_semantic_contradiction(local_content, remote_content):
                pending_tbl.add([
                    PendingConflict(
                        id=str(uuid.uuid4()),
                        memory_id_existing=rid,
                        candidate_content=remote_content,
                        candidate_level=normalized_remote.get("level", "semantic"),
                        candidate_category=normalized_remote.get("category", "preferences"),
                        candidate_source_llm=f"sync:{remote_device or 'unknown'}",
                        similarity_score=0.9,
                        detected_at=now,
                        resolved_at=None,
                        resolution=None,
                        status="pending",
                        candidate_memory_id=None,
                    )
                ])
                conflicts += 1
                continue

            values = {k: v for k, v in normalized_remote.items() if k != "id"}
            values = _filter_for_columns(mem_tbl, values)
            try:
                mem_tbl.update(where=f"id = '{rid}'", values=values)
            except Exception as e:
                if "not found in target schema" in str(e).lower():
                    fallback_values = {k: v for k, v in values.items() if k in _LEGACY_MEMORY_BASE_COLUMNS and k != "id"}
                    mem_tbl.update(where=f"id = '{rid}'", values=fallback_values)
                else:
                    raise
            updated += 1

        if to_add:
            try:
                mem_tbl.add(to_add)
            except Exception as e:
                if "not found in target schema" in str(e).lower():
                    fallback_rows = [
                        {k: v for k, v in row.items() if k in _LEGACY_MEMORY_BASE_COLUMNS}
                        for row in to_add
                    ]
                    mem_tbl.add(fallback_rows)
                else:
                    raise
        return {"added": added, "updated": updated, "conflicts": conflicts}

    return await enqueue_write(_write_op)


async def _merge_other_tables(remote_tables: dict[str, list[dict]]) -> dict:
    db = get_db()
    stats = {"added": 0}

    async def _write_op():
        for table_name, rows in remote_tables.items():
            if table_name == "memories":
                continue
            if table_name not in db.table_names():
                continue
            if not rows:
                continue
            tbl = db.open_table(table_name)
            local_rows = tbl.search().limit(200000).to_list()
            local_ids = {r.get("id") for r in local_rows if isinstance(r, dict) and r.get("id")}

            to_add = []
            for row in rows:
                rid = row.get("id")
                if rid and rid in local_ids:
                    continue
                to_add.append(_from_jsonable_row(row))
            if to_add:
                tbl.add(to_add)
                stats["added"] += len(to_add)

    await enqueue_write(_write_op)
    return stats


def _update_sync_status(success: bool, payload: Optional[dict] = None, error: Optional[str] = None):
    cfg = load_config(force_reload=True)
    status = cfg.get("sync_status", {})
    now = datetime.now(timezone.utc).isoformat()
    status["last_sync_at"] = now
    status["last_sync_result"] = "ok" if success else "error"
    status["last_error"] = error
    if payload:
        status["last_sync_size_bytes"] = payload.get("size_bytes", status.get("last_sync_size_bytes", 0))
        devices = set(status.get("devices", []))
        local_device = cfg.get("sync", {}).get("device_id")
        remote_device = payload.get("remote_device_id")
        if local_device:
            devices.add(local_device)
        if remote_device:
            devices.add(remote_device)
        status["devices"] = sorted(devices)
    cfg["sync_status"] = status
    save_config(copy.deepcopy(cfg))


async def run_sync_now(passphrase: Optional[str] = None, source: str = "manual") -> dict:
    global _UNLOCKED_SYNC_KEY

    cfg = load_config(force_reload=True)
    sync_cfg = cfg.get("sync", {})
    _ensure_sync_ready(sync_cfg)
    if not sync_cfg.get("enabled"):
        raise ValueError("Sync is disabled in settings")

    if passphrase:
        unlock_sync(passphrase)
    if _UNLOCKED_SYNC_KEY is None:
        raise ValueError("Sync key is locked. Provide passphrase first.")

    try:
        remote_doc = download_latest_encrypted_snapshot(sync_cfg)
        merge_report = {
            "memories_added": 0,
            "memories_updated": 0,
            "conflicts_created": 0,
            "other_rows_added": 0,
        }
        remote_device_id = None

        if remote_doc:
            metadata = remote_doc.get("metadata", {})
            remote_device_id = metadata.get("device_id")
            encrypted_payload = remote_doc.get("payload", {})
            plain_remote = decrypt_snapshot(encrypted_payload, _UNLOCKED_SYNC_KEY, metadata)
            remote_tables, _manifest = _load_plain_snapshot_zip(plain_remote)

            mem_report = await _merge_memories(remote_tables.get("memories", []), remote_device=remote_device_id)
            other_report = await _merge_other_tables(remote_tables)
            merge_report["memories_added"] = mem_report.get("added", 0)
            merge_report["memories_updated"] = mem_report.get("updated", 0)
            merge_report["conflicts_created"] = mem_report.get("conflicts", 0)
            merge_report["other_rows_added"] = other_report.get("added", 0)

        plain_snapshot, manifest = _build_plain_snapshot_zip()
        metadata = {
            "snapshot_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "checksum_plain_sha256": manifest.get("checksum_plain_sha256"),
            "device_id": sync_cfg.get("device_id"),
            "table_counts": {k: v.get("row_count", 0) for k, v in manifest.get("tables", {}).items()},
            "source": source,
            "size_bytes": manifest.get("size_bytes", len(plain_snapshot)),
        }
        encrypted_payload = encrypt_snapshot(plain_snapshot, _UNLOCKED_SYNC_KEY, metadata=metadata)
        snapshot_document = {
            "metadata": metadata,
            "payload": encrypted_payload,
        }
        key_name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{sync_cfg.get('device_id', 'device')}"
        upload_info = upload_encrypted_snapshot(sync_cfg, snapshot_document, key_name=key_name)

        report = {
            "status": "ok",
            "uploaded": upload_info,
            "merge": merge_report,
            "metadata": {
                "size_bytes": upload_info.get("size_bytes", metadata.get("size_bytes", 0)),
                "remote_device_id": remote_device_id,
            },
        }
        _update_sync_status(success=True, payload=report["metadata"])
        return report
    except Exception as e:
        _update_sync_status(success=False, error=str(e))
        raise
