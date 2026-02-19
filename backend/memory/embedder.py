# backend/memory/embedder.py
# from sentence_transformers import SentenceTransformer  <-- Moved inside
import warnings

# Suppress warnings from huggingface/tokenizers
warnings.filterwarnings("ignore")

_model = None
_status: str = "loading"

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
            # Use bge-small-en-v1.5 as per prompt
            _model = SentenceTransformer('BAAI/bge-small-en-v1.5')
            _status = "ready"
        except Exception:
            _status = "error"
            raise
    return _model

def embed(text: str) -> list[float]:
    return get_model().encode(text, normalize_embeddings=True).tolist()

def embed_batch(texts: list[str]) -> list[list[float]]:
    return get_model().encode(texts, normalize_embeddings=True, batch_size=32).tolist()
