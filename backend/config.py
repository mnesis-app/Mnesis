import yaml
import os
import secrets
import copy
import hashlib
import stat
import logging
from typing import Optional
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

if os.environ.get("MNESIS_APPDATA_DIR"):
    CONFIG_DIR = os.environ["MNESIS_APPDATA_DIR"]
elif os.name == 'nt':
    CONFIG_DIR = os.path.join(os.environ['APPDATA'], 'Mnesis')
else:
    CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.mnesis')

if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(CONFIG_DIR, "config.yaml")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _ensure_private_permissions() -> bool:
    """
    Best-effort permission hardening on POSIX systems:
      - config dir: 700
      - config file: 600
    """
    if os.name == "nt":
        return False
    changed = False
    try:
        if os.path.isdir(CONFIG_DIR):
            mode = stat.S_IMODE(os.stat(CONFIG_DIR).st_mode)
            if mode != 0o700:
                os.chmod(CONFIG_DIR, 0o700)
                changed = True
    except Exception as e:
        logger.debug(f"Could not harden CONFIG_DIR permissions: {e}")
    try:
        if os.path.exists(CONFIG_PATH):
            mode = stat.S_IMODE(os.stat(CONFIG_PATH).st_mode)
            if mode != 0o600:
                os.chmod(CONFIG_PATH, 0o600)
                changed = True
    except Exception as e:
        logger.debug(f"Could not harden CONFIG_PATH permissions: {e}")
    return changed


def _ensure_security_baseline(config: dict) -> bool:
    """
    Secure-by-default baseline:
      - Ensure dedicated MCP key exists (bootstrapped from snapshot token hash if needed).
      - Disable snapshot-token MCP fallback when dedicated keys exist.
      - Keep strict auth/header/rate-limit defaults enabled.
    """
    changed = False
    if not isinstance(config, dict):
        return False

    if not isinstance(config.get("llm_client_keys"), dict):
        config["llm_client_keys"] = {}
        changed = True

    keys = config["llm_client_keys"]
    token = str(config.get("snapshot_read_token") or "").strip()
    if token and not keys:
        keys["mnesis-bridge"] = {
            "hash": _sha256_hex(token),
            "scopes": ["read", "write", "sync"],
            "enabled": True,
            "managed_by": "mnesis",
            "created_at": _utc_now_iso(),
        }
        changed = True

    sec = config.get("security")
    if not isinstance(sec, dict):
        sec = {}
        config["security"] = sec
        changed = True

    hard_bools = {
        "enforce_mcp_auth": True,
        "allow_snapshot_query_token": False,
        "require_client_mutation_header": True,
    }
    for key, value in hard_bools.items():
        if sec.get(key) != value:
            sec[key] = value
            changed = True

    if keys and sec.get("allow_snapshot_token_for_mcp") is not False:
        sec["allow_snapshot_token_for_mcp"] = False
        changed = True

    if not isinstance(sec.get("allowed_client_mutation_header_values"), list) or not sec.get(
        "allowed_client_mutation_header_values"
    ):
        sec["allowed_client_mutation_header_values"] = list(
            DEFAULT_CONFIG.get("security", {}).get("allowed_client_mutation_header_values", [])
        )
        changed = True

    if not isinstance(sec.get("allowed_mutation_origins"), list) or not sec.get("allowed_mutation_origins"):
        sec["allowed_mutation_origins"] = list(DEFAULT_CONFIG.get("security", {}).get("allowed_mutation_origins", []))
        changed = True

    if not isinstance(sec.get("trusted_hosts"), list) or not sec.get("trusted_hosts"):
        sec["trusted_hosts"] = list(DEFAULT_CONFIG.get("security", {}).get("trusted_hosts", []))
        changed = True

    rate_limit = sec.get("rate_limit")
    if not isinstance(rate_limit, dict):
        rate_limit = {}
        sec["rate_limit"] = rate_limit
        changed = True
    if rate_limit.get("enabled") is not True:
        rate_limit["enabled"] = True
        changed = True

    return changed

