import yaml
import os
import secrets
from typing import Optional

if os.environ.get("MNESIS_APPDATA_DIR"):
    CONFIG_DIR = os.environ["MNESIS_APPDATA_DIR"]
elif os.name == 'nt':
    CONFIG_DIR = os.path.join(os.environ['APPDATA'], 'Mnesis')
else:
    CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.mnesis')

if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(CONFIG_DIR, "config.yaml")

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
}

_config_cache = None

def load_config(force_reload: bool = False) -> dict:
    global _config_cache
    if _config_cache and not force_reload:
        return _config_cache
    
    if not os.path.exists(CONFIG_PATH):
        _config_cache = DEFAULT_CONFIG.copy()
        # Generate initial token
        _config_cache["snapshot_read_token"] = secrets.token_urlsafe(32)
        save_config(_config_cache)
    else:
        with open(CONFIG_PATH, "r") as f:
            _config_cache = yaml.safe_load(f) or DEFAULT_CONFIG.copy()
            
    return _config_cache

def save_config(config: dict):
    global _config_cache
    # Merge with defaults so new keys are always present
    merged = {**DEFAULT_CONFIG, **config}
    _config_cache = merged
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(merged, f, default_flow_style=False)

def get_snapshot_token() -> str:
    config = load_config()
    if not config.get("snapshot_read_token"):
        rotate_snapshot_token()
    return config["snapshot_read_token"]

def rotate_snapshot_token() -> str:
    config = load_config()
    new_token = secrets.token_urlsafe(32)
    config["snapshot_read_token"] = new_token
    save_config(config)
    return new_token
