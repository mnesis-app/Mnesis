# backend/memory/embedder.py
# from sentence_transformers import SentenceTransformer  <-- Moved inside
import logging
import warnings

from backend.memory.model_manager import MODEL_DIR, MODEL_REPO, model_manager

# Suppress warnings from huggingface/tokenizers
warnings.filterwarnings("ignore")

_model = None
_status: str = "loading"
logger = logging.getLogger(__name__)


def get_status() -> str:
    global _status
    if _model is not None:
        return "ready"
    return _status

def get_model():
    global _model, _status
    if _model is None:
        try:
            # Lazy import to speed up startup
            from sentence_transformers import SentenceTransformer

            model_dir = str(MODEL_DIR)

            # Preferred path: fully local folder managed by model_manager.
            if model_manager.check_model_exists():
                try:
                    _model = SentenceTransformer(model_dir, local_files_only=True)
                except Exception as local_err:
                    logger.warning(
                        "Local model load failed from %s (%s). Falling back to HF cache/repo.",
                        model_dir,
                        local_err,
                    )
                    _model = None

            # Secondary path: HF local cache only (no network).
            if _model is None:
                try:
                    _model = SentenceTransformer(MODEL_REPO, local_files_only=True)
                except Exception:
                    # Final fallback: allow network if cache isn't present.
                    _model = SentenceTransformer(MODEL_REPO)

            _status = "ready"
        except Exception:
            _status = "error"
            raise
    return _model


def embed(text: str) -> list[float]:
    return get_model().encode(text, normalize_embeddings=True).tolist()

def embed_batch(texts: list[str]) -> list[list[float]]:
    return get_model().encode(texts, normalize_embeddings=True, batch_size=32).tolist()