DEFAULT_CONFIG = {
    "onboarding_completed": False,
    "snapshot_read_token": "",
    "validation_mode": "auto",  # "auto" | "review" | "strict"
    "decay_rates": {
        "semantic": 0.001,
        "episodic": 0.05,
        "working": 0.3
    },
    "llm_client_keys": {},
    "rest_port": 7860,
    "mcp_port": 7861,
    "sync": {
        "enabled": False,
        "provider": "s3",
        "endpoint_url": "",
        "force_path_style": False,
        "webdav_url": "",
        "webdav_username": "",
        "webdav_password": "",
        "bucket": "",
        "region": "auto",
        "access_key_id": "",
        "secret_access_key": "",
        "object_prefix": "mnesis",
        "device_id": "",
        "auto_sync": False,
        "auto_sync_interval_minutes": 60,
    },
    "sync_status": {
        "last_sync_at": None,
        "last_sync_size_bytes": 0,
        "last_sync_result": "never",
        "devices": [],
        "last_error": None,
    },
    "insights": {
        "enabled": True,
        "provider": "openai",  # "openai" | "anthropic" | "ollama"
        "model": "gpt-4o-mini",
        "api_key": "",
        "api_base_url": "",
    },
    "insights_cache": {
        "date": "",
        "generated_at": None,
        "source": "none",
        "insights": [],
        "last_error": None,
    },
    "conversation_analysis": {
        "enabled": True,
        "require_llm_configured": True,
        "interval_minutes": 20,
        "provider": "auto",
        "model": "",
        "api_base_url": "",
        "api_key": "",
        "max_conversations": 24,
        "max_messages_per_conversation": 24,
        "max_candidates_per_conversation": 4,
        "max_new_memories": 40,
        "min_confidence": 0.8,
        "promotion_min_score": 0.72,
        "promotion_min_evidence": 1,
        "promotion_min_conversations": 1,
        "semantic_dedupe_threshold": 0.92,
        "concurrency": 2,
        "include_assistant_messages": False,
    },
    "mcp_autoconfig": {
        "enabled": True,
        "first_launch_done": False,
        "last_run_at": None,
        "detected_clients": [],
        "configured_clients": [],
        "last_error": None,
    },
    "remote_access": {
        "enabled": False,
        "relay_url": "",
        "project_id": "",
        "device_id": "",
        "device_secret": "",
        "device_name": "mnesis-desktop",
        "poll_interval_seconds": 12,
        "request_timeout_seconds": 20,
        "max_tasks_per_poll": 4,
    },
    "security": {
        # Keep local-first UX by default while hardening critical surfaces.
        "enforce_mcp_auth": True,
        "allow_snapshot_token_for_mcp": True,
        "allow_snapshot_query_token": False,
        "require_client_mutation_header": True,
        "client_mutation_header_name": "X-Mnesis-Client",
        "allowed_client_mutation_header_values": [
            "mnesis-desktop",
            "mnesis-electron",
            "mnesis-cli",
            "mnesis-tests",
        ],
        "allowed_mutation_origins": [
            "http://127.0.0.1",
            "http://localhost",
            "app://.",
        ],
        "trusted_hosts": [
            "127.0.0.1",
            "localhost",
            "testserver",
        ],
        "rate_limit": {
            "enabled": True,
            "window_seconds": 60,
            "buckets": {
                "mcp": 240,
                "snapshot": 40,
                "admin": 160,
                "api_mutation": 200,
            },
        },
        "audit": {
            "enabled": True,
            "interval_minutes": 60,
        },
    },
}

_config_cache = None

