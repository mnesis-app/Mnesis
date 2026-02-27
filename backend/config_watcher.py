"""
Config Watcher
==============
Background thread that watches LLM client config files.
When a client (e.g. Claude Desktop) overwrites its config,
this watcher detects the change and restores the Mnesis MCP entry.

Rate-limited to one notification per event type per hour to avoid spamming.
"""
import threading
import time
import os
import json
import yaml
import logging
import sys
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = 60
NOTIFICATION_RATE_LIMIT_HOURS = 1

_last_notified: Dict[str, datetime] = {}


def _load_clients_yaml() -> dict:
    """Load clients.yaml from the project root or adjacent to the executable."""
    search_paths = [
        os.path.join(os.path.dirname(__file__), '..', 'clients.yaml'),
        os.path.join(os.path.dirname(__file__), '..', '..', 'clients.yaml'),
        '/Applications/Mnesis.app/Contents/Resources/clients.yaml',
    ]
    for p in search_paths:
        p = os.path.normpath(p)
        if os.path.exists(p):
            try:
                with open(p) as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Failed to load clients.yaml from {p}: {e}")
    return {}


def _can_notify(event_key: str) -> bool:
    last = _last_notified.get(event_key)
    if last is None:
        return True
    return (datetime.now(timezone.utc) - last) > timedelta(hours=NOTIFICATION_RATE_LIMIT_HOURS)


def _send_notification(title: str, body: str, event_key: str):
    """Send a macOS native notification via osascript (best-effort)."""
    if not _can_notify(event_key):
        return
    _last_notified[event_key] = datetime.now(timezone.utc)

    try:
        import subprocess, shlex
        safe_title = title.replace('"', '\\"').replace('\\', '\\\\')
        safe_body = body.replace('"', '\\"').replace('\\', '\\\\')
        script = f'display notification "{safe_body}" with title "{safe_title}"'
        subprocess.run(["osascript", "-e", script], timeout=3, check=False)
    except Exception:
        pass  # Fail silently on Windows or if osascript unavailable


def _resolve_bridge() -> tuple[str, list[str]]:
    """
    Return (command, args) for the MCP stdio bridge process.

    Priority:
    1. Binary found by _find_bridge_executable()  (packaged build or backend/dist/)
    2. Dev fallback: python3 backend/mcp_stdio_bridge.py  (no build required)
    3. Best-effort path to a binary (may not exist yet)
    """
    binary = _find_bridge_executable()
    if binary:
        return binary, []

    # Dev fallback — works without any compilation.
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    script_path = os.path.abspath(os.path.join(repo_root, "backend", "mcp_stdio_bridge.py"))
    if os.path.isfile(script_path):
        logger.info("Bridge: using Python dev fallback → %s %s", sys.executable, script_path)
        return sys.executable, [script_path]

    # Last resort: best-effort absolute path (logged as warning).
    fallback = _best_effort_bridge_path()
    logger.warning("Bridge binary not found; using best-effort path: %s", fallback)
    return fallback, []


def _get_mnesis_mcp_entry(config: dict, rest_port: int, mcp_port: int) -> dict:
    """Generate the Mnesis MCP entry for Claude Desktop config."""
    api_key = config.get("snapshot_read_token", "")
    bridge_cmd, bridge_args = _resolve_bridge()
    return {
        "command": bridge_cmd,
        "args": bridge_args,
        "env": {
            # Base URL only; the bridge appends /mcp/sse itself.
            "MNESIS_MCP_URL": f"http://127.0.0.1:{rest_port}",
            "MNESIS_API_KEY": api_key,
        }
    }


def _best_effort_bridge_path() -> str:
    """
    Return an absolute bridge path even when executable-bit checks fail.
    This avoids writing plain 'mcp-stdio-bridge' commands that depend on PATH.
    """
    exe_name = "mcp-stdio-bridge.exe" if os.name == "nt" else "mcp-stdio-bridge"
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), exe_name), # Next to mnesis-backend executable
        os.path.join(os.path.dirname(__file__), "dist", exe_name), # Simple dev
        os.path.join(os.path.dirname(__file__), "..", "backend", "dist", exe_name), # Root relative dev
        os.path.join("/Applications/Mnesis.app/Contents/Resources/backend", exe_name), # macOS package
    ]
    for raw_path in candidates:
        p = os.path.abspath(os.path.expandvars(os.path.expanduser(raw_path)))
        if os.path.isfile(p):
            return p
    # Last-resort absolute path in the current working directory.
    return os.path.abspath(os.path.join("backend", "dist", exe_name))


