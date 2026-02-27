from datetime import datetime, timedelta, timezone

from backend.insights import service


def _sample_memory(**overrides):
    now = datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc)
    base = {
        "id": "m1",
        "content": "Julien builds FastAPI services and TypeScript tools for product analytics.",
        "level": "semantic",
        "category": "skills",
        "status": "active",
        "source_llm": "claude",
        "reference_count": 5,
        "importance_score": 0.8,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return base


def test_build_analytics_payload_shapes_expected_metrics():
    now = datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc)
    memories = [
        _sample_memory(id="m1", level="semantic", category="skills", source_llm="claude", reference_count=8),
        _sample_memory(
            id="m2",
            level="episodic",
            category="history",
            source_llm="chatgpt",
            reference_count=2,
            content="Quarterly roadmap review and revenue planning completed.",
            updated_at=now - timedelta(days=2),
        ),
        _sample_memory(
            id="m3",
            level="working",
            category="working",
            source_llm="claude",
            reference_count=1,
            content="Temporary note for deployment checks today.",
            updated_at=now - timedelta(days=1),
        ),
    ]
    pending_conflicts = [
        {"id": "c1", "status": "resolved"},
        {"id": "c2", "status": "pending"},
    ]

    payload = service._build_analytics_payload(memories=memories, pending_conflicts=pending_conflicts, now=now)

    summary = payload["summary"]
    assert summary["total_memories"] == 3
    assert summary["levels"]["semantic"] == 1
    assert summary["levels"]["episodic"] == 1
    assert summary["levels"]["working"] == 1
    assert summary["most_active_llm"]["name"] == "claude"
    assert summary["most_active_llm"]["writes"] == 2
    assert summary["conflict_resolution_rate"] == 50.0
    assert payload["category_evolution"]
    assert payload["domain_activity"]
    assert isinstance(payload["recurrent_topics"], list)


def test_get_insights_dashboard_uses_daily_cache(monkeypatch):
    state = {
        "insights": {
            "enabled": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-test",
            "api_base_url": "",
        },
        "insights_cache": {
            "date": "",
            "generated_at": None,
            "source": "none",
            "insights": [],
            "last_error": None,
        },
    }

    calls = {"llm": 0}

    def _load_config(force_reload=False):
        return state

    def _save_config(new_cfg):
        state.clear()
        state.update(new_cfg)

    def _load_rows(table_name: str, limit: int = 200000):
        if table_name == "memories":
            return [_sample_memory(id="m1")]
        if table_name == "pending_conflicts":
            return []
        return []

    def _fake_generate(analytics, runtime, heuristic):
        calls["llm"] += 1
        return [{"title": "LLM insight", "detail": "Generated from model."}]

    monkeypatch.setattr(service, "load_config", _load_config)
    monkeypatch.setattr(service, "save_config", _save_config)
    monkeypatch.setattr(service, "_load_rows", _load_rows)
    monkeypatch.setattr(service, "_generate_llm_insights", _fake_generate)

    first = service.get_insights_dashboard()
    second = service.get_insights_dashboard()

    assert calls["llm"] == 1
    assert first["insights"][0]["title"] == "LLM insight"
    assert second["insights"][0]["title"] == "LLM insight"


def test_update_insights_config_preserves_masked_api_key(monkeypatch):
    state = {
        "insights": {
            "enabled": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-real-key",
            "api_base_url": "",
        },
        "insights_cache": {
            "date": "",
            "generated_at": None,
            "source": "none",
            "insights": [],
            "last_error": None,
        },
    }

    def _load_config(force_reload=False):
        return state

    def _save_config(new_cfg):
        state.clear()
        state.update(new_cfg)

    monkeypatch.setattr(service, "load_config", _load_config)
    monkeypatch.setattr(service, "save_config", _save_config)

    result = service.update_insights_config(
        {
            "provider": "Anthropic",
            "api_key": "********",
            "model": "claude-3-5-haiku-latest",
        }
    )

    assert state["insights"]["provider"] == "anthropic"
    assert state["insights"]["api_key"] == "sk-real-key"
    assert result["insights"]["api_key"].startswith("sk")


def test_update_insights_config_preserves_pretty_masked_api_key(monkeypatch):
    state = {
        "insights": {
            "enabled": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-super-secret-key",
            "api_base_url": "",
        },
        "insights_cache": {
            "date": "",
            "generated_at": None,
            "source": "none",
            "insights": [],
            "last_error": None,
        },
    }

    def _load_config(force_reload=False):
        return state

    def _save_config(new_cfg):
        state.clear()
        state.update(new_cfg)

    monkeypatch.setattr(service, "load_config", _load_config)
    monkeypatch.setattr(service, "save_config", _save_config)

    masked = service.get_insights_config_public()["insights"]["api_key"]
    service.update_insights_config({"api_key": masked})
    assert state["insights"]["api_key"] == "sk-super-secret-key"


def test_resolve_runtime_defaults_for_ollama(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    runtime = service._resolve_runtime({"provider": "ollama", "model": "", "api_base_url": "", "api_key": ""})

    assert runtime["provider"] == "ollama"
    assert runtime["model"] == "llama3.2:3b"
    assert runtime["api_base_url"] == "http://127.0.0.1:11434"
    assert runtime["api_key"] == ""


def test_generate_llm_insights_ollama_without_api_key(monkeypatch):
    runtime = {
        "enabled": True,
        "provider": "ollama",
        "api_key": "",
        "model": "llama3.2:3b",
        "api_base_url": "http://127.0.0.1:11434",
    }
    analytics = {"summary": {}, "recurrent_topics": [], "domain_activity": [], "category_evolution": [], "window_days": 30}
    heuristic = [{"title": "fallback", "detail": "fallback"}]

    monkeypatch.setattr(
        service,
        "_call_ollama",
        lambda prompt, runtime: '{"insights":[{"title":"Local insight","detail":"Generated by ollama."}]}',
    )
    monkeypatch.setattr(service, "_preflight_ollama", lambda runtime: None)

    out = service._generate_llm_insights(analytics=analytics, runtime=runtime, heuristic=heuristic)
    assert out[0]["title"] == "Local insight"
