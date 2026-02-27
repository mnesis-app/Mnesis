from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

from backend.config import load_config
from backend.database.client import get_db
from backend.database.schema import EMBEDDING_DIM
from backend.memory.core import create_memory
from backend.memory.embedder import embed, get_status as get_embedder_status
from backend.memory.write_queue import enqueue_write

SUPPORTED_LLM_PROVIDERS = {"openai", "anthropic", "ollama"}
_FIRST_PERSON_PATTERN = re.compile(
    r"\b(i|i'm|i've|i'd|my|mine|me|je|j'|moi|mon|ma|mes|nous|notre|nos)\b",
    flags=re.IGNORECASE,
)
_USER_ANCHOR_PATTERN = re.compile(
    r"\b(the user|user's|l'utilisateur|utilisateur|lutilisateur)\b(?!\s*/)",
    flags=re.IGNORECASE,
)
_BROKEN_USER_ANCHOR_PATTERN = re.compile(r"\b(?:the\s+)?user\s*/", flags=re.IGNORECASE)
_GENERIC_FACT_PATTERN = re.compile(
    r"\b("
    r"is\s+(an?|the)\s+(?:[a-z0-9][a-z0-9_\-]*\s+){0,4}(open|standard|protocol|framework|library|language|concept|method|tool|model)\b|"
    r"refers to\b|means\b|defined as\b|"
    r"est\s+(un|une|le|la)\s+(?:[a-z0-9à-ÿ][a-z0-9à-ÿ_\-]*\s+){0,4}(protocole|standard|framework|biblioth[eè]que|langage|concept|m[eé]thode|outil|mod[eè]le)\b|"
    r"fait r[eé]f[eé]rence [aà]\b|d[eé]signe\b"
    r")",
    flags=re.IGNORECASE,
)
_DEFINITION_STYLE_PATTERN = re.compile(
    r"\b("
    r"(?:the user|l'utilisateur)\b[^.!?\n]{0,80}\b(?:is|est)\s+(?:an?|the|un|une|le|la)\s+[^.!?\n]{0,80}\b("
    r"language|protocol|framework|library|standard|concept|method|tool|model|stack|"
    r"langage|protocole|framework|biblioth[eè]que|standard|concept|m[eé]thode|outil|mod[eè]le"
    r")\b|"
    r"(?:the user|l'utilisateur)\b[^.!?\n]{0,80}\b(?:means|refers to|defined as|d[eé]signe|fait r[eé]f[eé]rence [aà])\b"
    r")",
    flags=re.IGNORECASE,
)
_DURABLE_MEMORY_PATTERN = re.compile(
    r"\b("
    r"prefers|likes|loves|hates|always|never|uses|works on|working on|building|goal|plans|"
    r"name is|is from|lives in|role|job|team|relationship|project|stack|"
    r"pr[eé]f[eè]re|aime|d[eé]teste|utilise|travaille sur|d[eé]veloppe|objectif|projet|"
    r"nom est|habite|r[oô]le|m[eé]tier|[eé]quipe|relation"
    r")\b",
    flags=re.IGNORECASE,
)
_QUESTION_STYLE_PATTERN = re.compile(
    r"\b("
    r"asks?|asked|wants to know|is asking|question|"
    r"demande|a demand[eé]|veut savoir|question"
    r")\b",
    flags=re.IGNORECASE,
)
_TIME_WINDOW_PATTERN = re.compile(
    r"\b\d{1,2}(?::|h)\d{2}\s*(?:-|–|to|a|à)\s*\d{1,2}(?::|h)\d{2}\b",
    flags=re.IGNORECASE,
)
_TIME_HINT_PATTERN = re.compile(
    r"\b("
    r"today|tomorrow|tonight|this morning|this afternoon|this evening|"
    r"aujourd'hui|demain|ce matin|cet apr[eè]s-midi|ce soir|demain matin|demain soir"
    r")\b",
    flags=re.IGNORECASE,
)
_REASON_CLAUSE_PATTERN = re.compile(
    r"\b(?:because|since|due to|as|car|parce que)\b\s+([^.!?\n]{8,220})",
    flags=re.IGNORECASE,
)
_NEED_CLAUSE_PATTERN = re.compile(
    r"\b(?:i need to|i have to|i must|je dois|il faut que je)\b\s+([^.!?\n]{8,220})",
    flags=re.IGNORECASE,
)
_VAGUE_CAPABILITY_PATTERN = re.compile(
    r"^\s*(?:the user|l'utilisateur)\s+(?:can|could|may|might|peut)\b",
    flags=re.IGNORECASE,
)
_WEAK_QUALIFIER_PATTERN = re.compile(
    r"\b("
    r"if needed|if necessary|if required|si besoin|au besoin|"
    r"more elaborate|more complex|more advanced|"
    r"additional requests?"
    r")\b",
    flags=re.IGNORECASE,
)
_ANALYSIS_TAG = "auto:conversation-analysis"
_ANALYSIS_MSGCOUNT_PREFIX = "auto:conversation-analysis:msgcount:"
_ANALYSIS_PROVIDER_PREFIX = "auto:conversation-analysis:provider:"
_ANALYSIS_RESULT_PREFIX = "auto:conversation-analysis:result:"
_ANALYSIS_INDEX_TABLE = "conversation_analysis_index"
_ANALYSIS_CANDIDATES_TABLE = "conversation_analysis_candidates"
_TOPIC_STOPWORDS = {
    "the",
    "this",
    "that",
    "these",
    "those",
    "with",
    "from",
    "into",
    "about",
    "your",
    "their",
    "will",
    "would",
    "should",
    "could",
    "using",
    "used",
    "uses",
    "user",
    "users",
    "application",
    "applications",
    "system",
    "saa",
    "saas",
    "modern",
    "mobile",
    "first",
    "called",
    "utilize",
    "utilizes",
    "utiliser",
    "utilise",
    "projet",
    "project",
    "projects",
    "pour",
    "avec",
    "dans",
    "sur",
    "des",
    "une",
    "les",
    "est",
    "sont",
    "sera",
    "seront",
    "lutilisateur",
    "utilisateur",
}
_ANALYSIS_RUN_LOCK: asyncio.Lock | None = None
_ANALYSIS_RUNTIME_STATUS: dict[str, Any] = {
    "running": False,
    "trigger": None,
    "started_at": None,
    "last_completed_at": None,
    "last_duration_ms": None,
    "last_error": None,
    "last_result_summary": None,
    "phase_step": 0,
    "phase_total_steps": 0,
    "phase_label": "",
    "phase_detail": "",
    "phase_items_done": 0,
    "phase_items_total": 0,
    "phase_items_unit": "",
    "phase_progress": 0.0,
    "phase_updated_at": None,
}


def _get_run_lock() -> asyncio.Lock:
    global _ANALYSIS_RUN_LOCK
    if _ANALYSIS_RUN_LOCK is None:
        _ANALYSIS_RUN_LOCK = asyncio.Lock()
    return _ANALYSIS_RUN_LOCK


def get_analysis_runtime_status() -> dict[str, Any]:
    lock = _get_run_lock()
    status = dict(_ANALYSIS_RUNTIME_STATUS)
    status["running"] = bool(lock.locked())
    try:
        cfg = load_config(force_reload=True)
        analysis_cfg = cfg.get("conversation_analysis", {}) if isinstance(cfg.get("conversation_analysis"), dict) else {}
        llm_required = bool(analysis_cfg.get("require_llm_configured", True))
    except Exception:
        llm_required = True
    runtime = _resolve_runtime()
    llm_configured = bool(runtime.get("provider") in SUPPORTED_LLM_PROVIDERS and _runtime_can_use_llm(runtime))
    status["llm_required"] = llm_required
    status["llm_configured"] = llm_configured
    status["llm_provider"] = str(runtime.get("provider") or "")
    if llm_required and not llm_configured:
        status["llm_block_reason"] = _runtime_unconfigured_reason(runtime)
    else:
        status["llm_block_reason"] = None
    return status


def _set_runtime_phase(
    *,
    step: int,
    total_steps: int,
    label: str,
    detail: str = "",
    items_done: int = 0,
    items_total: int = 0,
    items_unit: str = "",
):
    safe_total = max(0, int(total_steps or 0))
    safe_step = max(0, min(int(step or 0), safe_total if safe_total > 0 else int(step or 0)))
    safe_items_total = max(0, int(items_total or 0))
    safe_items_done = max(0, int(items_done or 0))
    if safe_items_total > 0:
        safe_items_done = min(safe_items_done, safe_items_total)
    if safe_total > 0:
        base = safe_step / safe_total
        if safe_items_total > 0:
            micro = (safe_items_done / safe_items_total) / safe_total
            progress = min(1.0, max(0.0, base - (1.0 / safe_total) + micro))
        else:
            progress = min(1.0, max(0.0, base))
    else:
        progress = 0.0
    _ANALYSIS_RUNTIME_STATUS["phase_step"] = safe_step
    _ANALYSIS_RUNTIME_STATUS["phase_total_steps"] = safe_total
    _ANALYSIS_RUNTIME_STATUS["phase_label"] = str(label or "").strip()
    _ANALYSIS_RUNTIME_STATUS["phase_detail"] = str(detail or "").strip()
    _ANALYSIS_RUNTIME_STATUS["phase_items_done"] = safe_items_done
    _ANALYSIS_RUNTIME_STATUS["phase_items_total"] = safe_items_total
    _ANALYSIS_RUNTIME_STATUS["phase_items_unit"] = str(items_unit or "").strip().lower()
    _ANALYSIS_RUNTIME_STATUS["phase_progress"] = float(progress)
    _ANALYSIS_RUNTIME_STATUS["phase_updated_at"] = datetime.now(timezone.utc).isoformat()


def _escape_sql(value: str) -> str:
    return str(value).replace("'", "''")


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            pass
    if isinstance(value, str) and value:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _normalize_source_timestamp(value: Any) -> str:
    dt = _to_dt(value)
    # Ignore sentinel/unknown timestamps commonly serialized as unix epoch.
    if dt.year <= 1971:
        return ""
    return dt.isoformat()


def _normalize_provider(provider: Any) -> str:
    raw = str(provider or "auto").strip().lower()
    aliases = {
        "oai": "openai",
        "chatgpt": "openai",
        "claude": "anthropic",
        "local": "ollama",
        "local-ollama": "ollama",
    }
    return aliases.get(raw, raw)


def _normalize_confidence(value: Any, default: float = 0.8) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = default
    return max(0.5, min(0.99, numeric))


def _normalize_category(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "identity": "identity",
        "about_user": "identity",
        "profile": "identity",
        "preference": "preferences",
        "preferences": "preferences",
        "working_style": "preferences",
        "skill": "skills",
        "skills": "skills",
        "tech_stack": "skills",
        "relationship": "relationships",
        "relationships": "relationships",
        "project": "projects",
        "projects": "projects",
        "history": "history",
        "event": "history",
        "working": "working",
    }
    return aliases.get(raw, "preferences")


def _normalize_level(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"semantic", "episodic", "working"}:
        return raw
    if raw in {"stable", "long_term", "long-term"}:
        return "semantic"
    if raw in {"temporary", "short_term", "short-term"}:
        return "working"
    return "semantic"


def _extract_json_obj(text: str) -> Optional[dict]:
    if not text:
        return None
    payload = text.strip()
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = payload.find("{")
    end = payload.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    fragment = payload[start : end + 1]
    try:
        parsed = json.loads(fragment)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def _normalize_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _read_analyzed_msgcount(tags: list[str]) -> Optional[int]:
    for tag in tags:
        lower = tag.lower()
        if not lower.startswith(_ANALYSIS_MSGCOUNT_PREFIX):
            continue
        raw = lower[len(_ANALYSIS_MSGCOUNT_PREFIX) :]
        try:
            return max(0, int(raw))
        except Exception:
            continue
    return None


def _read_analysis_result(tags: list[str]) -> Optional[str]:
    for tag in tags:
        lower = tag.lower()
        if not lower.startswith(_ANALYSIS_RESULT_PREFIX):
            continue
        value = lower[len(_ANALYSIS_RESULT_PREFIX) :].strip()
        if value in {"has_memory", "none", "error"}:
            return value
    return None


def _build_analysis_tags(existing_tags: Any, provider: str, message_count: int, result: Optional[str] = None) -> list[str]:
    tags = _normalize_tags(existing_tags)
    cleaned: list[str] = []
    for tag in tags:
        lower = tag.lower()
        if lower.startswith(_ANALYSIS_MSGCOUNT_PREFIX):
            continue
        if lower.startswith(_ANALYSIS_PROVIDER_PREFIX):
            continue
        if lower.startswith(_ANALYSIS_RESULT_PREFIX):
            continue
        cleaned.append(tag)

    lowered = {t.lower() for t in cleaned}
    if _ANALYSIS_TAG not in lowered:
        cleaned.append(_ANALYSIS_TAG)

    provider_slug = re.sub(r"[^a-z0-9_-]+", "", str(provider or "heuristic").strip().lower()) or "heuristic"
    cleaned.append(f"{_ANALYSIS_MSGCOUNT_PREFIX}{max(0, int(message_count))}")
    cleaned.append(f"{_ANALYSIS_PROVIDER_PREFIX}{provider_slug}")
    if result in {"has_memory", "none", "error"}:
        cleaned.append(f"{_ANALYSIS_RESULT_PREFIX}{result}")
    return _normalize_tags(cleaned)