def load_config(force_reload: bool = False) -> dict:
    global _config_cache
    if _config_cache and not force_reload:
        return _config_cache
    
    if not os.path.exists(CONFIG_PATH):
        _config_cache = copy.deepcopy(DEFAULT_CONFIG)
        # Generate initial token
        _config_cache["snapshot_read_token"] = secrets.token_urlsafe(32)
        _config_cache.setdefault("sync", {})
        _config_cache["sync"]["device_id"] = str(uuid.uuid4())
        save_config(_config_cache)
    else:
        with open(CONFIG_PATH, "r") as f:
            _config_cache = yaml.safe_load(f) or copy.deepcopy(DEFAULT_CONFIG)

    original = _config_cache if isinstance(_config_cache, dict) else {}

    # Deep-merge all known defaults so minimal/legacy configs are still fully usable.
    merged = {**DEFAULT_CONFIG, **original}
    merged["sync"] = {**DEFAULT_CONFIG.get("sync", {}), **(original.get("sync", {}) if isinstance(original.get("sync"), dict) else {})}
    merged["sync_status"] = {**DEFAULT_CONFIG.get("sync_status", {}), **(original.get("sync_status", {}) if isinstance(original.get("sync_status"), dict) else {})}
    merged["insights"] = {**DEFAULT_CONFIG.get("insights", {}), **(original.get("insights", {}) if isinstance(original.get("insights"), dict) else {})}
    merged["insights_cache"] = {**DEFAULT_CONFIG.get("insights_cache", {}), **(original.get("insights_cache", {}) if isinstance(original.get("insights_cache"), dict) else {})}
    merged["conversation_analysis"] = {**DEFAULT_CONFIG.get("conversation_analysis", {}), **(original.get("conversation_analysis", {}) if isinstance(original.get("conversation_analysis"), dict) else {})}
    merged["mcp_autoconfig"] = {**DEFAULT_CONFIG.get("mcp_autoconfig", {}), **(original.get("mcp_autoconfig", {}) if isinstance(original.get("mcp_autoconfig"), dict) else {})}
    merged["remote_access"] = {**DEFAULT_CONFIG.get("remote_access", {}), **(original.get("remote_access", {}) if isinstance(original.get("remote_access"), dict) else {})}
    merged["security"] = {**DEFAULT_CONFIG.get("security", {}), **(original.get("security", {}) if isinstance(original.get("security"), dict) else {})}
    merged["security"]["rate_limit"] = {
        **DEFAULT_CONFIG.get("security", {}).get("rate_limit", {}),
        **(merged["security"].get("rate_limit", {}) if isinstance(merged["security"].get("rate_limit"), dict) else {}),
    }
    merged["security"]["rate_limit"]["buckets"] = {
        **DEFAULT_CONFIG.get("security", {}).get("rate_limit", {}).get("buckets", {}),
        **(
            merged["security"].get("rate_limit", {}).get("buckets", {})
            if isinstance(merged["security"].get("rate_limit", {}).get("buckets"), dict)
            else {}
        ),
    }
    merged["security"]["audit"] = {
        **DEFAULT_CONFIG.get("security", {}).get("audit", {}),
        **(merged["security"].get("audit", {}) if isinstance(merged["security"].get("audit"), dict) else {}),
    }
    merged["decay_rates"] = {**DEFAULT_CONFIG.get("decay_rates", {}), **(original.get("decay_rates", {}) if isinstance(original.get("decay_rates"), dict) else {})}
    if not isinstance(merged.get("llm_client_keys"), dict):
        merged["llm_client_keys"] = {}

    needs_save = merged != original

    # Backfill dynamic defaults.
    if not merged["sync"].get("device_id"):
        merged["sync"]["device_id"] = str(uuid.uuid4())
        needs_save = True
    if not merged["remote_access"].get("device_id"):
        merged["remote_access"]["device_id"] = str(merged["sync"].get("device_id") or uuid.uuid4())
        needs_save = True
    if not merged["remote_access"].get("device_secret"):
        merged["remote_access"]["device_secret"] = secrets.token_urlsafe(32)
        needs_save = True
    if not merged.get("snapshot_read_token"):
        merged["snapshot_read_token"] = secrets.token_urlsafe(32)
        needs_save = True

    if _ensure_security_baseline(merged):
        needs_save = True

    _config_cache = merged

    if needs_save:
        try:
            save_config(_config_cache)
        except Exception:
            # Best-effort persistence; runtime config remains usable even if save fails.
            pass
    else:
        _ensure_private_permissions()

    return _config_cache

