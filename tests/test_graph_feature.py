from backend.memory.graph_layer import _infer_edges_for_memory


def _edge_types(edges):
    return {e["edge_type"] for e in edges}


def test_infer_reinforces_and_belongs_to_edges():
    new_memory = {
        "id": "m-new",
        "content": "Julien uses FastAPI for Python backend services.",
        "category": "skills",
        "event_date": None,
    }
    candidates = [
        {
            "id": "m-existing",
            "content": "Julien uses FastAPI in Python APIs.",
            "category": "skills",
            "_distance": 0.05,
        }
    ]

    edges = _infer_edges_for_memory(new_memory, candidates)
    types = _edge_types(edges)
    assert "BELONGS_TO" in types
    assert "REINFORCES" in types


def test_infer_contradicts_edge():
    new_memory = {
        "id": "m-new",
        "content": "Julien does not prefer Python for backend services.",
        "category": "preferences",
        "event_date": None,
    }
    candidates = [
        {
            "id": "m-existing",
            "content": "Julien prefers Python for backend services.",
            "category": "preferences",
            "_distance": 0.1,
        }
    ]

    edges = _infer_edges_for_memory(new_memory, candidates)
    assert "CONTRADICTS" in _edge_types(edges)


def test_infer_precedes_edge_from_dates():
    new_memory = {
        "id": "m-new",
        "content": "Release scheduled on 2026-03-01",
        "category": "projects",
        "event_date": None,
    }
    candidates = [
        {
            "id": "m-existing",
            "content": "Design review happened on 2026-02-15",
            "category": "projects",
            "_distance": 0.2,
            "event_date": None,
        }
    ]

    edges = _infer_edges_for_memory(new_memory, candidates)
    precedes = [e for e in edges if e["edge_type"] == "PRECEDES"]
    assert precedes
    assert precedes[0]["source_memory_id"] == "m-existing"
    assert precedes[0]["target_memory_id"] == "m-new"
