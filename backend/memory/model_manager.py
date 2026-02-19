import os
import requests
import hashlib
import logging
import shutil
from pathlib import Path

# Constants for bge-small-en-v1.5
MODEL_REPO = "BAAI/bge-small-en-v1.5"
MODEL_FILES = [
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "special_tokens_map.json",
    "modules.json"
]
# Base URL for huggingface
HF_BASE_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/main"

# Local path
if os.environ.get("MNESIS_APPDATA_DIR"):
    DATA_DIR = os.path.join(os.environ["MNESIS_APPDATA_DIR"], "data")
elif os.name == 'nt':
    DATA_DIR = os.path.join(os.environ['APPDATA'], 'Mnesis', 'data')
else:
    DATA_DIR = os.path.join(os.path.expanduser('~'), '.mnesis', 'data')

MODEL_DIR = Path(DATA_DIR) / "models" / "bge-small-en-v1.5"

logger = logging.getLogger(__name__)

class ModelManager:
    def __init__(self):
        self.progress = {"status": "idle", "file": None, "percent": 0, "downloaded": 0, "total": 0}

    def check_model_exists(self) -> bool:
        if not MODEL_DIR.exists():
            return False
        # Simple check: do all files exist?
        for f in MODEL_FILES:
            if not (MODEL_DIR / f).exists():
                return False
        return True

    def get_progress(self):
        return self.progress

    def download_model(self):
        try:
            self.progress["status"] = "starting"
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            
            total_files = len(MODEL_FILES)
            
            for idx, filename in enumerate(MODEL_FILES):
                url = f"{HF_BASE_URL}/{filename}"
                dest_path = MODEL_DIR / filename
                
                # Check if already exists (skip verification for speed in MVP, or verify size)
                if dest_path.exists():
                     self.progress["file"] = filename
                     self.progress["percent"] = 100
                     continue

                self.progress["status"] = "downloading"
                self.progress["file"] = filename
                self.progress["percent"] = 0
                
                # Download with streaming
                with requests.get(url, stream=True) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    self.progress["total"] = total_size
                    
                    with open(dest_path, 'wb') as f:
                        downloaded = 0
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                            downloaded += len(chunk)
                            self.progress["downloaded"] = downloaded
                            if total_size > 0:
                                self.progress["percent"] = int((downloaded / total_size) * 100)
            
            self.progress["status"] = "complete"
            self.progress["percent"] = 100
            
        except Exception as e:
            logger.error(f"Download failed: {e}")
            self.progress["status"] = "error"
            self.progress["error"] = str(e)
            # Cleanup partial?
            # shutil.rmtree(MODEL_DIR) 

model_manager = ModelManager()
