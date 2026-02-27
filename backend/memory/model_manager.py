import logging
import os
from pathlib import Path

from huggingface_hub import hf_hub_download

# Constants for bge-small-en-v1.5
MODEL_REPO = "BAAI/bge-small-en-v1.5"
# Required files to load the model from a local sentence-transformers folder.
MODEL_FILES = [
    "config.json",
    "config_sentence_transformers.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "1_Pooling/config.json",
]

# Local path
if os.environ.get("MNESIS_APPDATA_DIR"):
    DATA_DIR = os.path.join(os.environ["MNESIS_APPDATA_DIR"], "data")
elif os.name == "nt":
    DATA_DIR = os.path.join(os.environ["APPDATA"], "Mnesis", "data")
else:
    DATA_DIR = os.path.join(os.path.expanduser("~"), ".mnesis", "data")

MODEL_DIR = Path(DATA_DIR) / "models" / "bge-small-en-v1.5"

logger = logging.getLogger(__name__)


class ModelManager:
    def __init__(self):
        self.progress = {"status": "idle", "file": None, "percent": 0, "downloaded": 0, "total": 0}

    def _file_path(self, rel_path: str) -> Path:
        return MODEL_DIR / rel_path

    def check_model_exists(self) -> bool:
        if not MODEL_DIR.exists():
            return False
        for rel_path in MODEL_FILES:
            if not self._file_path(rel_path).exists():
                return False
        return True

    def get_progress(self):
        return self.progress

    def mark_complete(self):
        self.progress["status"] = "complete"
        self.progress["percent"] = 100

    def download_model(self):
        try:
            self.progress["status"] = "starting"
            self.progress["file"] = None
            self.progress["percent"] = 0
            self.progress["downloaded"] = 0
            self.progress["total"] = len(MODEL_FILES)
            self.progress.pop("error", None)

            MODEL_DIR.mkdir(parents=True, exist_ok=True)

            total_files = len(MODEL_FILES)
            for idx, rel_path in enumerate(MODEL_FILES):
                dest_path = self._file_path(rel_path)
                self.progress["file"] = rel_path

                if dest_path.exists():
                    self.progress["downloaded"] = idx + 1
                    self.progress["percent"] = int(((idx + 1) / total_files) * 100)
                    continue

                dest_path.parent.mkdir(parents=True, exist_ok=True)
                self.progress["status"] = "downloading"
                self.progress["percent"] = int((idx / total_files) * 100)

                if "/" in rel_path:
                    subfolder, filename = rel_path.rsplit("/", 1)
                else:
                    subfolder, filename = None, rel_path

                hf_hub_download(
                    repo_id=MODEL_REPO,
                    filename=filename,
                    subfolder=subfolder,
                    local_dir=str(MODEL_DIR),
                    force_download=False,
                )

                self.progress["downloaded"] = idx + 1
                self.progress["percent"] = int(((idx + 1) / total_files) * 100)

            self.mark_complete()
        except Exception as e:
            logger.error(f"Download failed: {e}")
            self.progress["status"] = "error"
            self.progress["error"] = str(e)


model_manager = ModelManager()