def _load_conversation_ids_with_analyzer_memories(limit: int = 200000) -> set[str]:
    db = get_db()
    if "memories" not in db.table_names():
        return set()
    tbl = db.open_table("memories")
    rows = tbl.search().limit(limit).to_list()
    out: set[str] = set()
    for row in rows:
        source_llm = str(row.get("source_llm") or "").strip().lower()
        if not source_llm.startswith("conversation-analyzer:"):
            continue
        if str(row.get("status") or "").strip().lower() == "archived":
            continue
        conv_id = str(row.get("source_conversation_id") or "").strip()
        if conv_id:
            out.add(conv_id)
    return out


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _load_analysis_index_map(limit: int = 300000) -> dict[str, dict]:
    db = get_db()
    if _ANALYSIS_INDEX_TABLE not in db.table_names():
        return {}
    rows = db.open_table(_ANALYSIS_INDEX_TABLE).search().limit(limit).to_list()
    out: dict[str, dict] = {}
    for row in rows:
        conv_id = str(row.get("conversation_id") or row.get("id") or "").strip()
        if conv_id:
            out[conv_id] = row
    return out


def _index_row_is_fresh(index_row: dict, conversation_row: dict, message_count: int) -> bool:
    result = str(index_row.get("last_result") or "").strip().lower()
    if result not in {"has_memory", "none"}:
        return False
    indexed_msg_count = _safe_int(index_row.get("message_count"), default=-1)
    if indexed_msg_count < int(message_count):
        return False

    conv_hash = str(conversation_row.get("raw_file_hash") or "").strip().lower()
    index_hash = str(index_row.get("conversation_hash") or "").strip().lower()
    if conv_hash:
        return bool(index_hash and index_hash == conv_hash)
    return True


def _contains_first_person(text: str) -> bool:
    return bool(_FIRST_PERSON_PATTERN.search(text or ""))


def _contains_user_anchor(text: str) -> bool:
    return bool(_USER_ANCHOR_PATTERN.search(text or ""))