def _find_bridge_executable() -> Optional[str]:
    """Find the mcp-stdio-bridge binary."""
    exe_name = "mcp-stdio-bridge.exe" if os.name == "nt" else "mcp-stdio-bridge"

    candidates = []

    # Preferred: explicit path passed by Electron main process.
    env_bridge = os.environ.get("MNESIS_BRIDGE_PATH")
    if env_bridge:
        candidates.append(env_bridge)

    # Packaged backend: bridge is next to mnesis-backend in Resources/backend.
    try:
        backend_exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(backend_exe_dir, exe_name))
    except Exception:
        pass

    # Dev/runtime from source tree.
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    candidates.append(os.path.join(repo_root, "backend", "dist", exe_name))
    candidates.append(os.path.join(os.path.dirname(__file__), "dist", exe_name))

    for raw_path in candidates:
        p = os.path.abspath(os.path.expandvars(os.path.expanduser(raw_path)))
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def _check_and_restore_claude_config(config_path: str, mnesis_entry: dict):
    """Verify Mnesis is in Claude Desktop's MCP config. Restore if missing/changed."""
    try:
        config_path = os.path.expanduser(config_path)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        if not os.path.exists(config_path):
            with open(config_path, "w") as f:
                json.dump({"mcpServers": {"mnesis": mnesis_entry}}, f, indent=2)
            logger.info(f"Created MCP config: {config_path}")
            return

        with open(config_path) as f:
            client_config = json.load(f)

        mcp_servers = client_config.get("mcpServers", {})
        current = mcp_servers.get("mnesis")

        if current == mnesis_entry:
            return  # Already correct

        # Restore
        logger.info(f"Restoring Mnesis entry in {config_path}")
        mcp_servers["mnesis"] = mnesis_entry
        client_config["mcpServers"] = mcp_servers

        with open(config_path, "w") as f:
            json.dump(client_config, f, indent=2)

        _send_notification(
            "Mnesis",
            "Your memory connection to Claude was restored automatically.",
            f"restore_{os.path.basename(config_path)}"
        )

    except Exception as e:
        logger.error(f"Failed to check/restore {config_path}: {e}")


def _check_generic_http_config(config_path: str, client_key: str, rest_port: int, token: str):
    """For HTTP clients (Cursor, Windsurf, AnythingLLM, ChatGPT, Gemini): ensure Mnesis server URL is registered."""
    try:
        config_path = os.path.expanduser(config_path)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        # Build the SSE URL with query token fallback for robust auth across HTTP clients
        mnesis_url = f"http://127.0.0.1:{rest_port}/mcp/sse"
        if token:
            mnesis_url = f"{mnesis_url}?token={token}"

        if not os.path.exists(config_path):
            with open(config_path, "w") as f:
                json.dump({"mcpServers": {"mnesis": {"url": mnesis_url}}}, f, indent=2)
            logger.info(f"Created MCP config for {client_key}: {config_path}")
            return

        with open(config_path) as f:
            client_config = json.load(f)

        servers = client_config.get("mcpServers", {})

        if servers.get("mnesis", {}).get("url") == mnesis_url:
            return

        servers["mnesis"] = {"url": mnesis_url}
        client_config["mcpServers"] = servers

        with open(config_path, "w") as f:
            json.dump(client_config, f, indent=2)

        _send_notification(
            "Mnesis",
            f"Memory connection to {client_key} was restored.",
            f"restore_{client_key}"
        )
    except Exception as e:
        logger.error(f"Failed to check generic HTTP config {config_path}: {e}")


_CLIENT_INSTALL_MARKERS_MAC = {
    "claude_desktop": ["/Applications/Claude.app"],
    "cursor": ["/Applications/Cursor.app"],
    "windsurf": ["/Applications/Windsurf.app"],
    "chatgpt": ["/Applications/ChatGPT.app"],
}


def _is_client_installed(client_key: str, config_path: str) -> bool:
    # On macOS, check the application bundle first — this is the authoritative signal.
    # Checking config file existence first was a bug: Mnesis itself creates those files,
    # so subsequent runs would always see them and falsely report the app as installed.
    if sys.platform == "darwin":
        markers = _CLIENT_INSTALL_MARKERS_MAC.get(str(client_key or "").strip().lower(), [])
        if markers:
            # Markers are defined for this client — use them as the sole signal.
            return any(os.path.exists(m) for m in markers)

    # Fallback: config file existence (non-macOS, or clients with no app markers defined).
    expanded = os.path.expanduser(config_path)
    return os.path.exists(expanded)


def _configure_client_once(client_key: str, client: dict, rest_port: int, mnesis_entry: dict, token: str) -> dict:
    config_path = str(client.get("config_path") or "").strip()
    transport = str(client.get("transport") or "stdio").strip().lower()
    if not config_path:
        return {"client": client_key, "installed": False, "configured": False, "reason": "no_config_path"}
    installed = _is_client_installed(client_key, config_path)
    if not installed:
        return {"client": client_key, "installed": False, "configured": False, "reason": "not_detected"}
    try:
        if transport == "stdio":
            _check_and_restore_claude_config(config_path, mnesis_entry)
        else:
            _check_generic_http_config(config_path, client_key, rest_port, token)
        return {"client": client_key, "installed": True, "configured": True, "reason": "ok"}
    except Exception as e:
        logger.error(f"Auto-config failed for {client_key}: {e}")
        return {"client": client_key, "installed": True, "configured": False, "reason": str(e)}