def save_config(config: dict):
    global _config_cache
    # Merge with defaults so new keys are always present
    merged = {**DEFAULT_CONFIG, **config}
    # Deep-merge nested sync blocks to preserve new keys.
    merged["sync"] = {**DEFAULT_CONFIG.get("sync", {}), **(config.get("sync", {}) if isinstance(config.get("sync"), dict) else {})}
    merged["sync_status"] = {**DEFAULT_CONFIG.get("sync_status", {}), **(config.get("sync_status", {}) if isinstance(config.get("sync_status"), dict) else {})}
    merged["insights"] = {**DEFAULT_CONFIG.get("insights", {}), **(config.get("insights", {}) if isinstance(config.get("insights"), dict) else {})}
    merged["insights_cache"] = {**DEFAULT_CONFIG.get("insights_cache", {}), **(config.get("insights_cache", {}) if isinstance(config.get("insights_cache"), dict) else {})}
    merged["conversation_analysis"] = {**DEFAULT_CONFIG.get("conversation_analysis", {}), **(config.get("conversation_analysis", {}) if isinstance(config.get("conversation_analysis"), dict) else {})}
    merged["mcp_autoconfig"] = {**DEFAULT_CONFIG.get("mcp_autoconfig", {}), **(config.get("mcp_autoconfig", {}) if isinstance(config.get("mcp_autoconfig"), dict) else {})}
    merged["remote_access"] = {**DEFAULT_CONFIG.get("remote_access", {}), **(config.get("remote_access", {}) if isinstance(config.get("remote_access"), dict) else {})}
    merged["security"] = {**DEFAULT_CONFIG.get("security", {}), **(config.get("security", {}) if isinstance(config.get("security"), dict) else {})}
    merged["security"]["rate_limit"] = {
        **DEFAULT_CONFIG.get("security", {}).get("rate_limit", {}),
        **(merged["security"].get("rate_limit", {}) if isinstance(merged["security"].get("rate_limit"), dict) else {}),
    }
    merged["security"]["rate_limit"]["buckets"] = {
        **DEFAULT_CONFIG.get("security", {}).get("rate_limit", {}).get("buckets", {}),
        **(
            merged["security"].get("rate_limit", {}).get("buckets", {})
            if isinstance(merged["security"].get("rate_limit", {}).get("buckets"), dict)
            else {}
        ),
    }
    merged["security"]["audit"] = {
        **DEFAULT_CONFIG.get("security", {}).get("audit", {}),
        **(merged["security"].get("audit", {}) if isinstance(merged["security"].get("audit"), dict) else {}),
    }
    if not merged["remote_access"].get("device_id"):
        merged["remote_access"]["device_id"] = str(merged.get("sync", {}).get("device_id") or uuid.uuid4())
    if not merged["remote_access"].get("device_secret"):
        merged["remote_access"]["device_secret"] = secrets.token_urlsafe(32)
    _ensure_security_baseline(merged)
    _config_cache = merged
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(merged, f, default_flow_style=False)
    _ensure_private_permissions()

def get_snapshot_token() -> str:
    config = load_config()
    if not config.get("snapshot_read_token"):
        rotate_snapshot_token()
    return config["snapshot_read_token"]

def rotate_snapshot_token() -> str:
    config = load_config()
    old_token = str(config.get("snapshot_read_token") or "")
    new_token = secrets.token_urlsafe(32)
    config["snapshot_read_token"] = new_token

    keys = config.get("llm_client_keys", {})
    if isinstance(keys, dict):
        bridge = keys.get("mnesis-bridge")
        if isinstance(bridge, dict) and str(bridge.get("managed_by") or "") == "mnesis":
            bridge_hash = str(bridge.get("hash") or bridge.get("sha256") or bridge.get("token_hash") or "")
            if bridge_hash and old_token and bridge_hash == _sha256_hex(old_token):
                bridge["hash"] = _sha256_hex(new_token)
                bridge["updated_at"] = _utc_now_iso()

    save_config(config)
    return new_token
