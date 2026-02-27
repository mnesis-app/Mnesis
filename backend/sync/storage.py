from __future__ import annotations

import base64
import json
from typing import Optional

import httpx


def _provider(sync_cfg: dict) -> str:
    provider = str(sync_cfg.get("provider") or "s3").strip().lower()
    aliases = {
        "aws": "s3",
        "amazon-s3": "s3",
        "cloudflare-r2": "r2",
        "cf-r2": "r2",
        "nextcloud": "webdav",
        "owncloud": "webdav",
    }
    return aliases.get(provider, provider)


def _get_s3_client(sync_cfg: dict):
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except Exception as e:
        raise RuntimeError("Missing dependency 'boto3' required for S3/R2 sync.") from e

    provider = _provider(sync_cfg)
    endpoint_url = (sync_cfg.get("endpoint_url") or "").strip() or None
    region = sync_cfg.get("region") or "auto"
    if region == "auto":
        region = "us-east-1"

    # Provider-specific defaults.
    if provider == "s3":
        endpoint_url = endpoint_url or None
    else:
        if not endpoint_url:
            raise ValueError(f"Sync provider '{provider}' requires endpoint_url")

    force_path_style = bool(sync_cfg.get("force_path_style"))
    if provider == "minio":
        force_path_style = True

    config = BotoConfig(
        s3={"addressing_style": "path" if force_path_style else "auto"},
        signature_version="s3v4",
    )

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=sync_cfg.get("access_key_id"),
        aws_secret_access_key=sync_cfg.get("secret_access_key"),
        region_name=region,
        config=config,
    )


def _paths(sync_cfg: dict) -> tuple[str, str]:
    prefix = (sync_cfg.get("object_prefix") or "mnesis").strip("/")
    latest_key = f"{prefix}/latest.json"
    return prefix, latest_key


def _upload_s3(sync_cfg: dict, snapshot_document: dict, key_name: str) -> dict:
    s3 = _get_s3_client(sync_cfg)
    bucket = sync_cfg.get("bucket")
    if not bucket:
        raise ValueError("Sync bucket is required")

    prefix, latest_key = _paths(sync_cfg)
    snapshot_key = f"{prefix}/snapshots/{key_name}.json"
    body = json.dumps(snapshot_document, ensure_ascii=False).encode("utf-8")
    s3.put_object(
        Bucket=bucket,
        Key=snapshot_key,
        Body=body,
        ContentType="application/json",
    )
    latest_doc = json.dumps({"key": snapshot_key}, ensure_ascii=False).encode("utf-8")
    s3.put_object(
        Bucket=bucket,
        Key=latest_key,
        Body=latest_doc,
        ContentType="application/json",
    )
    return {"snapshot_key": snapshot_key, "latest_key": latest_key, "size_bytes": len(body)}


def _download_s3(sync_cfg: dict) -> Optional[dict]:
    s3 = _get_s3_client(sync_cfg)
    bucket = sync_cfg.get("bucket")
    if not bucket:
        raise ValueError("Sync bucket is required")

    _, latest_key = _paths(sync_cfg)

    try:
        latest_res = s3.get_object(Bucket=bucket, Key=latest_key)
        latest_data = json.loads(latest_res["Body"].read().decode("utf-8"))
        snapshot_key = latest_data.get("key")
        if not snapshot_key:
            return None
        snapshot_res = s3.get_object(Bucket=bucket, Key=snapshot_key)
        payload = json.loads(snapshot_res["Body"].read().decode("utf-8"))
        payload["_object_key"] = snapshot_key
        return payload
    except Exception:
        # No snapshot yet / inaccessible latest pointer.
        return None


def _webdav_base_url(sync_cfg: dict) -> str:
    base = (sync_cfg.get("webdav_url") or "").strip().rstrip("/")
    if not base:
        raise ValueError("WebDAV URL is required")
    if not base.startswith("https://"):
        raise ValueError("WebDAV sync requires an HTTPS URL to protect credentials in transit.")
    return base