def auto_configure_installed_clients() -> dict:
    """
    Detect installed clients and ensure each receives a working Mnesis MCP entry.
    Safe to run repeatedly (idempotent).
    """
    from backend.config import load_config

    config = load_config(force_reload=True)
    rest_port = config.get("rest_port", 7860)
    mcp_port = config.get("mcp_port", 7861)
    clients_data = _load_clients_yaml()
    clients = clients_data.get("clients", {}) if isinstance(clients_data, dict) else {}
    mnesis_entry = _get_mnesis_mcp_entry(config, rest_port, mcp_port)

    detected: list[str] = []
    configured: list[str] = []
    errors: list[str] = []

    for client_key, client in clients.items():
        if not isinstance(client, dict):
            continue
        outcome = _configure_client_once(str(client_key), client, rest_port, mnesis_entry, str(config.get("snapshot_read_token") or ""))
        if outcome.get("installed"):
            detected.append(str(client_key))
        if outcome.get("configured"):
            configured.append(str(client_key))
        elif outcome.get("installed"):
            reason = str(outcome.get("reason") or "unknown")
            errors.append(f"{client_key}: {reason}")

    return {
        "status": "ok" if not errors else "partial",
        "detected_clients": sorted(list(dict.fromkeys(detected))),
        "configured_clients": sorted(list(dict.fromkeys(configured))),
        "error_count": len(errors),
        "errors": errors[:8],
    }


def run_first_launch_autoconfigure(force: bool = False) -> dict:
    """
    Run MCP client auto-detection/auto-configuration once on first app launch.
    """
    from backend.config import load_config, save_config

    cfg = load_config(force_reload=True)
    state = cfg.get("mcp_autoconfig", {}) if isinstance(cfg.get("mcp_autoconfig"), dict) else {}
    enabled = bool(state.get("enabled", True))
    if not enabled and not force:
        return {"status": "disabled", "detected_clients": [], "configured_clients": [], "error_count": 0, "errors": []}
    if state.get("first_launch_done") and not force:
        return {
            "status": "skipped",
            "detected_clients": list(state.get("detected_clients") or []),
            "configured_clients": list(state.get("configured_clients") or []),
            "error_count": 0,
            "errors": [],
        }

    result = auto_configure_installed_clients()
    next_state = {
        "enabled": enabled,
        "first_launch_done": True,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "detected_clients": result.get("detected_clients", []),
        "configured_clients": result.get("configured_clients", []),
        "last_error": "; ".join(result.get("errors", [])[:2]) if result.get("errors") else None,
    }
    cfg["mcp_autoconfig"] = next_state
    save_config(cfg)
    return result


def _watcher_loop():
    """Main watch loop — runs in a daemon thread."""
    logger.info("Config watcher started")

    from backend.config import load_config
    config = load_config()
    rest_port = config.get("rest_port", 7860)
    mcp_port = config.get("mcp_port", 7861)

    clients_data = _load_clients_yaml()
    clients = clients_data.get("clients", {})

    mnesis_entry = _get_mnesis_mcp_entry(config, rest_port, mcp_port)

    while True:
        try:
            # Reload config in case ports changed
            config = load_config()
            rest_port = config.get("rest_port", 7860)
            mcp_port = config.get("mcp_port", 7861)
            mnesis_entry = _get_mnesis_mcp_entry(config, rest_port, mcp_port)

            for client_key, client in clients.items():
                config_path = client.get("config_path")
                if not config_path:
                    continue

                # Only restore configs for clients that are actually installed.
                # Without this check the watcher would create config files for every
                # client in mcp_clients.yaml regardless of whether the app is present,
                # causing false-positive "configured" reports and unnecessary restores.
                if not _is_client_installed(str(client_key), config_path):
                    continue

                transport = client.get("transport", "stdio")
                if transport == "stdio":
                    _check_and_restore_claude_config(config_path, mnesis_entry)
                elif transport == "http":
                    _check_generic_http_config(config_path, client_key, rest_port, str(config.get("snapshot_read_token") or ""))

        except Exception as e:
            logger.error(f"Config watcher error: {e}")

        time.sleep(WATCH_INTERVAL_SECONDS)


def start_config_watcher():
    """Start the config watcher in a background daemon thread."""
    thread = threading.Thread(target=_watcher_loop, name="mnesis-config-watcher", daemon=True)
    thread.start()
    logger.info("Config watcher thread started")
