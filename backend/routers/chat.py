"""
POST /api/v1/chat — RAG chat over the memory store.

Accepts a natural-language query, retrieves the most relevant memories via
hybrid search, builds a prompt with those memories as context, and streams
the LLM response back as Server-Sent Events.

Falls back gracefully (returns search results as plain text) when no LLM is
configured via the Insights settings.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Generator

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import load_config
from backend.database.client import get_db
from backend.memory.embedder import embed, get_status as embedder_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

# ── Request/response models ────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str
    limit: int = 12


# ── Memory retrieval ───────────────────────────────────────────────────────────

def _retrieve_memories(query: str, limit: int) -> list[dict]:
    """Hybrid search: vector similarity + lexical fallback."""
    db = get_db()
    if "memories" not in db.table_names():
        return []

    tbl = db.open_table("memories")
    where = "status = 'active' OR status = 'pending_review'"
    safe_limit = max(1, min(limit, 50))

    query_lower = query.lower()
    query_words = set(query_lower.split())

    # Try vector search first
    rows: list[dict] = []
    seen_ids: set[str] = set()

    if embedder_status() == "ready":
        try:
            vec = embed(query)
            vec_rows = tbl.search(vec).where(where).limit(safe_limit * 3).to_list()
            for row in vec_rows:
                mid = str(row.get("id") or "")
                if mid and mid not in seen_ids:
                    dist = float(row.get("_distance") or 1.0)
                    row["_score"] = max(0.0, 1.0 - dist)
                    rows.append(row)
                    seen_ids.add(mid)
        except Exception:
            pass

    # Lexical top-up
    if len(rows) < safe_limit:
        try:
            lex_rows = tbl.search().where(where).limit(safe_limit * 6).to_list()
            for row in lex_rows:
                mid = str(row.get("id") or "")
                if not mid or mid in seen_ids:
                    continue
                content_lower = str(row.get("content") or "").lower()
                if query_words and any(w in content_lower for w in query_words):
                    row["_score"] = 0.3
                    rows.append(row)
                    seen_ids.add(mid)
        except Exception:
            pass

    # Sort by score descending, take top N
    rows.sort(key=lambda r: r.get("_score", 0.0), reverse=True)
    rows = rows[:safe_limit]

    return [
        {
            "id": str(r.get("id") or ""),
            "content": str(r.get("content") or ""),
            "category": str(r.get("category") or ""),
            "source_llm": str(r.get("source_llm") or ""),
            "created_at": str(r.get("created_at") or ""),
            "score": round(float(r.get("_score", 0.0)), 3),
        }
        for r in rows
        if r.get("content")
    ]


# ── LLM streaming helpers ──────────────────────────────────────────────────────

def _stream_openai(prompt: str, runtime: dict) -> Generator[str, None, None]:
    base = (runtime.get("api_base_url") or "https://api.openai.com/v1").rstrip("/")
    model = runtime.get("model") or "gpt-4o-mini"
    headers = {"Content-Type": "application/json"}
    if runtime.get("api_key"):
        headers["Authorization"] = f"Bearer {runtime['api_key']}"
    body = {
        "model": model,
        "stream": True,
        "temperature": 0.5,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that answers questions based on the user's personal memory notes. Be concise and cite which memories you used."},
            {"role": "user", "content": prompt},
        ],
    }
    with httpx.Client(timeout=60.0) as client:
        with client.stream("POST", f"{base}/chat/completions", headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                yield f"\n\n[LLM error: {resp.status_code}]"
                return
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content") or ""
                    if delta:
                        yield delta
                except Exception:
                    continue


def _stream_anthropic(prompt: str, runtime: dict) -> Generator[str, None, None]:
    base = (runtime.get("api_base_url") or "https://api.anthropic.com/v1").rstrip("/")
    model = runtime.get("model") or "claude-3-5-haiku-latest"
    headers = {
        "x-api-key": runtime.get("api_key") or "",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 1024,
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": f"You are a helpful assistant that answers questions based on personal memory notes. Be concise and cite which memories you used.\n\n{prompt}",
            }
        ],
    }
    with httpx.Client(timeout=60.0) as client:
        with client.stream("POST", f"{base}/messages", headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                yield f"\n\n[LLM error: {resp.status_code}]"
                return
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    chunk = json.loads(line[6:])
                    if chunk.get("type") == "content_block_delta":
                        text = chunk.get("delta", {}).get("text") or ""
                        if text:
                            yield text
                except Exception:
                    continue


def _stream_ollama(prompt: str, runtime: dict) -> Generator[str, None, None]:
    base = (runtime.get("api_base_url") or "http://127.0.0.1:11434").rstrip("/")
    model = runtime.get("model") or "llama3.2:3b"
    headers = {"Content-Type": "application/json"}
    if runtime.get("api_key"):
        headers["Authorization"] = f"Bearer {runtime['api_key']}"
    body = {
        "model": model,
        "prompt": f"You are a helpful assistant that answers questions based on personal memory notes. Be concise and cite which memories you used.\n\n{prompt}",
        "stream": True,
        "options": {"temperature": 0.5},
    }
    with httpx.Client(timeout=120.0) as client:
        with client.stream("POST", f"{base}/api/generate", headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                yield f"\n\n[LLM error: {resp.status_code}]"
                return
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    text = chunk.get("response") or ""
                    if text:
                        yield text
                    if chunk.get("done"):
                        break
                except Exception:
                    continue


def _get_llm_stream(prompt: str) -> Generator[str, None, None] | None:
    """Return a token generator for the configured Insights LLM, or None."""
    cfg = load_config()
    insights_cfg = cfg.get("insights", {})

    if not insights_cfg.get("enabled", True):
        return None

    provider_raw = str(insights_cfg.get("provider") or "openai").strip().lower()
    aliases = {"oai": "openai", "chatgpt": "openai", "claude": "anthropic", "local": "ollama"}
    provider = aliases.get(provider_raw, provider_raw)

    api_key = (insights_cfg.get("api_key") or "").strip()
    model = (insights_cfg.get("model") or "").strip()
    api_base_url = (insights_cfg.get("api_base_url") or "").strip()

    if not api_key:
        import os
        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not model:
        if provider == "openai":
            model = "gpt-4o-mini"
        elif provider == "anthropic":
            model = "claude-3-5-haiku-latest"
        elif provider == "ollama":
            import os
            model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

    runtime = {"provider": provider, "api_key": api_key, "model": model, "api_base_url": api_base_url}

    # Require credentials for cloud providers
    if provider in ("openai", "anthropic") and not api_key:
        return None

    if provider == "openai":
        return _stream_openai(prompt, runtime)
    if provider == "anthropic":
        return _stream_anthropic(prompt, runtime)
    if provider == "ollama":
        return _stream_ollama(prompt, runtime)
    return None


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_prompt(query: str, memories: list[dict]) -> str:
    if not memories:
        return query

    ctx_parts = []
    for i, m in enumerate(memories, 1):
        date = str(m.get("created_at") or "")[:10]
        source = m.get("source_llm") or "unknown"
        content = m.get("content") or ""
        ctx_parts.append(f"[{i}] ({date}, via {source}) {content}")

    context = "\n".join(ctx_parts)
    return (
        f"The following are memories from the user's personal knowledge base:\n\n"
        f"{context}\n\n"
        f"Question: {query}\n\n"
        f"Answer based on the memories above. If a memory directly answers the question, "
        f"reference it by its number (e.g. [1]). If the memories don't contain enough "
        f"information, say so."
    )


# ── SSE event helpers ──────────────────────────────────────────────────────────

def _sse(event: str, data: str) -> str:
    """Format a single SSE message."""
    payload = data.replace("\n", "\\n")
    return f"event: {event}\ndata: {payload}\n\n"


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("")
async def chat(req: ChatRequest):
    query = req.query.strip()
    if not query:
        return {"error": "empty query"}

    memories = _retrieve_memories(query, req.limit)
    prompt = _build_prompt(query, memories)

    def generate() -> Generator[str, None, None]:
        # First event: send the citations
        yield _sse("citations", json.dumps(memories, default=str))

        llm_stream = _get_llm_stream(prompt)

        if llm_stream is None:
            # No LLM configured — return the raw memory list as a plain text answer
            if memories:
                text = "\n\n".join(
                    f"**[{i}]** {m['content']}"
                    for i, m in enumerate(memories, 1)
                )
                yield _sse("delta", text)
            else:
                yield _sse("delta", "No matching memories found.")
            yield _sse("done", "")
            return

        try:
            for token in llm_stream:
                if token:
                    yield _sse("delta", token)
        except Exception as e:
            logger.warning("Chat LLM stream error: %s", e)
            yield _sse("delta", f"\n\n[Error: {e}]")

        yield _sse("done", "")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