def _webdav_headers(sync_cfg: dict, content_type: Optional[str] = None) -> dict:
    username = sync_cfg.get("webdav_username") or ""
    password = sync_cfg.get("webdav_password") or ""
    if not username or not password:
        raise ValueError("WebDAV credentials are required")
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {token}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _join_url(base: str, relative_path: str) -> str:
    rel = relative_path.strip("/")
    if not rel:
        return base
    return f"{base}/{rel}"


def _ensure_webdav_dirs(sync_cfg: dict, relative_dir: str):
    base_url = _webdav_base_url(sync_cfg)
    headers = _webdav_headers(sync_cfg)
    parts = [p for p in relative_dir.strip("/").split("/") if p]
    current = base_url
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for part in parts:
            current = f"{current}/{part}"
            res = client.request("MKCOL", current, headers=headers)
            if res.status_code in (200, 201, 204, 207, 301, 302, 405):
                continue
            if res.status_code == 409:
                raise ValueError(f"WebDAV path conflict while creating '{relative_dir}'")
            raise ValueError(f"WebDAV MKCOL failed ({res.status_code}): {res.text[:180]}")


def _upload_webdav(sync_cfg: dict, snapshot_document: dict, key_name: str) -> dict:
    prefix, latest_key = _paths(sync_cfg)
    snapshot_key = f"{prefix}/snapshots/{key_name}.json"
    body = json.dumps(snapshot_document, ensure_ascii=False).encode("utf-8")

    _ensure_webdav_dirs(sync_cfg, prefix)
    _ensure_webdav_dirs(sync_cfg, f"{prefix}/snapshots")

    base_url = _webdav_base_url(sync_cfg)
    json_headers = _webdav_headers(sync_cfg, content_type="application/json")
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        put_snapshot = client.put(_join_url(base_url, snapshot_key), content=body, headers=json_headers)
        if put_snapshot.status_code not in (200, 201, 204):
            raise ValueError(f"WebDAV upload failed ({put_snapshot.status_code}): {put_snapshot.text[:180]}")

        latest_doc = json.dumps({"key": snapshot_key}, ensure_ascii=False).encode("utf-8")
        put_latest = client.put(_join_url(base_url, latest_key), content=latest_doc, headers=json_headers)
        if put_latest.status_code not in (200, 201, 204):
            raise ValueError(f"WebDAV latest pointer update failed ({put_latest.status_code}): {put_latest.text[:180]}")

    return {"snapshot_key": snapshot_key, "latest_key": latest_key, "size_bytes": len(body)}


def _download_webdav(sync_cfg: dict) -> Optional[dict]:
    base_url = _webdav_base_url(sync_cfg)
    headers = _webdav_headers(sync_cfg)
    _, latest_key = _paths(sync_cfg)

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        latest_res = client.get(_join_url(base_url, latest_key), headers=headers)
        if latest_res.status_code == 404:
            return None
        if latest_res.status_code != 200:
            raise ValueError(f"WebDAV latest pointer fetch failed ({latest_res.status_code})")

        latest_data = json.loads(latest_res.text)
        snapshot_key = latest_data.get("key")
        if not snapshot_key:
            return None

        snapshot_url = snapshot_key if str(snapshot_key).startswith(("http://", "https://")) else _join_url(base_url, snapshot_key)
        snapshot_res = client.get(snapshot_url, headers=headers)
        if snapshot_res.status_code == 404:
            return None
        if snapshot_res.status_code != 200:
            raise ValueError(f"WebDAV snapshot fetch failed ({snapshot_res.status_code})")

        payload = json.loads(snapshot_res.text)
        payload["_object_key"] = snapshot_key
        return payload


def upload_encrypted_snapshot(sync_cfg: dict, snapshot_document: dict, key_name: str) -> dict:
    provider = _provider(sync_cfg)
    if provider == "webdav":
        return _upload_webdav(sync_cfg, snapshot_document, key_name)
    return _upload_s3(sync_cfg, snapshot_document, key_name)


def download_latest_encrypted_snapshot(sync_cfg: dict) -> Optional[dict]:
    provider = _provider(sync_cfg)
    if provider == "webdav":
        return _download_webdav(sync_cfg)
    return _download_s3(sync_cfg)
