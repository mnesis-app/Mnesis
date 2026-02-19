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
        import subprocess
        script = f'display notification "{body}" with title "{title}"'
        subprocess.run(["osascript", "-e", script], timeout=3, check=False)
    except Exception:
        pass  # Fail silently on Windows or if osascript unavailable


def _get_mnesis_mcp_entry(config: dict, rest_port: int, mcp_port: int) -> dict:
    """Generate the Mnesis MCP entry for Claude Desktop config."""
    bridge_path = _find_bridge_executable()
    return {
        "command": bridge_path or "mcp-stdio-bridge",
        "args": [],
        "env": {
            "MNESIS_MCP_URL": f"http://127.0.0.1:{mcp_port}/mcp",
            "MNESIS_REST_URL": f"http://127.0.0.1:{rest_port}",
        }
    }


def _find_bridge_executable() -> Optional[str]:
    """Find the mcp-stdio-bridge binary."""
    candidates = [
        # Production: inside .app bundle
        os.path.join(os.path.dirname(__file__), '..', '..', 'Resources', 'bridge', 'mcp-stdio-bridge'),
        # Dev: project root
        os.path.join(os.path.dirname(__file__), '..', 'bridge', 'dist', 'mcp-stdio-bridge'),
    ]
    for p in candidates:
        p = os.path.normpath(p)
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def _check_and_restore_claude_config(config_path: str, mnesis_entry: dict):
    """Verify Mnesis is in Claude Desktop's MCP config. Restore if missing/changed."""
    try:
        config_path = os.path.expanduser(config_path)
        if not os.path.exists(config_path):
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


def _check_generic_http_config(config_path: str, client_key: str, mcp_port: int):
    """For HTTP clients (Cursor, Windsurf): ensure Mnesis server URL is registered."""
    try:
        config_path = os.path.expanduser(config_path)
        if not os.path.exists(config_path):
            return

        with open(config_path) as f:
            client_config = json.load(f)

        servers = client_config.get("mcpServers", {})
        mnesis_url = f"http://127.0.0.1:{mcp_port}/mcp/sse"

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

                transport = client.get("transport", "stdio")
                if transport == "stdio":
                    _check_and_restore_claude_config(config_path, mnesis_entry)
                elif transport == "http":
                    _check_generic_http_config(config_path, client_key, mcp_port)

        except Exception as e:
            logger.error(f"Config watcher error: {e}")

        time.sleep(WATCH_INTERVAL_SECONDS)


def start_config_watcher():
    """Start the config watcher in a background daemon thread."""
    thread = threading.Thread(target=_watcher_loop, name="mnesis-config-watcher", daemon=True)
    thread.start()
    logger.info("Config watcher thread started")
