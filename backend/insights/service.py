from __future__ import annotations

import copy
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from backend.config import load_config, save_config
from backend.database.client import get_db

WINDOW_DAYS = 30
MAX_ROWS = 200000
SUPPORTED_PROVIDERS = {"openai", "anthropic", "ollama"}
KNOWN_CATEGORIES = ["identity", "preferences", "skills", "relationships", "projects", "history", "working"]
AUTO_CONVERSATION_ANALYSIS_TAG = "auto:conversation-analysis"

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "about", "have", "has", "had", "into",
    "dans", "avec", "pour", "une", "des", "les", "sur", "par", "est", "sont", "mais", "plus", "moins",
    "user", "assistant", "mnesis", "memory", "memories", "project", "projects", "using", "used", "like",
}


def _to_dt(value: Any, fallback: Optional[datetime] = None) -> datetime:
    default = fallback or datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return default
    return default


def _masked(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _preview(content: str, max_len: int = 96) -> str:
    text = (content or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _normalize_provider(value: Any) -> str:
    provider = str(value or "openai").strip().lower()
    aliases = {
        "oai": "openai",
        "chatgpt": "openai",
        "claude": "anthropic",
        "local": "ollama",
        "local-ollama": "ollama",
    }
    return aliases.get(provider, provider)


def _load_rows(table_name: str, limit: int = MAX_ROWS) -> list[dict]:
    db = get_db()
    if table_name not in db.table_names():
        return []
    try:
        return db.open_table(table_name).search().limit(limit).to_list()
    except Exception:
        return []


def _domain_for_category(category: str) -> str:
    category = (category or "").strip().lower()
    if category in {"skills", "projects"}:
        return "code"
    if category in {"relationships", "history"}:
        return "business"
    if category in {"identity", "preferences"}:
        return "personal"
    return "casual"


def _days_range(now: datetime, days: int) -> list[str]:
    start = (now - timedelta(days=days - 1)).date()
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def _extract_recurrent_topics(memories: list[dict], now: datetime) -> list[dict]:
    cutoff = now - timedelta(days=WINDOW_DAYS)
    counter: Counter[str] = Counter()
    pattern = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")

    for row in memories:
        if row.get("status") == "archived":
            continue
        ts = _to_dt(row.get("updated_at") or row.get("created_at"), fallback=now)
        if ts < cutoff:
            continue
        content = row.get("content", "")
        for raw in pattern.findall(content):
            token = raw.lower()
            if token in STOPWORDS:
                continue
            if token.isdigit() or len(token) < 3:
                continue
            counter[token] += 1

    topics = []
    for token, count in counter.most_common(10):
        if count < 2:
            break
        topics.append({"topic": token, "count": count})
    return topics


def _build_level_counts(memories: list[dict]) -> dict[str, int]:
    counts = {"semantic": 0, "episodic": 0, "working": 0}
    for row in memories:
        if row.get("status") == "archived":
            continue
        level = (row.get("level") or "").strip().lower()
        if level in counts:
            counts[level] += 1
        else:
            counts[level] = counts.get(level, 0) + 1
    return counts


def _build_top_referenced(memories: list[dict], limit: int = 5) -> list[dict]:
    active = [m for m in memories if m.get("status") != "archived"]
    active.sort(
        key=lambda row: (
            int(row.get("reference_count") or 0),
            float(row.get("importance_score") or 0.0),
        ),
        reverse=True,
    )
    top = []
    for row in active[:limit]:
        top.append(
            {
                "id": row.get("id"),
                "content_preview": _preview(row.get("content", "")),
                "reference_count": int(row.get("reference_count") or 0),
                "category": row.get("category") or "unknown",
                "level": row.get("level") or "unknown",
            }
        )
    return top


def _is_auto_conversation_pending_memory(row: dict) -> bool:
    if str(row.get("status") or "").strip().lower() != "pending_review":
        return False

    source_llm = str(row.get("source_llm") or "").strip().lower()
    if source_llm.startswith("conversation-analyzer:"):
        return True

    tags = row.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if str(tag or "").strip().lower() == AUTO_CONVERSATION_ANALYSIS_TAG:
                return True
    return False


def _build_auto_memory_suggestions(memories: list[dict], limit: int = 8) -> list[dict]:
    pending = [row for row in memories if _is_auto_conversation_pending_memory(row)]
    pending.sort(
        key=lambda row: (
            _to_dt(row.get("updated_at") or row.get("created_at")).timestamp(),
            float(row.get("confidence_score") or 0.0),
        ),
        reverse=True,
    )

    out: list[dict] = []
    for row in pending[: max(1, min(limit, 20))]:
        out.append(
            {
                "id": str(row.get("id") or ""),
                "content": str(row.get("content") or ""),
                "content_preview": _preview(str(row.get("content") or ""), max_len=132),
                "category": str(row.get("category") or "unknown"),
                "level": str(row.get("level") or "unknown"),
                "confidence_score": float(row.get("confidence_score") or 0.0),
                "source_conversation_id": str(row.get("source_conversation_id") or ""),
                "updated_at": _to_dt(row.get("updated_at") or row.get("created_at")).isoformat(),
            }
        )
    return out


def _build_category_evolution(memories: list[dict], now: datetime) -> list[dict]:
    dates = _days_range(now, WINDOW_DAYS)
    daily: dict[str, Counter[str]] = {d: Counter() for d in dates}
    cutoff = now - timedelta(days=WINDOW_DAYS)

    categories = set(KNOWN_CATEGORIES)
    for row in memories:
        if row.get("status") == "archived":
            continue
        ts = _to_dt(row.get("updated_at") or row.get("created_at"), fallback=now)
        if ts < cutoff:
            continue
        day_key = ts.date().isoformat()
        if day_key not in daily:
            continue
        category = (row.get("category") or "unknown").strip().lower()
        categories.add(category)
        daily[day_key][category] += 1

    ordered_categories = sorted(categories)
    series = []
    for day in dates:
        entry: dict[str, Any] = {"date": day, "total": 0}
        for category in ordered_categories:
            value = int(daily[day].get(category, 0))
            entry[category] = value
            entry["total"] += value
        series.append(entry)
    return series


def _build_domain_activity(memories: list[dict], now: datetime) -> list[dict]:
    dates = _days_range(now, WINDOW_DAYS)
    daily: dict[str, Counter[str]] = {d: Counter() for d in dates}
    cutoff = now - timedelta(days=WINDOW_DAYS)

    for row in memories:
        if row.get("status") == "archived":
            continue
        ts = _to_dt(row.get("updated_at") or row.get("created_at"), fallback=now)
        if ts < cutoff:
            continue
        day_key = ts.date().isoformat()
        if day_key not in daily:
            continue
        domain = _domain_for_category(row.get("category") or "")
        daily[day_key][domain] += 1

    series = []
    for day in dates:
        code = int(daily[day].get("code", 0))
        business = int(daily[day].get("business", 0))
        personal = int(daily[day].get("personal", 0))
        casual = int(daily[day].get("casual", 0))
        series.append(
            {
                "date": day,
                "code": code,
                "business": business,
                "personal": personal,
                "casual": casual,
                "total": code + business + personal + casual,
            }
        )
    return series


def _build_summary(memories: list[dict], pending_conflicts: list[dict]) -> dict:
    active = [m for m in memories if m.get("status") != "archived"]
    levels = _build_level_counts(active)

    llm_counter: Counter[str] = Counter()
    for row in active:
        llm = (row.get("source_llm") or "unknown").strip() or "unknown"
        llm_counter[llm] += 1
    top_llm = llm_counter.most_common(1)

    conflicts_total = len(pending_conflicts)
    conflicts_resolved = sum(1 for c in pending_conflicts if (c.get("status") or "") == "resolved")
    conflict_rate = round((conflicts_resolved / conflicts_total) * 100, 1) if conflicts_total else 100.0

    return {
        "total_memories": len(active),
        "levels": levels,
        "conflicts_total": conflicts_total,
        "conflicts_resolved": conflicts_resolved,
        "conflict_resolution_rate": conflict_rate,
        "auto_suggestions_pending": len([m for m in memories if _is_auto_conversation_pending_memory(m)]),
        "most_active_llm": (
            {"name": top_llm[0][0], "writes": top_llm[0][1]} if top_llm else None
        ),
        "top_referenced_memories": _build_top_referenced(active, limit=5),
    }


def _build_analytics_payload(memories: list[dict], pending_conflicts: list[dict], now: Optional[datetime] = None) -> dict:
    now_utc = now or datetime.now(timezone.utc)
    return {
        "summary": _build_summary(memories, pending_conflicts),
        "category_evolution": _build_category_evolution(memories, now_utc),
        "domain_activity": _build_domain_activity(memories, now_utc),
        "recurrent_topics": _extract_recurrent_topics(memories, now_utc),
        "auto_memory_suggestions": _build_auto_memory_suggestions(memories, limit=8),
        "window_days": WINDOW_DAYS,
    }


def _heuristic_insights(analytics: dict) -> list[dict]:
    insights: list[dict] = []
    summary = analytics.get("summary", {})
    total = int(summary.get("total_memories") or 0)
    levels = summary.get("levels", {}) or {}
    recurrent = analytics.get("recurrent_topics", []) or []
    top_llm = summary.get("most_active_llm")

    if total == 0:
        return [
            {
                "title": "Memory base is still empty",
                "detail": "Start by importing conversations or writing 10-20 core memories to unlock meaningful trends.",
            },
            {
                "title": "No behavioral trend yet",
                "detail": "Insights become useful once at least a few days of memory activity are accumulated.",
            },
            {
                "title": "Setup recommendation",
                "detail": "Enable sync and keep conflict resolution active to improve data quality over time.",
            },
        ]

    dominant_level = max(levels.items(), key=lambda x: x[1])[0] if levels else "semantic"
    insights.append(
        {
            "title": f"{dominant_level.title()} memories dominate your base",
            "detail": f"{levels.get(dominant_level, 0)} of {total} active memories are {dominant_level}, showing where your memory system currently focuses.",
        }
    )

    conflict_rate = float(summary.get("conflict_resolution_rate") or 0.0)
    if conflict_rate < 65:
        insights.append(
            {
                "title": "Conflict backlog is building",
                "detail": f"Only {conflict_rate:.1f}% of conflicts are resolved. Clearing pending conflicts will improve memory consistency.",
            }
        )
    else:
        insights.append(
            {
                "title": "Conflict resolution is healthy",
                "detail": f"{conflict_rate:.1f}% of conflicts are resolved, indicating good memory curation quality.",
            }
        )

    if top_llm:
        insights.append(
            {
                "title": f"{top_llm.get('name', 'unknown')} is the most active writer",
                "detail": f"This client produced {top_llm.get('writes', 0)} memory writes and is shaping most of your memory graph evolution.",
            }
        )

    if recurrent:
        top_topic = recurrent[0]
        insights.append(
            {
                "title": f"Recurring topic: {top_topic.get('topic', 'n/a')}",
                "detail": f"This topic appears {top_topic.get('count', 0)} times in the last {analytics.get('window_days', WINDOW_DAYS)} days.",
            }
        )

    top_ref = (summary.get("top_referenced_memories") or [])[:1]
    if top_ref:
        insights.append(
            {
                "title": "One memory is heavily reused",
                "detail": f"'{top_ref[0].get('content_preview', '')}' is currently the most referenced memory ({top_ref[0].get('reference_count', 0)} uses).",
            }
        )

    return insights[:5]


def _extract_json_obj(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    fragment = text[start : end + 1]
    try:
        parsed = json.loads(fragment)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def _normalize_insight_items(items: Any) -> list[dict]:
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if isinstance(it, dict):
            title = str(it.get("title") or "").strip()
            detail = str(it.get("detail") or it.get("description") or "").strip()
            if title and detail:
                out.append({"title": title, "detail": detail})
        elif isinstance(it, str):
            line = it.strip()
            if line:
                out.append({"title": line[:60], "detail": line})
        if len(out) >= 5:
            break
    return out


def _build_llm_prompt(analytics: dict, heuristic: list[dict]) -> str:
    payload = {
        "summary": analytics.get("summary", {}),
        "recurrent_topics": analytics.get("recurrent_topics", [])[:8],
        "domain_activity_tail": (analytics.get("domain_activity", []) or [])[-7:],
        "category_evolution_tail": (analytics.get("category_evolution", []) or [])[-7:],
        "heuristic_baseline": heuristic,
    }
    return (
        "You are an analytics assistant. Generate 3 to 5 concise insights about this memory dashboard.\n"
        "Respond with STRICT JSON only in this shape: {\"insights\":[{\"title\":\"...\",\"detail\":\"...\"}]}.\n"
        "Each insight should be specific, actionable, and grounded in the data.\n"
        f"Data:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def _call_openai(prompt: str, runtime: dict) -> str:
    base = (runtime.get("api_base_url") or "https://api.openai.com/v1").rstrip("/")
    model = runtime.get("model") or "gpt-4o-mini"
    headers = {
        "Content-Type": "application/json",
    }
    if runtime.get("api_key"):
        headers["Authorization"] = f"Bearer {runtime.get('api_key')}"
    body = {
        "model": model,
        "temperature": 0.3,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
    }
    with httpx.Client(timeout=20.0) as client:
        res = client.post(f"{base}/chat/completions", headers=headers, json=body)
        if res.status_code >= 400:
            raise RuntimeError(f"OpenAI request failed ({res.status_code}): {res.text[:180]}")
        data = res.json()
    return (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )


def _call_anthropic(prompt: str, runtime: dict) -> str:
    base = (runtime.get("api_base_url") or "https://api.anthropic.com/v1").rstrip("/")
    model = runtime.get("model") or "claude-3-5-haiku-latest"
    headers = {
        "x-api-key": runtime.get("api_key") or "",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 500,
        "temperature": 0.3,
        "messages": [{"role": "user", "content": prompt}],
    }
    with httpx.Client(timeout=20.0) as client:
        res = client.post(f"{base}/messages", headers=headers, json=body)
        if res.status_code >= 400:
            raise RuntimeError(f"Anthropic request failed ({res.status_code}): {res.text[:180]}")
        data = res.json()

    content = data.get("content", [])
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    return "\n".join(parts)


def _call_ollama(prompt: str, runtime: dict) -> str:
    base = (runtime.get("api_base_url") or "http://127.0.0.1:11434").rstrip("/")
    model = runtime.get("model") or "llama3.2:3b"
    headers = {
        "Content-Type": "application/json",
    }
    if runtime.get("api_key"):
        headers["Authorization"] = f"Bearer {runtime.get('api_key')}"
    body = {
        "model": model,
        "prompt": f"Return valid JSON only.\n\n{prompt}",
        "stream": False,
        "options": {"temperature": 0.3},
    }
    with httpx.Client(timeout=60.0) as client:
        res = client.post(f"{base}/api/generate", headers=headers, json=body)
        if res.status_code >= 400:
            raise RuntimeError(f"Ollama request failed ({res.status_code}): {res.text[:180]}")
        data = res.json()
    return data.get("response", "")


def _resolve_runtime(insights_cfg: dict) -> dict:
    provider = _normalize_provider(insights_cfg.get("provider"))
    api_key = (insights_cfg.get("api_key") or "").strip()
    if not api_key:
        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        elif provider == "ollama":
            api_key = os.environ.get("OLLAMA_API_KEY", "")

    model = (insights_cfg.get("model") or "").strip()
    if not model:
        if provider == "openai":
            model = "gpt-4o-mini"
        elif provider == "anthropic":
            model = "claude-3-5-haiku-latest"
        else:
            model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

    api_base_url = (insights_cfg.get("api_base_url") or "").strip()
    if not api_base_url:
        if provider == "openai":
            api_base_url = os.environ.get("OPENAI_BASE_URL", "")
        elif provider == "anthropic":
            api_base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
        elif provider == "ollama":
            api_base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    return {
        "enabled": bool(insights_cfg.get("enabled", True)),
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "api_base_url": api_base_url,
    }


def _runtime_can_call_provider(runtime: dict) -> bool:
    provider = runtime.get("provider")
    if provider == "openai":
        return bool(runtime.get("api_key"))
    if provider == "anthropic":
        return bool(runtime.get("api_key"))
    if provider == "ollama":
        return bool(runtime.get("api_base_url")) and bool(runtime.get("model"))
    return False


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
    requested = str(requested_model or "").strip().lower()
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


def _preflight_ollama(runtime: dict):
    base = (runtime.get("api_base_url") or "http://127.0.0.1:11434").rstrip("/")
    model = str(runtime.get("model") or "").strip()
    with httpx.Client(timeout=4.0) as client:
        res = client.get(f"{base}/api/tags")
        if res.status_code >= 400:
            detail = ""
            try:
                payload = res.json()
                if isinstance(payload, dict):
                    detail = str(payload.get("error") or payload.get("message") or "").strip()
            except Exception:
                detail = (res.text or "").strip()
            suffix = f": {detail[:180]}" if detail else ""
            raise RuntimeError(f"Ollama preflight failed ({res.status_code}){suffix}")

        available = _extract_ollama_model_names(res.json())
        if model and not available:
            raise RuntimeError(
                f"Ollama has no local models installed. "
                f"Run 'ollama pull {model}' (or any model) first."
            )
        if model and available and not _ollama_model_available(model, available):
            preview = ", ".join(sorted(available)[:6])
            preview_suffix = f" Available: {preview}" if preview else ""
            raise RuntimeError(
                f"Ollama model '{model}' not found locally.{preview_suffix} "
                f"Run 'ollama pull {model}' or pick an installed model."
            )


def _generate_llm_insights(analytics: dict, runtime: dict, heuristic: list[dict]) -> list[dict]:
    if not runtime.get("enabled"):
        return heuristic
    if runtime.get("provider") not in SUPPORTED_PROVIDERS:
        return heuristic
    if not _runtime_can_call_provider(runtime):
        return heuristic

    if runtime.get("provider") == "ollama":
        _preflight_ollama(runtime)

    prompt = _build_llm_prompt(analytics, heuristic)
    provider = runtime.get("provider")
    if provider == "openai":
        text = _call_openai(prompt, runtime)
    elif provider == "anthropic":
        text = _call_anthropic(prompt, runtime)
    else:
        text = _call_ollama(prompt, runtime)

    parsed = _extract_json_obj(text)
    if not parsed:
        return heuristic
    items = _normalize_insight_items(parsed.get("insights"))
    return items if items else heuristic


def get_insights_config_public() -> dict:
    cfg = load_config(force_reload=True)
    insights_cfg = cfg.get("insights", {})
    public = {
        **insights_cfg,
        "provider": _normalize_provider(insights_cfg.get("provider")),
        "api_key": _masked(insights_cfg.get("api_key", "")),
    }
    return {
        "insights": public,
        "insights_cache": cfg.get("insights_cache", {}),
    }


def update_insights_config(partial: dict) -> dict:
    cfg = load_config(force_reload=True)
    current = cfg.get("insights", {})
    merged = {**current, **(partial or {})}

    api_key = merged.get("api_key")
    if isinstance(api_key, str) and current.get("api_key"):
        current_key = str(current.get("api_key"))
        if (api_key and set(api_key) == {"*"}) or api_key == _masked(current_key):
            merged["api_key"] = current_key

    for key in ("provider", "model", "api_base_url"):
        value = merged.get(key)
        if isinstance(value, str):
            merged[key] = value.strip()
    merged["provider"] = _normalize_provider(merged.get("provider"))
    if "enabled" in merged:
        merged["enabled"] = bool(merged.get("enabled"))
    if isinstance(merged.get("api_base_url"), str):
        merged["api_base_url"] = merged["api_base_url"].rstrip("/")

    cfg["insights"] = merged
    # Force regeneration on next dashboard request after config change.
    cache = cfg.get("insights_cache", {}) if isinstance(cfg.get("insights_cache"), dict) else {}
    cache["date"] = ""
    cache["insights"] = []
    cache["source"] = "none"
    cache["last_error"] = None
    cfg["insights_cache"] = cache
    save_config(copy.deepcopy(cfg))
    return get_insights_config_public()


def get_insights_dashboard() -> dict:
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    memories = _load_rows("memories")
    pending_conflicts = _load_rows("pending_conflicts")
    analytics = _build_analytics_payload(memories=memories, pending_conflicts=pending_conflicts, now=now)

    cfg = load_config(force_reload=True)
    cache = cfg.get("insights_cache", {}) if isinstance(cfg.get("insights_cache"), dict) else {}

    if cache.get("date") == today and isinstance(cache.get("insights"), list) and cache.get("insights"):
        insights = _normalize_insight_items(cache.get("insights"))
        return {
            "generated_at": cache.get("generated_at") or now.isoformat(),
            "source": cache.get("source") or "cache",
            "insights": insights,
            "analytics": analytics,
            "cache": {
                "date": cache.get("date"),
                "source": cache.get("source"),
                "last_error": cache.get("last_error"),
            },
        }

    heuristic = _heuristic_insights(analytics)
    runtime = _resolve_runtime(cfg.get("insights", {}))
    source = "heuristic"
    last_error: Optional[str] = None

    try:
        generated = _generate_llm_insights(analytics=analytics, runtime=runtime, heuristic=heuristic)
        if runtime.get("enabled") and runtime.get("provider") in SUPPORTED_PROVIDERS and _runtime_can_call_provider(runtime):
            source = f"llm:{runtime.get('provider')}"
        else:
            source = "heuristic"
        insights = generated
    except Exception as e:
        source = "heuristic"
        last_error = str(e)
        insights = heuristic

    cache_payload = {
        "date": today,
        "generated_at": now.isoformat(),
        "source": source,
        "insights": insights,
        "last_error": last_error,
    }
    cfg["insights_cache"] = cache_payload
    save_config(copy.deepcopy(cfg))

    return {
        "generated_at": cache_payload["generated_at"],
        "source": source,
        "insights": insights,
        "analytics": analytics,
        "cache": {
            "date": cache_payload["date"],
            "source": cache_payload["source"],
            "last_error": cache_payload["last_error"],
        },
    }