def _looks_vague_capability_memory(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.lower()
    if _VAGUE_CAPABILITY_PATTERN.search(lowered) and _WEAK_QUALIFIER_PATTERN.search(lowered):
        return True
    return False


def _looks_generic_non_memory(text: str) -> bool:
    """
    Reject user-anchored sentences that still look like generic encyclopedia facts
    instead of personal memories.
    """
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.lower()
    if _BROKEN_USER_ANCHOR_PATTERN.search(lowered):
        return True
    has_anchor = _contains_user_anchor(value)
    if not has_anchor:
        return True
    if _QUESTION_STYLE_PATTERN.search(lowered):
        return True
    if _looks_vague_capability_memory(lowered):
        return True
    if _DEFINITION_STYLE_PATTERN.search(lowered) and not _DURABLE_MEMORY_PATTERN.search(lowered):
        return True
    if _GENERIC_FACT_PATTERN.search(lowered) and not _DURABLE_MEMORY_PATTERN.search(lowered):
        return True
    return False


def _to_third_person(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""

    # Fast replacements for common EN/FR first-person forms.
    replacements = [
        (r"\bI am\b", "The user is"),
        (r"\bI'm\b", "The user is"),
        # Keep I/O and similar technical tokens intact.
        (r"\bI\b(?!\s*/)", "the user"),
        (r"\bmy\b", "the user's"),
        (r"\bmine\b", "the user's"),
        (r"\bme\b", "the user"),
        (r"\bje suis\b", "L'utilisateur est"),
        (r"\bj['`]ai\b", "L'utilisateur a"),
        (r"\bje\b", "l'utilisateur"),
        (r"\bmoi\b", "l'utilisateur"),
        (r"\bmon\b", "le"),
        (r"\bma\b", "la"),
        (r"\bmes\b", "les"),
        (r"\bnous\b", "l'utilisateur"),
        (r"\bnotre\b", "le"),
        (r"\bnos\b", "les"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)

    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return ""
    if value[-1] not in ".!?":
        value += "."
    return value[0].upper() + value[1:]


def _clean_candidate_text(text: str) -> str:
    values = _clean_candidate_texts(text)
    return values[0] if values else ""


def _sanitize_context_fragment(text: str, max_chars: int = 140) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip(" .,:;-\u2014")
    if not value:
        return ""
    if len(value) > max_chars:
        value = value[:max_chars].rstrip(" ,;:-")
    return value


def _extract_time_fragment(source_text: str) -> str:
    value = re.sub(r"\s+", " ", str(source_text or "")).strip()
    if not value:
        return ""
    window = _TIME_WINDOW_PATTERN.search(value)
    hint = _TIME_HINT_PATTERN.search(value)
    window_text = _sanitize_context_fragment(window.group(0)) if window else ""
    hint_text = _sanitize_context_fragment(hint.group(0)) if hint else ""
    if hint_text and window_text:
        return f"{hint_text} ({window_text})"
    return hint_text or window_text


def _extract_reason_fragment(source_text: str) -> str:
    value = re.sub(r"\s+", " ", str(source_text or "")).strip()
    if not value:
        return ""

    reason_match = _REASON_CLAUSE_PATTERN.search(value)
    if reason_match:
        return _sanitize_context_fragment(reason_match.group(1))

    need_match = _NEED_CLAUSE_PATTERN.search(value)
    if need_match:
        detail = _sanitize_context_fragment(need_match.group(1))
        if detail:
            return f"the user needs to {detail}"

    # Delivery-related fallback that often carries the practical constraint.
    delivery_match = re.search(r"\bfor a delivery[^.!?\n]{0,180}", value, flags=re.IGNORECASE)
    if delivery_match:
        return _sanitize_context_fragment(delivery_match.group(0))
    return ""


def _contains_contextual_detail(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    lowered = value.lower()
    if _TIME_WINDOW_PATTERN.search(value) or _TIME_HINT_PATTERN.search(value):
        return True
    if re.search(r"\b(?:because|since|due to|car|parce que|reason:)\b", lowered):
        return True
    return False


def _has_time_detail(text: str) -> bool:
    value = str(text or "")
    return bool(_TIME_WINDOW_PATTERN.search(value) or _TIME_HINT_PATTERN.search(value))


def _has_reason_detail(text: str) -> bool:
    return bool(re.search(r"\b(?:because|since|due to|car|parce que|reason:)\b", str(text or "").lower()))


def _build_source_excerpt(source_text: str, max_chars: int = 120) -> str:
    value = re.sub(r"\s+", " ", str(source_text or "")).strip()
    if not value:
        return ""
    value = re.sub(r"^(hello|hi|bonjour|salut)\b[^.!?]{0,80}[.!?]\s*", "", value, flags=re.IGNORECASE)
    value = value.strip()
    if not value:
        return ""
    if len(value) > max_chars:
        value = value[:max_chars].rstrip(" ,;:-") + "..."
    return value


def _enrich_candidate_with_source_context(content: str, source_text: str, category: str) -> str:
    base = str(content or "").strip()
    source = str(source_text or "").strip()
    if not base or not source:
        return base
    if len(base) >= 340:
        return base
    has_time = _has_time_detail(base)
    has_reason = _has_reason_detail(base)
    if has_time and has_reason:
        return base

    time_fragment = _extract_time_fragment(source)
    reason_fragment = _extract_reason_fragment(source)
    additions: list[str] = []
    lowered_base = base.lower()

    if time_fragment and not has_time and time_fragment.lower() not in lowered_base:
        additions.append(time_fragment)
    if reason_fragment and not has_reason and reason_fragment.lower() not in lowered_base:
        additions.append(f"reason: {reason_fragment}")

    # For weak/short claims, add a compact excerpt to avoid contextless memories.
    if not additions and len(base) < 96:
        excerpt = _build_source_excerpt(source, max_chars=90)
        if excerpt:
            # Keep enrichment user-centric and avoid re-introducing first-person text.
            excerpt = _to_third_person(excerpt).strip().rstrip(".")
        if excerpt and not _contains_first_person(excerpt) and excerpt.lower() not in lowered_base:
            additions.append(excerpt)

    if not additions:
        return base

    enriched = f"{base.rstrip(' .;')} ({'; '.join(additions)})."
    if len(enriched) <= 420:
        return enriched

    # Keep only one strongest fragment when close to max length.
    for fragment in additions:
        trial = f"{base.rstrip(' .;')} ({fragment})."
        if len(trial) <= 420:
            return trial
    return base


def _content_quality_score(text: str) -> float:
    value = str(text or "").strip()
    if not value:
        return -1.0
    score = 0.0
    score += min(0.6, len(value) / 420.0)
    if _contains_contextual_detail(value):
        score += 1.4
    if _extract_reason_fragment(value):
        score += 0.6
    if _TIME_HINT_PATTERN.search(value) or _TIME_WINDOW_PATTERN.search(value):
        score += 0.4
    if _looks_vague_capability_memory(value):
        score -= 1.2
    return score


def _select_best_user_message_for_candidate(candidate_content: str, user_messages: list[dict]) -> Optional[dict]:
    if not user_messages:
        return None
    candidate_tokens = _extract_topic_tokens(candidate_content).union(_extract_named_tokens(candidate_content))
    if not candidate_tokens:
        return user_messages[-1]

    best: Optional[dict] = None
    best_score = -1
    for msg in user_messages:
        text = str(msg.get("content") or "")
        msg_tokens = _extract_topic_tokens(text).union(_extract_named_tokens(text))
        score = len(candidate_tokens.intersection(msg_tokens))
        if score > best_score:
            best_score = score
            best = msg
    if best:
        return best
    return user_messages[-1]


def _split_structured_sections(text: str) -> list[str]:
    """
    Split list-like blocks such as:
    "The user ... main pillars: Development: ... Entrepreneurship: ..."
    into atomic segments without truncation.
    """
    value = re.sub(r"\s+", " ", (text or "").strip())
    if not value:
        return []

    raw_matches = list(
        re.finditer(
            r"([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ0-9'’\-/ ]{1,28})\s*:\s",
            value,
        )
    )
    if not raw_matches:
        return [value]

    def _looks_like_section_label(label: str) -> bool:
        clean = re.sub(r"\s+", " ", (label or "").strip())
        if not clean:
            return False
        words = [w for w in clean.split(" ") if w]
        if len(words) == 0 or len(words) > 4:
            return False
        lower = clean.lower()
        if lower.startswith("the user") or lower.startswith("l'utilisateur"):
            return False
        # Skip long contextual phrases ("... for main pillars ...") and keep atomic labels.
        blocked_terms = {"for", "pour", "principaux", "principales", "main", "piliers"}
        if any(w.lower() in blocked_terms for w in words):
            return False
        return True

    matches = [m for m in raw_matches if _looks_like_section_label(str(m.group(1) or ""))]
    if len(matches) < 2:
        return [value]

    prefix = value[: matches[0].start()].strip(" .;:-")
    out: list[str] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(value)
        section = value[start:end].strip(" ;")
        if not section:
            continue
        if prefix:
            section = f"{prefix} - {section}"
        out.append(section)
    return out or [value]


def _chunk_text_by_sentences(text: str, max_chars: int = 320) -> list[str]:
    value = re.sub(r"\s+", " ", (text or "").strip())
    if not value:
        return []
    if len(value) <= max_chars:
        return [value]

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", value) if s.strip()]
    if len(sentences) <= 1:
        # Fallback: split on clause separators when sentence boundaries are absent.
        sentences = [s.strip() for s in re.split(r"(?<=,)\s+|(?<=;)\s+", value) if s.strip()]
        if len(sentences) <= 1:
            sentences = [value]

    out: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            out.append(current.strip())
            current = ""
        if len(sentence) <= max_chars:
            current = sentence
            continue

        # Sentence still too long: split by hard chunks without dropping content.
        start = 0
        while start < len(sentence):
            piece = sentence[start : start + max_chars].strip()
            if piece:
                out.append(piece)
            start += max_chars

    if current:
        out.append(current.strip())
    return out


def _clean_candidate_texts(text: str, max_chars: int = 420, max_segments: int = 3) -> list[str]:
    value = re.sub(r"\s+", " ", (text or "").strip())
    if not value:
        return []
    value = _to_third_person(value)
    if not value:
        return []

    sections: list[str] = []
    for block in re.split(r"\s*(?:\n+|;|•|·|\u2022)\s*", value):
        chunk = block.strip()
        if not chunk:
            continue
        sections.extend(_split_structured_sections(chunk))

    raw_segments: list[str] = []
    for section in sections:
        raw_segments.extend(_chunk_text_by_sentences(section, max_chars=max_chars))

    out: list[str] = []
    seen: set[str] = set()
    for segment in raw_segments:
        cleaned = re.sub(r"\s+", " ", segment).strip()
        if not cleaned:
            continue
        if cleaned[-1] not in ".!?":
            cleaned += "."
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= max_segments:
            break
    return out


def _looks_truncated_memory_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.lower()
    if "..." in value or "…" in value:
        return True
    if lowered.endswith(("-", ":", ";", ",")):
        return True
    # Very short trailing token after a long sentence often indicates cut output.
    parts = value.split()
    if len(value) >= 80 and parts:
        tail = parts[-1].strip(".,;:!?")
        if 1 <= len(tail) <= 2:
            return True
    return False


def _normalize_for_dedupe(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip(" .;")


def _canonicalize_candidate_text(text: str) -> str:
    value = _normalize_for_dedupe(text)
    value = re.sub(r"[^a-z0-9à-ÿ_\-\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _candidate_key(content: str, category: str, level: str) -> str:
    canonical = f"{_normalize_category(category)}|{_normalize_level(level)}|{_canonicalize_candidate_text(content)}"
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _safe_vector_from_text(text: str) -> list[float]:
    if get_embedder_status() != "ready":
        return [0.0] * EMBEDDING_DIM
    try:
        return embed(text)
    except Exception:
        return [0.0] * EMBEDDING_DIM


def _merge_unique_str(existing: Any, additions: list[str], max_items: int = 64) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(existing, list):
        for raw in existing:
            value = str(raw or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(value)
            if len(out) >= max_items:
                return out
    for raw in additions:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= max_items:
            break
    return out


def _candidate_conversation_count(row: dict) -> int:
    conv_ids = row.get("conversation_ids")
    if not isinstance(conv_ids, list):
        return 0
    return len([v for v in conv_ids if str(v or "").strip()])


def _candidate_promotion_score(
    *,
    confidence: float,
    evidence_count: int,
    conversation_count: int,
    level: str,
    last_seen_at: Any,
) -> float:
    safe_confidence = _normalize_confidence(confidence, default=0.8)
    evidence_factor = min(max(int(evidence_count), 0), 4) / 4.0
    conversation_factor = min(max(int(conversation_count), 0), 3) / 3.0
    days_since_seen = max(0.0, (datetime.now(timezone.utc) - _to_dt(last_seen_at)).total_seconds() / 86400.0)
    recency_factor = max(0.0, min(1.0, 1.0 - (days_since_seen / 60.0)))
    level_bonus = 0.04 if _normalize_level(level) == "semantic" else 0.0
    score = (safe_confidence * 0.52) + (evidence_factor * 0.23) + (conversation_factor * 0.17) + (recency_factor * 0.08) + level_bonus
    return max(0.0, min(0.99, score))


def _candidate_is_promotable(
    row: dict,
    *,
    min_score: float,
    min_evidence: int,
    min_conversations: int,
) -> bool:
    status = str(row.get("status") or "").strip().lower()
    if status != "pending":
        return False
    score = float(row.get("promotion_score") or 0.0)
    evidence_count = int(row.get("evidence_count") or 0)
    conversation_count = _candidate_conversation_count(row)
    confidence = _normalize_confidence(row.get("confidence_score"), default=0.8)
    if evidence_count >= max(1, min_evidence) and conversation_count >= max(1, min_conversations) and score >= min_score:
        return True
    # Escape hatch for high-confidence one-shot facts.
    if confidence >= 0.93 and evidence_count >= 1 and score >= (min_score * 0.9):
        return True
    return False


def _extract_topic_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9_\-]{2,}", str(text or "").lower())
    out: set[str] = set()
    for token in tokens:
        if len(token) < 4:
            continue
        if token in _TOPIC_STOPWORDS:
            continue
        out.add(token)
    return out


def _extract_named_tokens(text: str) -> set[str]:
    # Useful for branded entities (HomeBoard, Notion, Stripe, etc.).
    tokens = re.findall(r"\b[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ0-9_\-]{2,}\b", str(text or ""))
    out: set[str] = set()
    for token in tokens:
        lowered = token.lower()
        if lowered in _TOPIC_STOPWORDS:
            continue
        out.add(lowered)
    return out


def _looks_like_project_followup(text: str) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return False
    prefixes = (
        "the application ",
        "this application ",
        "the app ",
        "this app ",
        "the project ",
        "this project ",
        "the product ",
        "it will ",
        "it is ",
        "it should ",
    )
    return any(value.startswith(prefix) for prefix in prefixes)


def _candidate_related_to_cluster(candidate: dict, cluster: dict) -> bool:
    source_message_id = str(candidate.get("source_message_id") or "").strip()
    if source_message_id and source_message_id in cluster["source_message_ids"]:
        return True

    named = _extract_named_tokens(candidate.get("content", ""))
    if named and named.intersection(cluster["named_tokens"]):
        return True

    topic = _extract_topic_tokens(candidate.get("content", ""))
    shared = topic.intersection(cluster["topic_tokens"])
    if len(shared) >= 2:
        return True

    if topic and cluster["topic_tokens"]:
        jaccard = len(shared) / max(1, len(topic.union(cluster["topic_tokens"])))
        if jaccard >= 0.45:
            return True

    candidate_category = _normalize_category(candidate.get("category"))
    if (
        candidate_category == "projects"
        and candidate_category in cluster["categories"]
        and cluster["named_tokens"]
        and _looks_like_project_followup(candidate.get("content", ""))
    ):
        return True

    return False


def _merge_cluster_candidates(members: list[dict], max_chars: int = 420) -> dict:
    if len(members) <= 1:
        return members[0]

    base = members[0]
    base_text = str(base.get("content") or "").strip().rstrip(" .;")
    if not base_text:
        return base

    seen = {_normalize_for_dedupe(base_text)}
    parts = [base_text]

    for member in members[1:]:
        extra = str(member.get("content") or "").strip().rstrip(" .;")
        if not extra:
            continue
        key = _normalize_for_dedupe(extra)
        if not key or key in seen:
            continue
        seen.add(key)
        trial = "; ".join(parts + [extra]) + "."
        if len(trial) > max_chars:
            break
        parts.append(extra)

    if len(parts) <= 1:
        return base

    category_scores: dict[str, float] = {}
    for member in members:
        category = _normalize_category(member.get("category"))
        category_scores[category] = category_scores.get(category, 0.0) + _normalize_confidence(member.get("confidence"), 0.8)
    merged_category = max(category_scores.items(), key=lambda x: x[1])[0] if category_scores else base.get("category")

    merged = dict(base)
    merged["content"] = "; ".join(parts) + "."
    merged["confidence"] = max(_normalize_confidence(m.get("confidence"), 0.8) for m in members)
    merged["category"] = merged_category
    merged["method"] = f"{base.get('method', 'heuristic')}:condensed"
    timestamp_candidates: list[str] = []
    for member in members:
        raw = _normalize_source_timestamp(member.get("source_message_timestamp"))
        if raw:
            timestamp_candidates.append(raw)
    if timestamp_candidates:
        merged["source_message_timestamp"] = min(timestamp_candidates, key=_to_dt)
    return merged


def _consolidate_candidates(candidates: list[dict], max_chars: int = 420, max_cluster_size: int = 4) -> list[dict]:
    if len(candidates) <= 1:
        return candidates

    grouped: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    key_order: list[tuple[str, str]] = []
    for idx, candidate in enumerate(candidates):
        key = (
            str(candidate.get("conversation_id") or ""),
            _normalize_level(candidate.get("level")),
        )
        if key not in grouped:
            grouped[key] = []
            key_order.append(key)
        grouped[key].append((idx, candidate))

    out_with_index: list[tuple[int, dict]] = []
    for key in key_order:
        clusters: list[dict] = []
        for idx, candidate in grouped.get(key, []):
            placed = False
            for cluster in clusters:
                if len(cluster["members"]) >= max_cluster_size:
                    continue
                if _candidate_related_to_cluster(candidate, cluster):
                    cluster["members"].append(candidate)
                    cluster["topic_tokens"].update(_extract_topic_tokens(candidate.get("content", "")))
                    cluster["named_tokens"].update(_extract_named_tokens(candidate.get("content", "")))
                    cluster["categories"].add(_normalize_category(candidate.get("category")))
                    source_message_id = str(candidate.get("source_message_id") or "").strip()
                    if source_message_id:
                        cluster["source_message_ids"].add(source_message_id)
                    placed = True
                    break
            if not placed:
                source_message_id = str(candidate.get("source_message_id") or "").strip()
                clusters.append(
                    {
                        "first_index": idx,
                        "members": [candidate],
                        "topic_tokens": _extract_topic_tokens(candidate.get("content", "")),
                        "named_tokens": _extract_named_tokens(candidate.get("content", "")),
                        "categories": {_normalize_category(candidate.get("category"))},
                        "source_message_ids": {source_message_id} if source_message_id else set(),
                    }
                )

        for cluster in clusters:
            merged = _merge_cluster_candidates(cluster["members"], max_chars=max_chars)
            out_with_index.append((cluster["first_index"], merged))

    out_with_index.sort(key=lambda item: item[0])
    return [item[1] for item in out_with_index]


def _conversation_signal_score(messages: list[dict]) -> int:
    score = 0
    for msg in messages:
        if (msg.get("role") or "").lower() != "user":
            continue
        text = (msg.get("content") or "").lower()
        if len(text) < 24:
            continue
        if re.search(r"\b(i|i'm|my|me|je|j'|moi|mon|ma|mes)\b", text):
            score += 2
        if re.search(r"\b(prefer|like|love|hate|always|never|prefere|aime|deteste|toujours|jamais)\b", text):
            score += 2
        if re.search(r"\b(work on|building|project|stack|use|travaille sur|projet|utilise|developpe)\b", text):
            score += 1
    return score


def _extract_snippet(text: str, marker: str) -> str:
    lower = text.lower()
    idx = lower.find(marker)
    if idx == -1:
        return ""
    start = idx + len(marker)
    snippet = text[start:].strip(" :,-")
    snippet = re.sub(r"\s+", " ", snippet)
    if len(snippet) > 140:
        snippet = snippet[:140].rstrip() + "..."
    return snippet


def _heuristic_candidates_for_conversation(
    context: dict,
    max_candidates_per_conversation: int,
    min_confidence: float,
) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    messages = context.get("messages", [])

    def _push(
        content: str,
        category: str,
        level: str,
        confidence: float,
        source_message_id: str,
        source_message_timestamp: str,
        source_message_content: str,
    ):
        if len(out) >= max_candidates_per_conversation:
            return
        cleaned_variants = _clean_candidate_texts(content, max_chars=420, max_segments=2)
        for cleaned in cleaned_variants:
            if len(out) >= max_candidates_per_conversation:
                break
            enriched = _enrich_candidate_with_source_context(cleaned, source_message_content, category)
            if not enriched or len(enriched) < 20 or len(enriched) > 520:
                continue
            if _looks_truncated_memory_text(enriched):
                continue
            if _looks_generic_non_memory(enriched):
                continue
            key = enriched.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "content": enriched,
                    "category": _normalize_category(category),
                    "level": _normalize_level(level),
                    "confidence": _normalize_confidence(confidence),
                    "source_message_id": source_message_id,
                    "source_message_timestamp": source_message_timestamp,
                    "source_excerpt": _build_source_excerpt(source_message_content),
                    "conversation_id": context.get("conversation_id"),
                    "conversation_title": context.get("title", ""),
                    "method": "heuristic",
                }
            )

    for msg in messages:
        if len(out) >= max_candidates_per_conversation:
            break
        if (msg.get("role") or "").lower() != "user":
            continue
        text = (msg.get("content") or "").strip()
        if len(text) < 24:
            continue
        lower = text.lower()
        message_id = str(msg.get("id") or "")
        message_timestamp = _normalize_source_timestamp(msg.get("timestamp"))

        if "my name is " in lower:
            name = _extract_snippet(text, "my name is ")
            if name:
                _push(
                    f"The user's name is {name}",
                    "identity",
                    "semantic",
                    0.92,
                    message_id,
                    message_timestamp,
                    text,
                )

        if "je m'appelle " in lower:
            name = _extract_snippet(text, "je m'appelle ")
            if name:
                _push(
                    f"Le nom de l'utilisateur est {name}",
                    "identity",
                    "semantic",
                    0.92,
                    message_id,
                    message_timestamp,
                    text,
                )

        preference_markers = [
            "i prefer ",
            "i like ",
            "i love ",
            "i hate ",
            "je prefere ",
            "j'aime ",
            "je deteste ",
        ]
        for marker in preference_markers:
            if marker in lower:
                snippet = _extract_snippet(text, marker)
                if snippet:
                    _push(
                        f"The user prefers {snippet}",
                        "preferences",
                        "semantic",
                        0.84,
                        message_id,
                        message_timestamp,
                        text,
                    )
                break

        project_markers = [
            "i'm working on ",
            "i am working on ",
            "i'm building ",
            "i am building ",
            "je travaille sur ",
            "je developpe ",
            "mon projet ",
        ]
        for marker in project_markers:
            if marker in lower:
                snippet = _extract_snippet(text, marker)
                if snippet:
                    _push(
                        f"The user is working on {snippet}",
                        "projects",
                        "semantic",
                        0.82,
                        message_id,
                        message_timestamp,
                        text,
                    )
                break

        stack_markers = [
            "i use ",
            "my stack",
            "j'utilise ",
            "tech stack",
        ]
        for marker in stack_markers:
            if marker in lower:
                snippet = _extract_snippet(text, marker)
                if snippet:
                    _push(
                        f"The user uses {snippet}",
                        "skills",
                        "semantic",
                        0.8,
                        message_id,
                        message_timestamp,
                        text,
                    )
                break

    return [c for c in out if c["confidence"] >= min_confidence][:max_candidates_per_conversation]


def _build_llm_prompt(context: dict, max_candidates_per_conversation: int, min_confidence: float) -> str:
    messages = []
    for msg in context.get("messages", []):
        messages.append(
            {
                "id": str(msg.get("id") or ""),
                "role": str(msg.get("role") or ""),
                "content": str(msg.get("content") or "")[:480],
                "timestamp": str(msg.get("timestamp") or ""),
            }
        )

    payload = {
        "conversation_id": context.get("conversation_id"),
        "title": context.get("title"),
        "source_llm": context.get("source_llm"),
        "messages": messages,
    }
    return (
        "You extract durable user memories from conversation transcripts.\n"
        "Return STRICT JSON only with this schema:\n"
        "{\"memories\":[{\"content\":\"...\",\"category\":\"identity|preferences|skills|relationships|projects|history|working\","
        "\"level\":\"semantic|episodic|working\",\"confidence\":0.0,\"source_message_id\":\"...\"}]}\n"
        "Rules:\n"
        f"- Return at most {max_candidates_per_conversation} memories.\n"
        f"- Keep only memories with confidence >= {min_confidence:.2f}.\n"
        "- Keep durable, user-centric facts and preferences. Avoid transient tasks and one-off requests.\n"
        "- Write in third-person declarative style (never first-person).\n"
        "- Source grounding: source_message_id must reference a USER message from this transcript.\n"
        "- Each memory must be 20-480 chars.\n"
        "- Keep key context when available (time window, concrete reason, constraints), not generic paraphrases.\n"
        "- Reject vague capability claims (e.g., 'the user can ... if needed') unless concretely evidenced and durable.\n"
        "- Never truncate with ellipsis ('...' or '…'). If needed, shorten while keeping a complete sentence.\n"
        "- Merge tightly related facts from the same topic into one memory instead of splitting excessively.\n"
        "- Do not duplicate semantically equivalent memories.\n"
        f"Conversation data: {json.dumps(payload, ensure_ascii=False)}"
    )


def _resolve_runtime(
    provider: str = "auto",
    model: Optional[str] = None,
    api_base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    cfg = load_config(force_reload=True)
    analysis_cfg = cfg.get("conversation_analysis", {}) if isinstance(cfg.get("conversation_analysis"), dict) else {}
    insights_cfg = cfg.get("insights", {}) if isinstance(cfg.get("insights"), dict) else {}

    resolved_provider = _normalize_provider(provider)
    if resolved_provider in {"", "auto"}:
        analysis_provider = _normalize_provider(analysis_cfg.get("provider", "auto"))
        if analysis_provider not in {"", "auto"}:
            resolved_provider = analysis_provider
        else:
            resolved_provider = _normalize_provider(insights_cfg.get("provider", "openai"))

    resolved_model = (
        (model or "").strip()
        or str(analysis_cfg.get("model") or "").strip()
        or str(insights_cfg.get("model") or "").strip()
    )
    resolved_api_base_url = (
        (api_base_url or "").strip()
        or str(analysis_cfg.get("api_base_url") or "").strip()
        or str(insights_cfg.get("api_base_url") or "").strip()
    )
    resolved_api_key = (
        (api_key or "").strip()
        or str(analysis_cfg.get("api_key") or "").strip()
        or str(insights_cfg.get("api_key") or "").strip()
    )

    if resolved_provider == "openai":
        if not resolved_model:
            resolved_model = "gpt-4o-mini"
        if not resolved_api_base_url:
            resolved_api_base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not resolved_api_key:
            resolved_api_key = os.environ.get("OPENAI_API_KEY", "")
    elif resolved_provider == "anthropic":
        if not resolved_model:
            resolved_model = "claude-3-5-haiku-latest"
        if not resolved_api_base_url:
            resolved_api_base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
        if not resolved_api_key:
            resolved_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    elif resolved_provider == "ollama":
        if not resolved_model:
            resolved_model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
        if not resolved_api_base_url:
            resolved_api_base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        if not resolved_api_key:
            resolved_api_key = os.environ.get("OLLAMA_API_KEY", "")
    else:
        # Unknown provider falls back to heuristic mode.
        resolved_provider = "heuristic"

    return {
        "provider": resolved_provider,
        "model": resolved_model,
        "api_base_url": resolved_api_base_url.rstrip("/") if resolved_api_base_url else "",
        "api_key": resolved_api_key,
    }


def _runtime_can_use_llm(runtime: dict) -> bool:
    provider = runtime.get("provider")
    if provider == "openai":
        return bool(runtime.get("model")) and bool(runtime.get("api_key"))
    if provider == "anthropic":
        return bool(runtime.get("model")) and bool(runtime.get("api_key"))
    if provider == "ollama":
        return bool(runtime.get("model")) and bool(runtime.get("api_base_url"))
    return False


def _runtime_unconfigured_reason(runtime: dict) -> str:
    provider = str(runtime.get("provider") or "").strip().lower()
    model = str(runtime.get("model") or "").strip()
    base_url = str(runtime.get("api_base_url") or "").strip()
    api_key = str(runtime.get("api_key") or "").strip()

    if provider not in SUPPORTED_LLM_PROVIDERS:
        return "Conversation analysis requires an LLM provider (OpenAI, Anthropic, or Ollama)."
    if provider in {"openai", "anthropic"}:
        if not model and not api_key:
            return f"Configure {provider} model and API key in Settings > Insights AI."
        if not model:
            return f"Configure a {provider} model in Settings > Insights AI."
        if not api_key:
            return f"Configure a {provider} API key in Settings > Insights AI."
    if provider == "ollama":
        if not model and not base_url:
            return "Configure Ollama model and base URL in Settings > Insights AI."
        if not model:
            return "Configure an Ollama model in Settings > Insights AI."
        if not base_url:
            return "Configure the Ollama base URL in Settings > Insights AI (example: http://127.0.0.1:11434)."
    return "LLM configuration is incomplete for conversation analysis."


def _resolve_require_llm_configured(explicit: Optional[bool] = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    try:
        cfg = load_config(force_reload=True)
        analysis_cfg = cfg.get("conversation_analysis", {}) if isinstance(cfg.get("conversation_analysis"), dict) else {}
        return bool(analysis_cfg.get("require_llm_configured", True))
    except Exception:
        return True


def _extract_ollama_model_names(payload: Any) -> set[str]:
    names: set[str] = set()
    if not isinstance(payload, dict):
        return names
    models = payload.get("models")
    if not isinstance(models, list):
        return names
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if name:
            names.add(name)
    return names


def _ollama_model_available(requested_model: str, available: set[str]) -> bool:
    if not requested_model:
        return False
    requested = requested_model.strip().lower()
    if not requested:
        return False
    if requested in available:
        return True
    requested_base = requested.split(":", 1)[0]
    if not requested_base:
        return False
    for name in available:
        base = str(name).split(":", 1)[0]
        if base == requested_base:
            return True
    return False


async def _preflight_runtime(runtime: dict) -> tuple[bool, Optional[str]]:
    """
    Fast provider reachability check to avoid long blocked runs when local endpoints are down.
    """
    provider = str(runtime.get("provider") or "")
    if provider != "ollama":
        return True, None
    base = str(runtime.get("api_base_url") or "").rstrip("/")
    if not base:
        return False, "Ollama base URL is empty."
    model = str(runtime.get("model") or "").strip()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{base}/api/tags")
            if res.status_code >= 400:
                detail = ""
                try:
                    payload = res.json()
                    if isinstance(payload, dict):
                        detail = str(payload.get("error") or payload.get("message") or "").strip()
                except Exception:
                    detail = (res.text or "").strip()
                suffix = f": {detail[:180]}" if detail else ""
                return False, f"Ollama preflight failed ({res.status_code}){suffix}"
            available = _extract_ollama_model_names(res.json())
            if model and not available:
                return (
                    False,
                    f"Ollama has no local models installed. "
                    f"Run 'ollama pull {model}' (or any model) first.",
                )
            if model and available and not _ollama_model_available(model, available):
                preview = ", ".join(sorted(available)[:6])
                preview_suffix = f" Available: {preview}" if preview else ""
                return (
                    False,
                    f"Ollama model '{model}' not found locally.{preview_suffix} "
                    f"Run 'ollama pull {model}' or pick an installed model.",
                )
        return True, None
    except Exception as e:
        return False, f"Ollama preflight failed: {e}"


async def get_analysis_llm_gate_status(
    *,
    provider: str = "auto",
    model: Optional[str] = None,
    api_base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    require_llm_configured: Optional[bool] = None,
    preflight: bool = True,
) -> dict[str, Any]:
    required = _resolve_require_llm_configured(require_llm_configured)
    runtime = _resolve_runtime(
        provider=provider,
        model=model,
        api_base_url=api_base_url,
        api_key=api_key,
    )
    configured = bool(runtime.get("provider") in SUPPORTED_LLM_PROVIDERS and _runtime_can_use_llm(runtime))
    llm_enabled = False
    reason: Optional[str] = None
    if configured:
        if preflight:
            ok, preflight_reason = await _preflight_runtime(runtime)
            if ok:
                llm_enabled = True
            else:
                reason = preflight_reason or "LLM runtime preflight failed."
        else:
            llm_enabled = True
    else:
        reason = _runtime_unconfigured_reason(runtime)

    analysis_allowed = bool(not required or llm_enabled)
    if analysis_allowed and not llm_enabled and not configured:
        reason = reason or _runtime_unconfigured_reason(runtime)
    if not analysis_allowed and not reason:
        reason = _runtime_unconfigured_reason(runtime)

    return {
        "required": required,
        "analysis_allowed": analysis_allowed,
        "llm_enabled": llm_enabled,
        "configured": configured,
        "reason": reason,
        "runtime": runtime,
        "runtime_public": {
            "provider": str(runtime.get("provider") or ""),
            "model": str(runtime.get("model") or ""),
            "api_base_url": str(runtime.get("api_base_url") or ""),
        },
    }


async def _call_openai(prompt: str, runtime: dict) -> str:
    headers = {"Content-Type": "application/json"}
    if runtime.get("api_key"):
        headers["Authorization"] = f"Bearer {runtime.get('api_key')}"
    body = {
        "model": runtime.get("model"),
        "temperature": 0.2,
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(f"{runtime.get('api_base_url')}/chat/completions", headers=headers, json=body)
        if res.status_code >= 400:
            raise RuntimeError(f"OpenAI request failed ({res.status_code})")
        data = res.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


async def _call_anthropic(prompt: str, runtime: dict) -> str:
    headers = {
        "x-api-key": runtime.get("api_key") or "",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": runtime.get("model"),
        "max_tokens": 700,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(f"{runtime.get('api_base_url')}/messages", headers=headers, json=body)
        if res.status_code >= 400:
            raise RuntimeError(f"Anthropic request failed ({res.status_code})")
        data = res.json()
    content = data.get("content", [])
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


def _extract_openai_compatible_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "")


def _extract_ollama_chat_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return ""


async def _call_ollama(prompt: str, runtime: dict) -> str:
    headers = {"Content-Type": "application/json"}
    if runtime.get("api_key"):
        headers["Authorization"] = f"Bearer {runtime.get('api_key')}"
    generate_body = {
        "model": runtime.get("model"),
        "prompt": f"Return valid JSON only.\n\n{prompt}",
        "stream": False,
        "options": {"temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        base_url = str(runtime.get("api_base_url") or "").rstrip("/")
        res = await client.post(f"{base_url}/api/generate", headers=headers, json=generate_body)
        if res.status_code == 404:
            # Fallback #1: Ollama chat endpoint (available on some installs/proxies).
            chat_body = {
                "model": runtime.get("model"),
                "messages": [
                    {"role": "system", "content": "Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.2},
            }
            res = await client.post(f"{base_url}/api/chat", headers=headers, json=chat_body)
            if res.status_code < 400:
                payload = res.json()
                text = _extract_ollama_chat_text(payload)
                if text:
                    return text
        if res.status_code == 404:
            # Fallback #2: OpenAI-compatible mode exposed by some Ollama gateways.
            compat_body = {
                "model": runtime.get("model"),
                "temperature": 0.2,
                "max_tokens": 700,
                "messages": [
                    {"role": "system", "content": "Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
            }
            res = await client.post(f"{base_url}/v1/chat/completions", headers=headers, json=compat_body)
            if res.status_code < 400:
                payload = res.json()
                text = _extract_openai_compatible_text(payload)
                if text:
                    return text
        if res.status_code >= 400:
            detail = ""
            try:
                payload = res.json()
                if isinstance(payload, dict):
                    detail = str(payload.get("error") or payload.get("message") or "").strip()
            except Exception:
                detail = (res.text or "").strip()
            suffix = f": {detail[:220]}" if detail else ""
            raise RuntimeError(f"Ollama request failed ({res.status_code}){suffix}")
        data = res.json()
    return str(data.get("response") or "")


def _normalize_llm_candidates(
    parsed: dict,
    context: dict,
    min_confidence: float,
    max_candidates_per_conversation: int,
) -> list[dict]:
    raw_memories = parsed.get("memories")
    if not isinstance(raw_memories, list):
        return []

    out: list[dict] = []
    seen: set[str] = set()
    message_by_id: dict[str, dict] = {}
    user_messages: list[dict] = []
    for msg in context.get("messages", []):
        msg_id = str(msg.get("id") or "")
        if msg_id:
            message_by_id[msg_id] = msg
        if str(msg.get("role") or "").strip().lower() == "user":
            user_messages.append(msg)

    for item in raw_memories:
        if len(out) >= max_candidates_per_conversation:
            break
        if not isinstance(item, dict):
            continue

        cleaned_variants = _clean_candidate_texts(str(item.get("content") or ""), max_chars=420, max_segments=2)
        if not cleaned_variants:
            continue

        confidence = _normalize_confidence(item.get("confidence"), default=0.82)
        if confidence < min_confidence:
            continue

        source_message_id_hint = str(item.get("source_message_id") or "")
        hinted_message = message_by_id.get(source_message_id_hint)
        if hinted_message and str(hinted_message.get("role") or "").strip().lower() != "user":
            hinted_message = None
            source_message_id_hint = ""
        if not hinted_message:
            hinted_message = _select_best_user_message_for_candidate(
                str(item.get("content") or ""),
                user_messages,
            )
            source_message_id_hint = str((hinted_message or {}).get("id") or "")

        for cleaned in cleaned_variants:
            if len(out) >= max_candidates_per_conversation:
                break
            if _looks_generic_non_memory(cleaned):
                continue
            source_message = hinted_message or _select_best_user_message_for_candidate(cleaned, user_messages)
            source_message_id = str((source_message or {}).get("id") or source_message_id_hint or "")
            source_message_timestamp = _normalize_source_timestamp((source_message or {}).get("timestamp"))
            source_message_content = str((source_message or {}).get("content") or "")

            enriched = _enrich_candidate_with_source_context(
                cleaned,
                source_message_content,
                _normalize_category(item.get("category")),
            )
            if len(enriched) < 20 or len(enriched) > 520:
                continue
            if _looks_truncated_memory_text(enriched):
                continue
            if _contains_first_person(enriched):
                continue
            # Guardrail: memories must be explicitly user-centric.
            # This blocks generic knowledge statements ("X is a protocol...").
            if not _contains_user_anchor(enriched):
                continue
            if _looks_generic_non_memory(enriched):
                continue
            key = enriched.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "content": enriched,
                    "category": _normalize_category(item.get("category")),
                    "level": _normalize_level(item.get("level")),
                    "confidence": confidence,
                    "source_message_id": source_message_id,
                    "source_message_timestamp": source_message_timestamp,
                    "source_excerpt": _build_source_excerpt(source_message_content),
                    "conversation_id": context.get("conversation_id"),
                    "conversation_title": context.get("title", ""),
                    "method": "llm",
                }
            )
    return out


async def _extract_candidates_with_llm(
    context: dict,
    runtime: dict,
    max_candidates_per_conversation: int,
    min_confidence: float,
) -> list[dict]:
    provider = runtime.get("provider")
    prompt = _build_llm_prompt(
        context=context,
        max_candidates_per_conversation=max_candidates_per_conversation,
        min_confidence=min_confidence,
    )
    if provider == "openai":
        text = await _call_openai(prompt, runtime)
    elif provider == "anthropic":
        text = await _call_anthropic(prompt, runtime)
    elif provider == "ollama":
        text = await _call_ollama(prompt, runtime)
    else:
        return []

    parsed = _extract_json_obj(text)
    if not parsed:
        return []
    return _normalize_llm_candidates(
        parsed=parsed,
        context=context,
        min_confidence=min_confidence,
        max_candidates_per_conversation=max_candidates_per_conversation,
    )


def _load_conversation_contexts(
    max_conversations: int,
    max_messages_per_conversation: int,
    include_assistant_messages: bool,
    force_reanalyze: bool,
    conversation_ids: Optional[list[str]] = None,
    progress_cb: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict:
    db = get_db()
    try:
        conv_tbl = db.open_table("conversations")
        msg_tbl = db.open_table("messages")
    except Exception:
        return {
            "contexts": [],
            "conversations_scanned": 0,
            "skipped_already_analyzed": 0,
            "skipped_by_index": 0,
            "skipped_by_tags": 0,
            "index_size": 0,
        }
    index_map = {} if force_reanalyze else _load_analysis_index_map()
    # Wider scan window prevents recency starvation on large imports where only
    # a small recent slice is repeatedly analyzed.
    scan_limit = max(240, min(12000, max_conversations * 80))
    conv_rows = conv_tbl.search().where("status != 'deleted'").limit(scan_limit).to_list()
    conv_rows.sort(key=lambda x: _to_dt(x.get("started_at")), reverse=True)

    requested_ids: list[str] = []
    if conversation_ids:
        seen_requested = set()
        for raw in conversation_ids:
            value = str(raw or "").strip()
            if not value or value in seen_requested:
                continue
            seen_requested.add(value)
            requested_ids.append(value)
    if requested_ids:
        requested_set = set(requested_ids)
        conv_rows = [row for row in conv_rows if str(row.get("id") or "") in requested_set]

    contexts: list[dict] = []
    skipped_already = 0
    skipped_by_index = 0
    skipped_by_tags = 0
    candidates: list[dict] = []
    # Probe deeper than just a tiny recent prefix so selection can reach
    # candidate-rich conversations beyond the first page.
    probe_limit = max(180, min(len(conv_rows), max_conversations * 24))
    conv_total = len(conv_rows)
    scan_emit_every = max(1, min(120, conv_total // 40 if conv_total > 0 else 1))
    for scan_idx, conv in enumerate(conv_rows, start=1):
        try:
            conv_id = str(conv.get("id") or "")
            if not conv_id:
                continue
            message_count = max(0, int(conv.get("message_count") or 0))
            if message_count <= 0:
                continue
            if not force_reanalyze:
                index_row = index_map.get(conv_id)
                if index_row and _index_row_is_fresh(index_row, conv, message_count):
                    skipped_already += 1
                    skipped_by_index += 1
                    continue

            normalized_tags = _normalize_tags(conv.get("tags"))
            lowered_tags = {tag.lower() for tag in normalized_tags}
            if not force_reanalyze and _ANALYSIS_TAG in lowered_tags:
                analyzed_msgcount = _read_analyzed_msgcount(normalized_tags)
                analyzed_result = _read_analysis_result(normalized_tags)
                if (
                    analyzed_result in {"has_memory", "none"}
                    and (analyzed_msgcount is None or analyzed_msgcount >= message_count)
                ):
                    skipped_already += 1
                    skipped_by_tags += 1
                    continue
            candidates.append(
                {
                    "conv": conv,
                    "normalized_tags": normalized_tags,
                    "message_count": message_count,
                }
            )
            if len(candidates) >= probe_limit:
                break
        finally:
            if progress_cb and (scan_idx % scan_emit_every == 0 or scan_idx >= conv_total):
                try:
                    progress_cb(
                        {
                            "stage": "scan",
                            "scanned": scan_idx,
                            "scan_total": conv_total,
                            "candidates": len(candidates),
                            "probe_limit": probe_limit,
                        }
                    )
                except Exception:
                    pass

    candidate_total = len(candidates)
    hydrate_emit_every = max(1, min(80, candidate_total // 30 if candidate_total > 0 else 1))
    for hydrate_idx, item in enumerate(candidates, start=1):
        try:
            conv = item["conv"]
            normalized_tags = item["normalized_tags"]
            message_count = item["message_count"]
            conv_id = str(conv.get("id") or "")
            escaped = _escape_sql(conv_id)
            rows = msg_tbl.search().where(f"conversation_id = '{escaped}'").limit(max_messages_per_conversation * 4).to_list()
            if not rows:
                continue
            rows.sort(key=lambda x: _to_dt(x.get("timestamp")))

            messages = []
            for msg in rows:
                role = str(msg.get("role") or "user").strip().lower()
                if role not in {"user", "assistant"}:
                    continue
                if not include_assistant_messages and role != "user":
                    continue
                content = str(msg.get("content") or "").strip()
                if len(content) < 12:
                    continue
                content = re.sub(r"\s+", " ", content)
                if len(content) > 720:
                    content = content[:720].rstrip()
                messages.append(
                    {
                        "id": str(msg.get("id") or ""),
                        "role": role,
                        "content": content,
                        "timestamp": str(msg.get("timestamp") or ""),
                    }
                )
            if not messages:
                continue

            score = _conversation_signal_score(messages)
            if score <= 0:
                continue

            contexts.append(
                {
                    "conversation_id": conv_id,
                    "title": str(conv.get("title") or "Untitled"),
                    "source_llm": str(conv.get("source_llm") or "unknown"),
                    "started_at": _to_dt(conv.get("started_at")).isoformat(),
                    "messages": messages[-max_messages_per_conversation:],
                    "signal_score": score,
                    "conversation_message_count": max(message_count, len(messages)),
                    "conversation_hash": str(conv.get("raw_file_hash") or ""),
                    "conversation_tags": normalized_tags,
                }
            )
        finally:
            if progress_cb and (hydrate_idx % hydrate_emit_every == 0 or hydrate_idx >= candidate_total):
                try:
                    progress_cb(
                        {
                            "stage": "hydrate",
                            "processed": hydrate_idx,
                            "total": candidate_total,
                            "selected": len(contexts),
                        }
                    )
                except Exception:
                    pass

    contexts.sort(
        key=lambda x: (
            int(x.get("signal_score") or 0),
            _to_dt(x.get("started_at")).timestamp(),
        ),
        reverse=True,
    )
    contexts = contexts[:max_conversations]
    return {
        "contexts": contexts,
        "conversations_scanned": len(conv_rows),
        "skipped_already_analyzed": skipped_already,
        "skipped_by_index": skipped_by_index,
        "skipped_by_tags": skipped_by_tags,
        "index_size": len(index_map),
    }


async def _link_created_memories(created_by_conversation: dict[str, list[str]]) -> int:
    if not created_by_conversation:
        return 0

    async def _write_op():
        db = get_db()
        if "conversations" not in db.table_names():
            return 0
        conv_tbl = db.open_table("conversations")
        linked = 0
        for conv_id, memory_ids in created_by_conversation.items():
            if not memory_ids:
                continue
            escaped = _escape_sql(conv_id)
            rows = conv_tbl.search().where(f"id = '{escaped}'").limit(1).to_list()
            if not rows:
                continue
            existing = rows[0]
            current_ids = [str(v) for v in (existing.get("memory_ids") or []) if v]
            merged_ids = list(dict.fromkeys(current_ids + [str(m) for m in memory_ids if m]))
            conv_tbl.update(where=f"id = '{escaped}'", values={"memory_ids": merged_ids})
            linked += 1
        return linked

    return await enqueue_write(_write_op)


async def _mark_conversations_analyzed(
    contexts: list[dict],
    provider: str,
    result_by_conversation: Optional[dict[str, str]] = None,
) -> int:
    if not contexts:
        return 0

    by_id: dict[str, dict] = {}
    for ctx in contexts:
        conv_id = str(ctx.get("conversation_id") or "")
        if conv_id:
            by_id[conv_id] = ctx
    if not by_id:
        return 0

    async def _write_op():
        db = get_db()
        if "conversations" not in db.table_names():
            return 0
        conv_tbl = db.open_table("conversations")
        updated = 0
        for conv_id, ctx in by_id.items():
            escaped = _escape_sql(conv_id)
            rows = conv_tbl.search().where(f"id = '{escaped}'").limit(1).to_list()
            if not rows:
                continue
            current = rows[0]
            tags = _build_analysis_tags(
                existing_tags=current.get("tags") or ctx.get("conversation_tags") or [],
                provider=provider,
                message_count=int(ctx.get("conversation_message_count") or 0),
                result=(result_by_conversation or {}).get(conv_id),
            )
            conv_tbl.update(where=f"id = '{escaped}'", values={"tags": tags})
            updated += 1
        return updated

    return await enqueue_write(_write_op)


async def _upsert_analysis_index(
    contexts: list[dict],
    provider: str,
    result_by_conversation: dict[str, str],
    outcomes_by_conversation: dict[str, dict[str, int]],
) -> int:
    if not contexts:
        return 0

    now = datetime.now(timezone.utc)
    by_id: dict[str, dict] = {}
    for ctx in contexts:
        conv_id = str(ctx.get("conversation_id") or "").strip()
        if conv_id:
            by_id[conv_id] = ctx
    if not by_id:
        return 0

    async def _write_op():
        db = get_db()
        if _ANALYSIS_INDEX_TABLE not in db.table_names():
            return 0
        idx_tbl = db.open_table(_ANALYSIS_INDEX_TABLE)
        updated = 0
        for conv_id, ctx in by_id.items():
            escaped = _escape_sql(conv_id)
            rows = idx_tbl.search().where(f"id = '{escaped}'").limit(1).to_list()
            outcome = outcomes_by_conversation.get(conv_id, {})
            messages = ctx.get("messages") if isinstance(ctx.get("messages"), list) else []
            latest_message_at = _to_dt(messages[-1].get("timestamp")) if messages else None
            values = {
                "conversation_id": conv_id,
                "message_count": int(ctx.get("conversation_message_count") or 0),
                "conversation_hash": str(ctx.get("conversation_hash") or ""),
                "latest_message_at": latest_message_at,
                "last_result": str(result_by_conversation.get(conv_id, "none")),
                "provider": str(provider or "heuristic"),
                "signal_score": int(ctx.get("signal_score") or 0),
                "candidates_count": int(outcome.get("candidates", 0) or 0),
                "created_count": int(outcome.get("created", 0) or 0),
                "error_count": int(outcome.get("errors", 0) or 0),
                "duration_ms": int(outcome.get("extract_ms", 0) or 0),
                "last_analyzed_at": now,
            }
            if rows:
                idx_tbl.update(where=f"id = '{escaped}'", values=values)
            else:
                idx_tbl.add(
                    [
                        {
                            "id": conv_id,
                            **values,
                        }
                    ]
                )
            updated += 1
        return updated

    return await enqueue_write(_write_op)


async def _upsert_conversation_candidates(
    candidates: list[dict],
    *,
    source_provider: str,
    source_llm: str,
    semantic_dedupe_threshold: float,
) -> dict:
    if not candidates:
        return {
            "inserted": 0,
            "updated": 0,
            "semantic_merged": 0,
            "generic_filtered": 0,
            "touched": [],
        }

    safe_semantic_dedupe_threshold = max(0.84, min(float(semantic_dedupe_threshold or 0.92), 0.99))

    async def _write_op():
        db = get_db()
        if _ANALYSIS_CANDIDATES_TABLE not in db.table_names():
            return {
                "inserted": 0,
                "updated": 0,
                "semantic_merged": 0,
                "generic_filtered": 0,
                "touched": [],
            }

        tbl = db.open_table(_ANALYSIS_CANDIDATES_TABLE)
        now = datetime.now(timezone.utc)
        inserted = 0
        updated = 0
        semantic_merged = 0
        generic_filtered = 0
        touched_ids: set[str] = set()
        touched_rows: list[dict] = []

        for candidate in candidates:
            content = str(candidate.get("content") or "").strip()
            if not content:
                continue
            if _looks_generic_non_memory(content):
                generic_filtered += 1
                continue
            category = _normalize_category(candidate.get("category"))
            level = _normalize_level(candidate.get("level"))
            confidence = _normalize_confidence(candidate.get("confidence"), default=0.8)
            conv_id = str(candidate.get("conversation_id") or "").strip()
            source_message_id = str(candidate.get("source_message_id") or "").strip()
            method = str(candidate.get("method") or "heuristic").strip() or "heuristic"
            normalized_content = _canonicalize_candidate_text(content)
            canonical_key = _candidate_key(content, category, level)
            candidate_vector = _safe_vector_from_text(content)
            timestamp_raw = _normalize_source_timestamp(candidate.get("source_message_timestamp"))
            first_seen_at = _to_dt(timestamp_raw) if timestamp_raw else now
            last_seen_at = _to_dt(timestamp_raw) if timestamp_raw else now

            existing = tbl.search().where(f"canonical_key = '{_escape_sql(canonical_key)}'").limit(1).to_list()
            match_row = existing[0] if existing else None

            if not match_row and any(abs(v) > 1e-9 for v in candidate_vector):
                try:
                    near = tbl.search(candidate_vector).where("status != 'rejected'").limit(12).to_list()
                except Exception:
                    near = []
                for item in near:
                    score = 1.0 - float(item.get("_distance", 1.0) or 1.0)
                    if score < safe_semantic_dedupe_threshold:
                        continue
                    item_category = _normalize_category(item.get("category"))
                    item_level = _normalize_level(item.get("level"))
                    if item_level != level:
                        continue
                    if item_category != category and score < 0.96:
                        continue
                    match_row = item
                    semantic_merged += 1
                    break

            if match_row:
                candidate_id = str(match_row.get("id") or "")
                if not candidate_id:
                    continue
                evidence_count = max(1, int(match_row.get("evidence_count") or 0)) + 1
                merged_conversation_ids = _merge_unique_str(match_row.get("conversation_ids"), [conv_id], max_items=96)
                merged_source_ids = _merge_unique_str(match_row.get("source_message_ids"), [source_message_id], max_items=160)
                merged_methods = _merge_unique_str(match_row.get("methods"), [method], max_items=16)
                merged_confidence = max(confidence, _normalize_confidence(match_row.get("confidence_score"), default=0.8))
                merged_last_seen = max(_to_dt(match_row.get("last_seen_at")), last_seen_at)
                merged_first_seen = min(_to_dt(match_row.get("first_seen_at")), first_seen_at)
                promotion_score = _candidate_promotion_score(
                    confidence=merged_confidence,
                    evidence_count=evidence_count,
                    conversation_count=len(merged_conversation_ids),
                    level=level,
                    last_seen_at=merged_last_seen,
                )
                status = str(match_row.get("status") or "pending").strip().lower() or "pending"
                if status == "rejected" and promotion_score >= 0.86 and evidence_count >= 2:
                    status = "pending"

                existing_content = str(match_row.get("content") or content)
                merged_content = (
                    content
                    if _content_quality_score(content) >= _content_quality_score(existing_content)
                    else existing_content
                )
                merged_normalized_content = _canonicalize_candidate_text(merged_content)
                values = {
                    "content": merged_content,
                    "normalized_content": merged_normalized_content,
                    "category": category,
                    "level": level,
                    "confidence_score": merged_confidence,
                    "source_provider": str(source_provider or "heuristic"),
                    "source_llm": str(source_llm or ""),
                    "evidence_count": evidence_count,
                    "conversation_ids": merged_conversation_ids,
                    "source_message_ids": merged_source_ids,
                    "methods": merged_methods,
                    "first_seen_at": merged_first_seen,
                    "last_seen_at": merged_last_seen,
                    "promotion_score": promotion_score,
                    "status": status,
                    "updated_at": now,
                    "last_error": "",
                }
                if any(abs(v) > 1e-9 for v in candidate_vector):
                    values["vector"] = candidate_vector

                tbl.update(where=f"id = '{_escape_sql(candidate_id)}'", values=values)
                updated += 1
                refreshed = tbl.search().where(f"id = '{_escape_sql(candidate_id)}'").limit(1).to_list()
                if refreshed:
                    row = refreshed[0]
                    if candidate_id not in touched_ids:
                        touched_ids.add(candidate_id)
                        touched_rows.append(row)
                continue

            candidate_id = str(uuid.uuid4())
            promotion_score = _candidate_promotion_score(
                confidence=confidence,
                evidence_count=1,
                conversation_count=1 if conv_id else 0,
                level=level,
                last_seen_at=last_seen_at,
            )
            row = {
                "id": candidate_id,
                "canonical_key": canonical_key,
                "content": content,
                "normalized_content": normalized_content,
                "category": category,
                "level": level,
                "confidence_score": confidence,
                "source_provider": str(source_provider or "heuristic"),
                "source_llm": str(source_llm or ""),
                "evidence_count": 1,
                "conversation_ids": [conv_id] if conv_id else [],
                "source_message_ids": [source_message_id] if source_message_id else [],
                "methods": [method],
                "first_seen_at": first_seen_at,
                "last_seen_at": last_seen_at,
                "promotion_score": promotion_score,
                "status": "pending",
                "promoted_memory_id": None,
                "last_result": "",
                "last_error": "",
                "created_at": now,
                "updated_at": now,
                "vector": candidate_vector,
            }
            tbl.add([row])
            inserted += 1
            touched_ids.add(candidate_id)
            touched_rows.append(row)

        return {
            "inserted": inserted,
            "updated": updated,
            "semantic_merged": semantic_merged,
            "generic_filtered": generic_filtered,
            "touched": touched_rows,
        }

    return await enqueue_write(_write_op)


def _select_promotable_candidates(
    touched_rows: list[dict],
    *,
    limit: int,
    min_score: float,
    min_evidence: int,
    min_conversations: int,
) -> list[dict]:
    if not touched_rows:
        return []
    ranked: list[dict] = []
    fallback: list[dict] = []
    for row in touched_rows:
        content = str(row.get("content") or "").strip()
        if _looks_generic_non_memory(content):
            continue
        score = float(row.get("promotion_score") or 0.0)
        if _candidate_is_promotable(
            row,
            min_score=min_score,
            min_evidence=min_evidence,
            min_conversations=min_conversations,
        ):
            ranked.append(row)
        else:
            status = str(row.get("status") or "").strip().lower()
            confidence = _normalize_confidence(row.get("confidence_score"), default=0.8)
            if status == "pending" and confidence >= 0.9 and score >= (min_score * 0.88):
                fallback.append(row)

    key_fn = lambda r: (
        float(r.get("promotion_score") or 0.0),
        int(r.get("evidence_count") or 0),
        _candidate_conversation_count(r),
        _to_dt(r.get("last_seen_at")).timestamp(),
    )
    ranked.sort(key=key_fn, reverse=True)
    fallback.sort(key=key_fn, reverse=True)
    out = ranked[:limit]
    if not out:
        out = fallback[: max(1, min(limit, 8))]
    return out


async def _update_candidate_results(result_updates: list[dict]) -> int:
    if not result_updates:
        return 0

    async def _write_op():
        db = get_db()
        if _ANALYSIS_CANDIDATES_TABLE not in db.table_names():
            return 0
        tbl = db.open_table(_ANALYSIS_CANDIDATES_TABLE)
        updated = 0
        now = datetime.now(timezone.utc)
        for item in result_updates:
            candidate_id = str(item.get("id") or "").strip()
            if not candidate_id:
                continue
            values = {
                "status": str(item.get("status") or "pending"),
                "last_result": str(item.get("result") or ""),
                "last_error": str(item.get("error") or "")[:420],
                "updated_at": now,
            }
            promoted_memory_id = str(item.get("promoted_memory_id") or "").strip()
            values["promoted_memory_id"] = promoted_memory_id or None
            tbl.update(where=f"id = '{_escape_sql(candidate_id)}'", values=values)
            updated += 1
        return updated

    return await enqueue_write(_write_op)


def _build_candidate_reason(candidate: dict) -> str:
    method = str(candidate.get("method") or "heuristic")
    conv_title = str(candidate.get("conversation_title") or "").strip()
    conv_id = str(candidate.get("conversation_id") or "").strip()
    source_msg = str(candidate.get("source_message_id") or "").strip()
    confidence = _normalize_confidence(candidate.get("confidence"), default=0.8)
    source_excerpt = _build_source_excerpt(str(candidate.get("source_excerpt") or ""), max_chars=96)

    title_part = conv_title if conv_title else (conv_id[:20] if conv_id else "unknown conversation")
    message_part = f", message {source_msg[:16]}" if source_msg else ""
    base = (
        f"Auto-suggested from {title_part} via {method} "
        f"(confidence {confidence:.2f}{message_part})."
    )
    if source_excerpt:
        base += f' Context: "{source_excerpt}"'
    return base[:420]


def _lookup_source_excerpt(
    conversation_ids: list[str],
    source_message_ids: list[str],
    excerpt_by_pair: dict[tuple[str, str], str],
    excerpt_by_message_id: dict[str, str],
) -> str:
    for conv_id in conversation_ids:
        for msg_id in source_message_ids:
            if not conv_id or not msg_id:
                continue
            value = excerpt_by_pair.get((conv_id, msg_id), "")
            if value:
                return value
    for msg_id in source_message_ids:
        if not msg_id:
            continue
        value = excerpt_by_message_id.get(msg_id, "")
        if value:
            return value
    return ""


async def mine_memories_from_conversations(
    dry_run: bool = True,
    force_reanalyze: bool = False,
    include_assistant_messages: bool = False,
    max_conversations: int = 40,
    max_messages_per_conversation: int = 24,
    max_candidates_per_conversation: int = 6,
    max_new_memories: int = 120,
    min_confidence: float = 0.78,
    provider: str = "auto",
    model: Optional[str] = None,
    api_base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    concurrency: int = 2,
    conversation_ids: Optional[list[str]] = None,
    require_llm_configured: Optional[bool] = None,
) -> dict:
    total_started = time.monotonic()
    _set_runtime_phase(
        step=1,
        total_steps=5,
        label="Preparing analysis",
        detail="Validating LLM runtime and loading configuration",
    )
    safe_max_conversations = max(1, min(int(max_conversations), 400))
    safe_max_messages = max(4, min(int(max_messages_per_conversation), 80))
    safe_max_candidates_per_conversation = max(1, min(int(max_candidates_per_conversation), 20))
    safe_max_new_memories = max(1, min(int(max_new_memories), 500))
    safe_min_confidence = _normalize_confidence(min_confidence)
    safe_concurrency = max(1, min(int(concurrency), 4))
    safe_require_llm_configured = _resolve_require_llm_configured(require_llm_configured)
    timings: dict[str, int] = {
        "load_ms": 0,
        "extract_ms": 0,
        "dedupe_ms": 0,
        "candidate_store_ms": 0,
        "write_ms": 0,
        "link_ms": 0,
        "mark_ms": 0,
        "index_ms": 0,
        "total_ms": 0,
    }

    gate = await get_analysis_llm_gate_status(
        provider=provider,
        model=model,
        api_base_url=api_base_url,
        api_key=api_key,
        require_llm_configured=safe_require_llm_configured,
    )
    runtime = gate.get("runtime", {})
    use_llm = bool(gate.get("llm_enabled"))
    llm_preflight_error: Optional[str] = None
    if not gate.get("analysis_allowed", True):
        blocked_reason = str(gate.get("reason") or "Conversation analysis is blocked until LLM is configured.")
        _set_runtime_phase(
            step=1,
            total_steps=5,
            label="Blocked",
            detail=blocked_reason[:180],
        )
        timings["total_ms"] = int((time.monotonic() - total_started) * 1000)
        return {
            "status": "blocked",
            "message": blocked_reason,
            "mode": "import",
            "provider": runtime.get("provider"),
            "llm_enabled": False,
            "llm_required": safe_require_llm_configured,
            "conversations_scanned": 0,
            "conversations_selected": 0,
            "skipped_already_analyzed": 0,
            "skipped_by_index": 0,
            "skipped_by_tags": 0,
            "analysis_index_size": 0,
            "candidates_total": 0,
            "candidate_sources": {"llm": 0, "heuristic": 0},
            "candidate_store": {
                "inserted": 0,
                "updated": 0,
                "semantic_merged": 0,
                "touched_total": 0,
                "promotable_total": 0,
                "status_updates": 0,
                "promotion_min_score": 0.0,
                "promotion_min_evidence": 0,
                "promotion_min_conversations": 0,
                "semantic_dedupe_threshold": 0.0,
            },
            "write_stats": {"created": 0, "merged": 0, "skipped": 0, "conflict_pending": 0, "rejected": 0},
            "linked_conversations": 0,
            "analyzed_marked": 0,
            "indexed_conversations": 0,
            "preview": [],
            "details": [],
            "llm_error_count": 1,
            "llm_errors": [blocked_reason],
            "metrics": timings,
        }
    if not use_llm:
        llm_preflight_error = str(gate.get("reason") or "").strip() or None

    _set_runtime_phase(
        step=2,
        total_steps=5,
        label="Analyzing conversation contexts",
        detail="Scanning conversations and building context windows",
    )

    def _load_progress(payload: dict[str, Any]):
        stage = str(payload.get("stage") or "").strip().lower()
        if stage == "scan":
            scanned = max(0, int(payload.get("scanned") or 0))
            scan_total = max(0, int(payload.get("scan_total") or 0))
            candidates = max(0, int(payload.get("candidates") or 0))
            probe_limit = max(0, int(payload.get("probe_limit") or 0))
            detail = (
                f"Scanned {scanned}/{scan_total} conversations · "
                f"candidates {candidates}/{probe_limit if probe_limit > 0 else '?'}"
            )
            _set_runtime_phase(
                step=2,
                total_steps=5,
                label="Analyzing conversation contexts",
                detail=detail,
                items_done=scanned,
                items_total=scan_total,
                items_unit="conversations",
            )
        elif stage == "hydrate":
            processed = max(0, int(payload.get("processed") or 0))
            total = max(0, int(payload.get("total") or 0))
            selected = max(0, int(payload.get("selected") or 0))
            detail = f"Hydrating {processed}/{total} candidates · selected {selected}"
            _set_runtime_phase(
                step=2,
                total_steps=5,
                label="Analyzing conversation contexts",
                detail=detail,
                items_done=processed,
                items_total=total,
                items_unit="candidates",
            )

    load_started = time.monotonic()
    loaded = _load_conversation_contexts(
        max_conversations=safe_max_conversations,
        max_messages_per_conversation=safe_max_messages,
        include_assistant_messages=include_assistant_messages,
        force_reanalyze=force_reanalyze,
        conversation_ids=conversation_ids,
        progress_cb=_load_progress,
    )
    timings["load_ms"] = int((time.monotonic() - load_started) * 1000)
    contexts = loaded["contexts"]
    _set_runtime_phase(
        step=2,
        total_steps=5,
        label="Analyzing conversation contexts",
        detail=(
            f"Selected {len(contexts)} conversations "
            f"from {int(loaded.get('conversations_scanned', 0) or 0)} scanned"
        ),
        items_done=len(contexts),
        items_total=max(len(contexts), int(loaded.get("conversations_scanned", 0) or 0)),
        items_unit="conversations",
    )
    source_excerpt_by_pair: dict[tuple[str, str], str] = {}
    source_excerpt_by_message_id: dict[str, str] = {}
    for ctx in contexts:
        conv_id = str(ctx.get("conversation_id") or "").strip()
        for msg in ctx.get("messages", []) if isinstance(ctx.get("messages"), list) else []:
            if str(msg.get("role") or "").strip().lower() != "user":
                continue
            msg_id = str(msg.get("id") or "").strip()
            if not msg_id:
                continue
            excerpt = _build_source_excerpt(str(msg.get("content") or ""))
            if not excerpt:
                continue
            if conv_id:
                source_excerpt_by_pair[(conv_id, msg_id)] = excerpt
            if msg_id not in source_excerpt_by_message_id:
                source_excerpt_by_message_id[msg_id] = excerpt

    candidate_sources = {"llm": 0, "heuristic": 0}
    llm_errors: list[str] = []
    if llm_preflight_error:
        llm_errors.append(llm_preflight_error)

    _set_runtime_phase(
        step=3,
        total_steps=5,
        label="Extracting memory candidates",
        detail=f"Processing {len(contexts)} selected conversations",
        items_done=0,
        items_total=len(contexts),
        items_unit="conversations",
    )

    semaphore = asyncio.Semaphore(safe_concurrency)
    per_conversation_extract: dict[str, dict[str, int]] = {}
    extract_progress_total = max(1, len(contexts))
    extract_progress_done = 0
    extract_progress_candidates = 0
    extract_progress_lock = asyncio.Lock()

    async def _mine_one(context: dict) -> list[dict]:
        nonlocal extract_progress_done, extract_progress_candidates
        async with semaphore:
            conv_id = str(context.get("conversation_id") or "")
            started = time.monotonic()
            candidates: list[dict] = []
            if use_llm:
                try:
                    candidates = await _extract_candidates_with_llm(
                        context=context,
                        runtime=runtime,
                        max_candidates_per_conversation=safe_max_candidates_per_conversation,
                        min_confidence=safe_min_confidence,
                    )
                except Exception as e:
                    llm_errors.append(str(e))
                    candidates = []
            if candidates:
                candidate_sources["llm"] += len(candidates)
                if conv_id:
                    per_conversation_extract[conv_id] = {
                        "extract_ms": int((time.monotonic() - started) * 1000),
                        "candidates": len(candidates),
                    }
                async with extract_progress_lock:
                    extract_progress_done += 1
                    extract_progress_candidates += len(candidates)
                    done = extract_progress_done
                    cand_total = extract_progress_candidates
                if done % max(1, extract_progress_total // 24) == 0 or done >= extract_progress_total:
                    _set_runtime_phase(
                        step=3,
                        total_steps=5,
                        label="Extracting memory candidates",
                        detail=f"Processed {done}/{extract_progress_total} conversations · candidates {cand_total}",
                        items_done=done,
                        items_total=extract_progress_total,
                        items_unit="conversations",
                    )
                return candidates
            fallback = _heuristic_candidates_for_conversation(
                context=context,
                max_candidates_per_conversation=safe_max_candidates_per_conversation,
                min_confidence=safe_min_confidence,
            )
            candidate_sources["heuristic"] += len(fallback)
            if conv_id:
                per_conversation_extract[conv_id] = {
                    "extract_ms": int((time.monotonic() - started) * 1000),
                    "candidates": len(fallback),
                }
            async with extract_progress_lock:
                extract_progress_done += 1
                extract_progress_candidates += len(fallback)
                done = extract_progress_done
                cand_total = extract_progress_candidates
            if done % max(1, extract_progress_total // 24) == 0 or done >= extract_progress_total:
                _set_runtime_phase(
                    step=3,
                    total_steps=5,
                    label="Extracting memory candidates",
                    detail=f"Processed {done}/{extract_progress_total} conversations · candidates {cand_total}",
                    items_done=done,
                    items_total=extract_progress_total,
                    items_unit="conversations",
                )
            return fallback

    extract_started = time.monotonic()
    mined_batches = await asyncio.gather(*[_mine_one(context) for context in contexts])
    timings["extract_ms"] = int((time.monotonic() - extract_started) * 1000)
    raw_candidates = [candidate for batch in mined_batches for candidate in batch]
    raw_candidates_total = len(raw_candidates)
    _set_runtime_phase(
        step=3,
        total_steps=5,
        label="Extracting memory candidates",
        detail=f"Collected {raw_candidates_total} raw candidates",
        items_done=len(contexts),
        items_total=max(1, len(contexts)),
        items_unit="conversations",
    )

    dedupe_started = time.monotonic()
    unique_candidates: list[dict] = []
    seen_content: set[str] = set()
    for candidate in raw_candidates:
        key = _normalize_for_dedupe(candidate.get("content", ""))
        if not key or key in seen_content:
            continue
        seen_content.add(key)
        unique_candidates.append(candidate)
    first_pass_unique_total = len(unique_candidates)

    consolidated_candidates = _consolidate_candidates(unique_candidates, max_chars=420, max_cluster_size=4)

    unique_candidates = []
    seen_content.clear()
    for candidate in consolidated_candidates:
        key = _normalize_for_dedupe(candidate.get("content", ""))
        if not key or key in seen_content:
            continue
        seen_content.add(key)
        unique_candidates.append(candidate)

    candidate_store_cap = min(max(safe_max_new_memories * 12, 400), 4000)
    unique_candidates = unique_candidates[:candidate_store_cap]
    post_dedupe_total = len(unique_candidates)
    duplicate_pruned = max(0, raw_candidates_total - post_dedupe_total)
    timings["dedupe_ms"] = int((time.monotonic() - dedupe_started) * 1000)
    _set_runtime_phase(
        step=3,
        total_steps=5,
        label="Extracting memory candidates",
        detail=f"Deduplicated to {post_dedupe_total} candidates",
        items_done=post_dedupe_total,
        items_total=max(post_dedupe_total, raw_candidates_total, 1),
        items_unit="candidates",
    )
    preview = [
        {
            "content": c["content"],
            "category": c["category"],
            "level": c["level"],
            "confidence": c["confidence"],
            "conversation_id": c["conversation_id"],
            "conversation_title": c["conversation_title"],
            "source_message_id": c["source_message_id"],
            "source_message_timestamp": c.get("source_message_timestamp"),
            "source_excerpt": c.get("source_excerpt", ""),
            "method": c["method"],
            "suggestion_reason": _build_candidate_reason(c),
        }
        for c in unique_candidates[:40]
    ]
    generic_candidates_detected = sum(
        1 for c in unique_candidates if _looks_generic_non_memory(str(c.get("content") or ""))
    )
    quality_metrics_base = {
        "raw_candidates_total": raw_candidates_total,
        "first_pass_unique_total": first_pass_unique_total,
        "post_dedupe_total": post_dedupe_total,
        "duplicate_pruned": duplicate_pruned,
    }

    if dry_run:
        timings["total_ms"] = int((time.monotonic() - total_started) * 1000)
        _set_runtime_phase(
            step=5,
            total_steps=5,
            label="Completed",
            detail=f"Dry run completed with {post_dedupe_total} candidates",
            items_done=1,
            items_total=1,
            items_unit="runs",
        )
        quality_metrics = {
            **quality_metrics_base,
            "generic_filtered_total": generic_candidates_detected,
            "generic_rate": (
                round(generic_candidates_detected / raw_candidates_total, 4)
                if raw_candidates_total > 0
                else 0.0
            ),
            "duplicate_rate": (
                round(duplicate_pruned / raw_candidates_total, 4)
                if raw_candidates_total > 0
                else 0.0
            ),
            "accepted_rate": 0.0,
            "context_coverage_rate": 0.0,
        }
        return {
            "status": "ok",
            "mode": "dry_run",
            "provider": runtime.get("provider"),
            "llm_enabled": use_llm,
            "conversations_scanned": loaded.get("conversations_scanned", 0),
            "conversations_selected": len(contexts),
            "skipped_already_analyzed": loaded.get("skipped_already_analyzed", 0),
            "skipped_by_index": loaded.get("skipped_by_index", 0),
            "skipped_by_tags": loaded.get("skipped_by_tags", 0),
            "analysis_index_size": loaded.get("index_size", 0),
            "candidates_total": len(unique_candidates),
            "candidate_sources": candidate_sources,
            "preview": preview,
            "llm_error_count": len(llm_errors),
            "llm_errors": llm_errors[:3],
            "quality_metrics": quality_metrics,
            "metrics": timings,
        }

    source_provider = runtime.get("provider") if use_llm else "heuristic"
    source_llm = f"conversation-analyzer:{source_provider}"
    created_by_conversation: dict[str, list[str]] = {}
    config = load_config(force_reload=True)
    analysis_cfg = config.get("conversation_analysis", {}) if isinstance(config.get("conversation_analysis"), dict) else {}
    promotion_min_score = max(0.55, min(float(analysis_cfg.get("promotion_min_score", 0.72) or 0.72), 0.99))
    promotion_min_evidence = max(1, min(int(analysis_cfg.get("promotion_min_evidence", 1) or 1), 8))
    promotion_min_conversations = max(1, min(int(analysis_cfg.get("promotion_min_conversations", 1) or 1), 8))
    semantic_dedupe_threshold = max(0.84, min(float(analysis_cfg.get("semantic_dedupe_threshold", 0.92) or 0.92), 0.99))

    write_stats = {
        "created": 0,
        "merged": 0,
        "skipped": 0,
        "conflict_pending": 0,
        "rejected": 0,
    }
    generic_filtered_during_write = 0
    write_details: list[dict] = []
    conv_outcomes: dict[str, dict[str, int]] = {
        str(ctx.get("conversation_id") or ""): {
            "candidates": 0,
            "created": 0,
            "errors": 0,
            "extract_ms": int(per_conversation_extract.get(str(ctx.get("conversation_id") or ""), {}).get("extract_ms", 0)),
        }
        for ctx in contexts
        if str(ctx.get("conversation_id") or "")
    }
    context_conv_ids = {str(ctx.get("conversation_id") or "") for ctx in contexts if str(ctx.get("conversation_id") or "")}
    for candidate in unique_candidates:
        conv_id = str(candidate.get("conversation_id") or "")
        if not conv_id:
            continue
        outcome = conv_outcomes.setdefault(conv_id, {"candidates": 0, "created": 0, "errors": 0, "extract_ms": 0})
        outcome["candidates"] += 1

    _set_runtime_phase(
        step=4,
        total_steps=5,
        label="Writing memory suggestions",
        detail=f"Scoring and promoting up to {safe_max_new_memories} candidates",
        items_done=0,
        items_total=max(1, len(unique_candidates)),
        items_unit="candidates",
    )

    candidate_store_started = time.monotonic()
    candidate_store = await _upsert_conversation_candidates(
        unique_candidates,
        source_provider=source_provider,
        source_llm=source_llm,
        semantic_dedupe_threshold=semantic_dedupe_threshold,
    )
    generic_filtered_store = int(candidate_store.get("generic_filtered", 0) if isinstance(candidate_store, dict) else 0)
    timings["candidate_store_ms"] = int((time.monotonic() - candidate_store_started) * 1000)

    touched_rows = candidate_store.get("touched", []) if isinstance(candidate_store, dict) else []
    if not touched_rows and unique_candidates:
        # Safety fallback for environments where candidate table is unavailable.
        now = datetime.now(timezone.utc)
        touched_rows = []
        for candidate in unique_candidates:
            conv_id = str(candidate.get("conversation_id") or "").strip()
            source_message_id = str(candidate.get("source_message_id") or "").strip()
            confidence = _normalize_confidence(candidate.get("confidence"), default=0.8)
            touched_rows.append(
                {
                    "id": f"volatile:{uuid.uuid4()}",
                    "content": str(candidate.get("content") or ""),
                    "category": _normalize_category(candidate.get("category")),
                    "level": _normalize_level(candidate.get("level")),
                    "confidence_score": confidence,
                    "conversation_ids": [conv_id] if conv_id else [],
                    "source_message_ids": [source_message_id] if source_message_id else [],
                    "methods": [str(candidate.get("method") or "heuristic")],
                    "status": "pending",
                    "last_seen_at": candidate.get("source_message_timestamp") or now,
                    "evidence_count": 1,
                    "promotion_score": _candidate_promotion_score(
                        confidence=confidence,
                        evidence_count=1,
                        conversation_count=1 if conv_id else 0,
                        level=candidate.get("level"),
                        last_seen_at=candidate.get("source_message_timestamp") or now,
                    ),
                }
            )
    promotable_candidates = _select_promotable_candidates(
        touched_rows,
        limit=safe_max_new_memories,
        min_score=promotion_min_score,
        min_evidence=promotion_min_evidence,
        min_conversations=promotion_min_conversations,
    )
    candidate_result_updates: list[dict] = []
    promoted_candidate_ids: set[str] = set()
    promotable_with_context = 0
    promotable_total = len(promotable_candidates)
    _set_runtime_phase(
        step=4,
        total_steps=5,
        label="Writing memory suggestions",
        detail=f"Promoting {promotable_total} candidates",
        items_done=0,
        items_total=max(1, promotable_total),
        items_unit="candidates",
    )

    write_started = time.monotonic()
    for write_idx, candidate in enumerate(promotable_candidates, start=1):
        candidate_id = str(candidate.get("id") or "").strip()
        if not candidate_id or candidate_id in promoted_candidate_ids:
            continue
        promoted_candidate_ids.add(candidate_id)
        candidate_content = str(candidate.get("content") or "").strip()
        conversation_ids = [str(v).strip() for v in (candidate.get("conversation_ids") or []) if str(v).strip()]
        source_message_ids = [str(v).strip() for v in (candidate.get("source_message_ids") or []) if str(v).strip()]
        methods = [str(v).strip() for v in (candidate.get("methods") or []) if str(v).strip()]
        primary_conv_id = conversation_ids[0] if conversation_ids else ""
        confidence = _normalize_confidence(candidate.get("confidence_score"), default=0.8)

        if _looks_generic_non_memory(candidate_content):
            generic_filtered_during_write += 1
            write_stats["rejected"] += 1
            candidate_result_updates.append(
                {
                    "id": candidate_id,
                    "status": "rejected",
                    "result": "filtered_non_memory",
                    "error": "Filtered generic/non-personal candidate.",
                    "promoted_memory_id": None,
                }
            )
            if len(write_details) < 50:
                write_details.append(
                    {
                        "candidate_id": candidate_id,
                        "conversation_id": primary_conv_id,
                        "conversation_ids": conversation_ids[:6],
                        "source_message_id": source_message_ids[0] if source_message_ids else "",
                        "source_message_timestamp": candidate.get("last_seen_at"),
                        "content": candidate_content,
                        "evidence_count": int(candidate.get("evidence_count") or 0),
                        "promotion_score": float(candidate.get("promotion_score") or 0.0),
                        "action": "filtered_non_memory",
                        "memory_id": None,
                        "message": "Filtered generic/non-personal candidate.",
                    }
                )
            continue

        source_excerpt = _lookup_source_excerpt(
            conversation_ids=conversation_ids,
            source_message_ids=source_message_ids,
            excerpt_by_pair=source_excerpt_by_pair,
            excerpt_by_message_id=source_excerpt_by_message_id,
        )
        if str(source_excerpt or "").strip():
            promotable_with_context += 1
        suggestion_reason = _build_candidate_reason(
            {
                "method": methods[0] if methods else "heuristic",
                "conversation_id": primary_conv_id,
                "conversation_title": "",
                "source_message_id": source_message_ids[0] if source_message_ids else "",
                "confidence": confidence,
                "source_excerpt": source_excerpt,
            }
        )
        try:
            result = await create_memory(
                content=candidate_content,
                category=_normalize_category(candidate.get("category")),
                level=_normalize_level(candidate.get("level")),
                source_llm=source_llm,
                importance_score=0.6,
                confidence_score=float(confidence),
                tags=[_ANALYSIS_TAG],
                source_conversation_id=primary_conv_id or None,
                source_message_id=source_message_ids[0] if source_message_ids else None,
                source_excerpt=source_excerpt,
                suggestion_reason=suggestion_reason,
                forced_status="pending_review",
                created_at=candidate.get("last_seen_at"),
                event_date=candidate.get("last_seen_at"),
            )
            action = result.get("action", "error")
            if action == "created":
                write_stats["created"] += 1
                mem_id = str(result.get("id") or "")
                if mem_id:
                    for conv_id in conversation_ids:
                        created_by_conversation.setdefault(conv_id, []).append(mem_id)
                    for conv_id in conversation_ids:
                        if conv_id in context_conv_ids:
                            outcome = conv_outcomes.setdefault(
                                conv_id,
                                {"candidates": 0, "created": 0, "errors": 0, "extract_ms": 0},
                            )
                            outcome["created"] += 1
                candidate_result_updates.append(
                    {
                        "id": candidate_id,
                        "status": "promoted",
                        "result": action,
                        "error": "",
                        "promoted_memory_id": result.get("id"),
                    }
                )
            elif action == "merged":
                write_stats["merged"] += 1
                candidate_result_updates.append(
                    {
                        "id": candidate_id,
                        "status": "merged",
                        "result": action,
                        "error": "",
                        "promoted_memory_id": result.get("id"),
                    }
                )
            elif action == "skipped":
                write_stats["skipped"] += 1
                candidate_result_updates.append(
                    {
                        "id": candidate_id,
                        "status": "merged",
                        "result": action,
                        "error": "",
                        "promoted_memory_id": result.get("id"),
                    }
                )
            elif action == "conflict_pending":
                write_stats["conflict_pending"] += 1
                candidate_result_updates.append(
                    {
                        "id": candidate_id,
                        "status": "conflict_pending",
                        "result": action,
                        "error": "",
                        "promoted_memory_id": None,
                    }
                )
            elif action == "error":
                write_stats["rejected"] += 1
                for conv_id in conversation_ids:
                    if conv_id in context_conv_ids:
                        outcome = conv_outcomes.setdefault(
                            conv_id,
                            {"candidates": 0, "created": 0, "errors": 0, "extract_ms": 0},
                        )
                        outcome["errors"] += 1
                candidate_result_updates.append(
                    {
                        "id": candidate_id,
                        "status": "rejected",
                        "result": action,
                        "error": str(result.get("message") or ""),
                        "promoted_memory_id": None,
                    }
                )
            else:
                write_stats["rejected"] += 1
                for conv_id in conversation_ids:
                    if conv_id in context_conv_ids:
                        outcome = conv_outcomes.setdefault(
                            conv_id,
                            {"candidates": 0, "created": 0, "errors": 0, "extract_ms": 0},
                        )
                        outcome["errors"] += 1
                candidate_result_updates.append(
                    {
                        "id": candidate_id,
                        "status": "rejected",
                        "result": str(action),
                        "error": str(result.get("message") or ""),
                        "promoted_memory_id": None,
                    }
                )

            if len(write_details) < 50:
                write_details.append(
                    {
                        "candidate_id": candidate_id,
                        "conversation_id": primary_conv_id,
                        "conversation_ids": conversation_ids[:6],
                        "source_message_id": source_message_ids[0] if source_message_ids else "",
                        "source_message_timestamp": candidate.get("last_seen_at"),
                        "content": str(candidate.get("content") or ""),
                        "evidence_count": int(candidate.get("evidence_count") or 0),
                        "promotion_score": float(candidate.get("promotion_score") or 0.0),
                        "action": action,
                        "memory_id": result.get("id"),
                        "message": result.get("message"),
                        "suggestion_reason": suggestion_reason,
                    }
                )
        except Exception as e:
            write_stats["rejected"] += 1
            for conv_id in conversation_ids:
                if conv_id in context_conv_ids:
                    outcome = conv_outcomes.setdefault(
                        conv_id,
                        {"candidates": 0, "created": 0, "errors": 0, "extract_ms": 0},
                    )
                    outcome["errors"] += 1
            candidate_result_updates.append(
                {
                    "id": candidate_id,
                    "status": "rejected",
                    "result": "error",
                    "error": str(e),
                    "promoted_memory_id": None,
                }
            )
            if len(write_details) < 50:
                write_details.append(
                    {
                        "candidate_id": candidate_id,
                        "conversation_id": primary_conv_id,
                        "conversation_ids": conversation_ids[:6],
                        "source_message_id": source_message_ids[0] if source_message_ids else "",
                        "source_message_timestamp": candidate.get("last_seen_at"),
                        "content": str(candidate.get("content") or ""),
                        "evidence_count": int(candidate.get("evidence_count") or 0),
                        "promotion_score": float(candidate.get("promotion_score") or 0.0),
                        "action": "error",
                        "memory_id": None,
                        "message": str(e),
                        "suggestion_reason": suggestion_reason,
                    }
                )
        if write_idx % max(1, promotable_total // 24 if promotable_total > 0 else 1) == 0 or write_idx >= promotable_total:
            _set_runtime_phase(
                step=4,
                total_steps=5,
                label="Writing memory suggestions",
                detail=(
                    f"Processed {write_idx}/{promotable_total} · "
                    f"created {int(write_stats.get('created', 0) or 0)} · "
                    f"rejected {int(write_stats.get('rejected', 0) or 0)}"
                ),
                items_done=write_idx,
                items_total=max(1, promotable_total),
                items_unit="candidates",
            )
    candidate_status_updates = await _update_candidate_results(candidate_result_updates)
    timings["write_ms"] = int((time.monotonic() - write_started) * 1000)

    link_started = time.monotonic()
    linked_conversations = await _link_created_memories(created_by_conversation)
    timings["link_ms"] = int((time.monotonic() - link_started) * 1000)

    conversation_results: dict[str, str] = {}
    for conv_id, outcome in conv_outcomes.items():
        if int(outcome.get("created", 0)) > 0:
            conversation_results[conv_id] = "has_memory"
        elif int(outcome.get("errors", 0)) > 0:
            conversation_results[conv_id] = "error"
        else:
            conversation_results[conv_id] = "none"

    mark_started = time.monotonic()
    analyzed_marked = await _mark_conversations_analyzed(
        contexts,
        source_provider,
        result_by_conversation=conversation_results,
    )
    timings["mark_ms"] = int((time.monotonic() - mark_started) * 1000)

    index_started = time.monotonic()
    indexed_conversations = await _upsert_analysis_index(
        contexts=contexts,
        provider=source_provider,
        result_by_conversation=conversation_results,
        outcomes_by_conversation=conv_outcomes,
    )
    timings["index_ms"] = int((time.monotonic() - index_started) * 1000)
    timings["total_ms"] = int((time.monotonic() - total_started) * 1000)
    generic_filtered_total = generic_filtered_store + generic_filtered_during_write
    accepted_denominator = int(write_stats.get("created", 0) or 0) + int(write_stats.get("rejected", 0) or 0)
    quality_metrics = {
        **quality_metrics_base,
        "generic_filtered_total": generic_filtered_total,
        "generic_rate": (
            round(generic_filtered_total / raw_candidates_total, 4) if raw_candidates_total > 0 else 0.0
        ),
        "duplicate_rate": (
            round(duplicate_pruned / raw_candidates_total, 4) if raw_candidates_total > 0 else 0.0
        ),
        "accepted_rate": (
            round((int(write_stats.get("created", 0) or 0)) / accepted_denominator, 4)
            if accepted_denominator > 0
            else 0.0
        ),
        "context_coverage_rate": (
            round(promotable_with_context / len(promotable_candidates), 4)
            if promotable_candidates
            else 0.0
        ),
    }
    _set_runtime_phase(
        step=5,
        total_steps=5,
        label="Completed",
        detail=(
            f"Created {int(write_stats.get('created', 0) or 0)} memories · "
            f"rejected {int(write_stats.get('rejected', 0) or 0)}"
        ),
        items_done=1,
        items_total=1,
        items_unit="runs",
    )

    return {
        "status": "ok",
        "mode": "import",
        "provider": runtime.get("provider"),
        "llm_enabled": use_llm,
        "conversations_scanned": loaded.get("conversations_scanned", 0),
        "conversations_selected": len(contexts),
        "skipped_already_analyzed": loaded.get("skipped_already_analyzed", 0),
        "skipped_by_index": loaded.get("skipped_by_index", 0),
        "skipped_by_tags": loaded.get("skipped_by_tags", 0),
        "analysis_index_size": loaded.get("index_size", 0),
        "candidates_total": len(unique_candidates),
        "candidate_sources": candidate_sources,
        "candidate_store": {
            "inserted": int(candidate_store.get("inserted", 0) if isinstance(candidate_store, dict) else 0),
            "updated": int(candidate_store.get("updated", 0) if isinstance(candidate_store, dict) else 0),
            "semantic_merged": int(candidate_store.get("semantic_merged", 0) if isinstance(candidate_store, dict) else 0),
            "generic_filtered": generic_filtered_store,
            "touched_total": len(touched_rows),
            "promotable_total": len(promotable_candidates),
            "status_updates": int(candidate_status_updates or 0),
            "promotion_min_score": promotion_min_score,
            "promotion_min_evidence": promotion_min_evidence,
            "promotion_min_conversations": promotion_min_conversations,
            "semantic_dedupe_threshold": semantic_dedupe_threshold,
        },
        "write_stats": write_stats,
        "linked_conversations": linked_conversations,
        "analyzed_marked": analyzed_marked,
        "indexed_conversations": indexed_conversations,
        "preview": preview,
        "details": write_details,
        "llm_error_count": len(llm_errors),
        "llm_errors": llm_errors[:3],
        "quality_metrics": quality_metrics,
        "metrics": timings,
    }


async def run_mining_singleflight(
    *,
    trigger: str,
    wait_if_busy: bool = False,
    **kwargs,
) -> dict:
    """
    Serialize conversation analysis runs across manual + scheduler triggers.
    """
    lock = _get_run_lock()
    if lock.locked() and not wait_if_busy:
        status = get_analysis_runtime_status()
        return {
            "status": "busy",
            "trigger": trigger,
            "message": "Conversation analysis already running.",
            "runtime": status,
        }

    async with lock:
        started_at = datetime.now(timezone.utc).isoformat()
        start_monotonic = time.monotonic()
        _ANALYSIS_RUNTIME_STATUS["running"] = True
        _ANALYSIS_RUNTIME_STATUS["trigger"] = trigger
        _ANALYSIS_RUNTIME_STATUS["started_at"] = started_at
        _ANALYSIS_RUNTIME_STATUS["last_error"] = None
        _ANALYSIS_RUNTIME_STATUS["last_result_summary"] = None
        try:
            result = await mine_memories_from_conversations(**kwargs)
            write_stats = result.get("write_stats", {}) if isinstance(result, dict) else {}
            metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
            _ANALYSIS_RUNTIME_STATUS["last_result_summary"] = {
                "conversations_selected": int(result.get("conversations_selected", 0) if isinstance(result, dict) else 0),
                "candidates_total": int(result.get("candidates_total", 0) if isinstance(result, dict) else 0),
                "created": int(write_stats.get("created", 0) or 0),
                "rejected": int(write_stats.get("rejected", 0) or 0),
                "duration_ms": int(metrics.get("total_ms", 0) if isinstance(metrics, dict) else 0),
            }
            return {
                "status": "ok",
                "trigger": trigger,
                "result": result,
            }
        except Exception as e:
            _set_runtime_phase(
                step=5,
                total_steps=5,
                label="Failed",
                detail=str(e)[:180],
                items_done=1,
                items_total=1,
                items_unit="runs",
            )
            _ANALYSIS_RUNTIME_STATUS["last_error"] = str(e)
            raise
        finally:
            _ANALYSIS_RUNTIME_STATUS["running"] = False
            _ANALYSIS_RUNTIME_STATUS["last_completed_at"] = datetime.now(timezone.utc).isoformat()
            _ANALYSIS_RUNTIME_STATUS["last_duration_ms"] = int((time.monotonic() - start_monotonic) * 1000)
