from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import re
from typing import Any, Optional
import uuid

from backend.database.client import DATA_DIR, get_db
from backend.database.schema import MemoryGraphEdge
from backend.memory.conflicts import is_semantic_contradiction
from backend.memory.decay import parse_event_date

logger = logging.getLogger(__name__)

EDGE_TYPES = {
    "BELONGS_TO",
    "CONTRADICTS",
    "REINFORCES",
    "PRECEDES",
    "DEPENDS_ON",
    "INVOLVES_PERSON",
}

_COMMON_NAMES = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}

_TOPIC_STOPWORDS = {
    "the",
    "and",
    "with",
    "from",
    "that",
    "this",
    "user",
    "users",
    "memory",
    "memories",
    "project",
    "projects",
    "using",
    "used",
    "will",
    "shall",
    "pour",
    "avec",
    "dans",
    "les",
    "des",
    "une",
}


def _escape_cypher(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _to_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _extract_people(content: str) -> set[str]:
    names = set()
    for token in re.findall(r"\b[A-Z][a-z]{2,}\b", content):
        lowered = token.lower()
        if lowered in _COMMON_NAMES:
            continue
        names.add(token)
    return names


def _topic_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9_\-]{2,}", str(text or "").lower())
    out = set()
    for token in tokens:
        if len(token) < 4:
            continue
        if token in _TOPIC_STOPWORDS:
            continue
        out.add(token)
    return out


def _build_topic_clusters(memory_nodes: list[dict], limit: int = 8) -> list[dict]:
    token_to_ids: dict[str, list[str]] = {}
    for node in memory_nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        for token in _topic_tokens(str(node.get("content_preview") or "")):
            token_to_ids.setdefault(token, []).append(node_id)

    ranked = sorted(
        ((token, ids) for token, ids in token_to_ids.items() if len(ids) >= 2),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    out = []
    for token, ids in ranked[: max(1, min(limit, 20))]:
        unique_ids = list(dict.fromkeys(ids))
        out.append(
            {
                "topic": token,
                "count": len(unique_ids),
                "memory_ids": unique_ids[:12],
            }
        )
    return out


class _KuzuClient:
    def __init__(self):
        self._attempted = False
        self._conn = None

    def _ensure(self):
        if self._attempted:
            return
        self._attempted = True
        try:
            import kuzu

            path = os.path.join(DATA_DIR, "kuzu_graph")
            os.makedirs(path, exist_ok=True)
            db = kuzu.Database(path)
            conn = kuzu.Connection(db)
            conn.execute("CREATE NODE TABLE IF NOT EXISTS Memory(id STRING, content_preview STRING, PRIMARY KEY(id));")
            for edge_type in EDGE_TYPES:
                conn.execute(
                    f"CREATE REL TABLE IF NOT EXISTS {edge_type}(FROM Memory TO Memory, score DOUBLE, created_at STRING);"
                )
            self._conn = conn
            logger.info("Kuzu knowledge-graph backend initialized")
        except Exception as e:
            logger.warning(f"Kuzu unavailable; graph persistence will fallback to LanceDB edges only: {e}")

    def upsert_memory(self, memory_id: str, content_preview: str):
        self._ensure()
        if not self._conn:
            return
        mid = _escape_cypher(memory_id)
        preview = _escape_cypher(content_preview)
        try:
            self._conn.execute(
                f"MERGE (m:Memory {{id: '{mid}'}}) "
                f"SET m.content_preview = '{preview}'"
            )
        except Exception as e:
            logger.warning(f"Kuzu upsert_memory failed: {e}")

    def add_edge(self, source: str, target: str, edge_type: str, score: float, created_at: datetime):
        self._ensure()
        if not self._conn:
            return
        if edge_type not in EDGE_TYPES or source == target:
            return
        src = _escape_cypher(source)
        dst = _escape_cypher(target)
        ts = _escape_cypher(created_at.isoformat())
        try:
            self._conn.execute(
                f"MATCH (a:Memory {{id: '{src}'}}), (b:Memory {{id: '{dst}'}}) "
                f"CREATE (a)-[:{edge_type} {{score: {float(score):.4f}, created_at: '{ts}'}}]->(b)"
            )
        except Exception as e:
            logger.warning(f"Kuzu add_edge failed: {e}")


_kuzu_client = _KuzuClient()


def _normalize_filter_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if not v or v.lower() in ("all", "any", "*"):
        return None
    return v


def _infer_edges_for_memory(new_memory: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    new_id = new_memory["id"]
    new_content = new_memory.get("content", "")
    new_category = new_memory.get("category")
    new_event = new_memory.get("event_date") or parse_event_date(new_content, now=now)
    new_people = _extract_people(new_content)
    depends_on_signal = bool(re.search(r"\b(depends on|requires|after)\b", new_content.lower()))

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for candidate in candidates:
        target_id = candidate.get("id")
        if not target_id or target_id == new_id:
            continue
        score = max(0.0, float(1 - candidate.get("_distance", 1.0)))
        if score < 0.65:
            continue

        candidate_content = candidate.get("content", "")
        candidate_event = candidate.get("event_date") or parse_event_date(candidate_content, now=now)
        candidate_people = _extract_people(candidate_content)

        def _append(src: str, dst: str, edge_type: str, edge_score: float):
            key = (src, dst, edge_type)
            if key in seen:
                return
            seen.add(key)
            edges.append(
                {
                    "id": str(uuid.uuid4()),
                    "source_memory_id": src,
                    "target_memory_id": dst,
                    "edge_type": edge_type,
                    "score": round(max(0.0, min(edge_score, 1.0)), 4),
                    "created_at": now,
                }
            )

        if candidate.get("category") == new_category and score >= 0.72:
            _append(new_id, target_id, "BELONGS_TO", score)

        if is_semantic_contradiction(candidate_content, new_content):
            _append(new_id, target_id, "CONTRADICTS", score)
        elif score >= 0.9:
            _append(new_id, target_id, "REINFORCES", score)

        if new_event and candidate_event:
            new_dt = _to_utc(new_event)
            cand_dt = _to_utc(candidate_event)
            if cand_dt < new_dt:
                _append(target_id, new_id, "PRECEDES", 0.85)
            elif new_dt < cand_dt:
                _append(new_id, target_id, "PRECEDES", 0.85)

        if depends_on_signal and score >= 0.75:
            _append(new_id, target_id, "DEPENDS_ON", score)

        if new_people and candidate_people and new_people.intersection(candidate_people):
            _append(new_id, target_id, "INVOLVES_PERSON", 0.8)

    return edges


def update_graph_on_memory_create(new_memory: dict[str, Any], candidates: list[dict[str, Any]], db=None) -> int:
    db = db or get_db()
    edges_tbl = db.open_table("memory_graph_edges")

    _kuzu_client.upsert_memory(new_memory["id"], new_memory.get("content", "")[:180])
    for candidate in candidates:
        if candidate.get("id"):
            _kuzu_client.upsert_memory(candidate["id"], candidate.get("content", "")[:180])

    edges = _infer_edges_for_memory(new_memory, candidates)
    if not edges:
        return 0

    edge_objects = [MemoryGraphEdge(**edge) for edge in edges]
    edges_tbl.add(edge_objects)
    for edge in edges:
        _kuzu_client.add_edge(
            edge["source_memory_id"],
            edge["target_memory_id"],
            edge["edge_type"],
            edge["score"],
            edge["created_at"],
        )
    return len(edges)


def sync_memory_node(memory_id: str, content: str):
    _kuzu_client.upsert_memory(memory_id, content[:180])


async def memory_graph_search(start_memory_id: str, depth: int = 2) -> dict[str, Any]:
    db = get_db()
    if "memory_graph_edges" not in db.table_names() or "memories" not in db.table_names():
        return {"start_memory_id": start_memory_id, "depth": depth, "nodes": [], "edges": []}

    depth = max(1, min(int(depth), 5))
    edge_tbl = db.open_table("memory_graph_edges")
    mem_tbl = db.open_table("memories")

    all_edges = edge_tbl.search().limit(200000).to_list()

    visited = {start_memory_id}
    frontier = {start_memory_id}
    selected_edges: list[dict[str, Any]] = []
    selected_edge_ids = set()

    for _ in range(depth):
        next_frontier = set()
        for edge in all_edges:
            src = edge.get("source_memory_id")
            dst = edge.get("target_memory_id")
            if src in frontier or dst in frontier:
                edge_id = edge.get("id")
                if edge_id not in selected_edge_ids:
                    selected_edge_ids.add(edge_id)
                    selected_edges.append(edge)
                if src and src not in visited:
                    next_frontier.add(src)
                if dst and dst not in visited:
                    next_frontier.add(dst)
        visited.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break

    # Always include start node if it exists.
    node_ids = set(visited)
    nodes = []
    memories = mem_tbl.search().where("status != 'archived'").limit(200000).to_list()
    memory_by_id = {m.get("id"): m for m in memories}
    if start_memory_id in memory_by_id:
        node_ids.add(start_memory_id)

    for node_id in node_ids:
        mem = memory_by_id.get(node_id)
        if not mem:
            continue
        nodes.append(
            {
                "id": mem["id"],
                "content_preview": mem.get("content", "")[:180],
                "category": mem.get("category"),
                "level": mem.get("level"),
            }
        )

    edges = [
        {
            "id": edge.get("id"),
            "source": edge.get("source_memory_id"),
            "target": edge.get("target_memory_id"),
            "type": edge.get("edge_type"),
            "score": edge.get("score", 0.0),
        }
        for edge in selected_edges
        if edge.get("source_memory_id") in node_ids and edge.get("target_memory_id") in node_ids
    ]

    return {
        "start_memory_id": start_memory_id,
        "depth": depth,
        "nodes": nodes,
        "edges": edges,
    }


async def memory_graph_overview(
    depth: int = 2,
    center_memory_id: Optional[str] = None,
    category: Optional[str] = None,
    edge_type: Optional[str] = None,
    max_nodes: int = 220,
    include_conversations: bool = False,
) -> dict[str, Any]:
    db = get_db()
    if "memory_graph_edges" not in db.table_names() or "memories" not in db.table_names():
        return {
            "start_memory_id": center_memory_id,
            "depth": depth,
            "nodes": [],
            "edges": [],
            "conversation_links": [],
            "topic_clusters": [],
            "timeline": [],
        }

    depth = max(1, min(int(depth), 5))
    max_nodes = max(20, min(int(max_nodes), 800))
    category = _normalize_filter_value(category)
    edge_type = _normalize_filter_value(edge_type)
    if edge_type and edge_type not in EDGE_TYPES:
        edge_type = None

    edge_tbl = db.open_table("memory_graph_edges")
    mem_tbl = db.open_table("memories")
    memories = mem_tbl.search().where("status != 'archived'").limit(200000).to_list()
    if category:
        memories = [m for m in memories if m.get("category") == category]

    memory_by_id = {m.get("id"): m for m in memories if m.get("id")}
    allowed_ids = set(memory_by_id.keys())
    if not allowed_ids:
        return {
            "start_memory_id": center_memory_id,
            "depth": depth,
            "nodes": [],
            "edges": [],
            "conversation_links": [],
            "topic_clusters": [],
            "timeline": [],
        }

    conversations_by_id: dict[str, dict] = {}
    if include_conversations and "conversations" in db.table_names():
        try:
            conv_rows = db.open_table("conversations").search().where("status != 'deleted'").limit(200000).to_list()
            for row in conv_rows:
                cid = str(row.get("id") or "").strip()
                if cid:
                    conversations_by_id[cid] = row
        except Exception:
            conversations_by_id = {}

    all_edges = edge_tbl.search().limit(200000).to_list()
    filtered_edges = []
    for edge in all_edges:
        src = edge.get("source_memory_id")
        dst = edge.get("target_memory_id")
        if not src or not dst:
            continue
        if src not in allowed_ids or dst not in allowed_ids:
            continue
        if edge_type and edge.get("edge_type") != edge_type:
            continue
        filtered_edges.append(edge)

    def _build_payload(node_ids: set[str], selected_edges: list[dict[str, Any]]) -> dict[str, Any]:
        base_nodes = [
            {
                "id": memory_by_id[nid]["id"],
                "content_preview": memory_by_id[nid].get("content", "")[:180],
                "category": memory_by_id[nid].get("category"),
                "level": memory_by_id[nid].get("level"),
                "node_type": "memory",
            }
            for nid in node_ids
            if nid in memory_by_id
        ]
        base_edges = [
            {
                "id": edge.get("id"),
                "source": edge.get("source_memory_id"),
                "target": edge.get("target_memory_id"),
                "type": edge.get("edge_type"),
                "score": edge.get("score", 0.0),
            }
            for edge in selected_edges
            if edge.get("source_memory_id") in node_ids and edge.get("target_memory_id") in node_ids
        ]

        conversation_links: list[dict[str, Any]] = []
        conversation_nodes: list[dict[str, Any]] = []
        conversation_edges: list[dict[str, Any]] = []
        seen_conv_nodes = set()
        seen_conv_edges = set()
        if include_conversations and conversations_by_id:
            for memory_id in node_ids:
                mem = memory_by_id.get(memory_id)
                if not mem:
                    continue
                conv_id = str(mem.get("source_conversation_id") or "").strip()
                if not conv_id:
                    continue
                conv = conversations_by_id.get(conv_id)
                if not conv:
                    continue
                conversation_links.append(
                    {
                        "conversation_id": conv_id,
                        "memory_id": memory_id,
                        "conversation_title": str(conv.get("title") or "Untitled conversation"),
                        "source_llm": str(conv.get("source_llm") or ""),
                        "started_at": _to_utc(conv.get("started_at")).isoformat(),
                    }
                )

                conv_node_id = f"conversation:{conv_id}"
                if conv_node_id not in seen_conv_nodes:
                    seen_conv_nodes.add(conv_node_id)
                    conversation_nodes.append(
                        {
                            "id": conv_node_id,
                            "content_preview": str(conv.get("title") or "Conversation")[:180],
                            "category": "conversation",
                            "level": "context",
                            "node_type": "conversation",
                            "source_llm": str(conv.get("source_llm") or ""),
                            "started_at": _to_utc(conv.get("started_at")).isoformat(),
                        }
                    )

                synthetic_id = f"conv-link:{conv_id}:{memory_id}"
                if synthetic_id not in seen_conv_edges:
                    seen_conv_edges.add(synthetic_id)
                    conversation_edges.append(
                        {
                            "id": synthetic_id,
                            "source": conv_node_id,
                            "target": memory_id,
                            "type": "CONVERSATION_CONTEXT",
                            "score": 0.92,
                        }
                    )

        memory_nodes_for_clusters = [n for n in base_nodes if str(n.get("node_type") or "") == "memory"]
        topic_clusters = _build_topic_clusters(memory_nodes_for_clusters, limit=8)

        timeline_map: dict[str, dict[str, Any]] = {}
        for nid in node_ids:
            mem = memory_by_id.get(nid)
            if not mem:
                continue
            ts = _to_utc(mem.get("created_at") or mem.get("updated_at"))
            day = ts.date().isoformat()
            row = timeline_map.setdefault(day, {"date": day, "memories": 0, "conversations": 0, "links": 0})
            row["memories"] += 1

        seen_conversations = set()
        for link in conversation_links:
            row = timeline_map.setdefault(
                str(link.get("started_at", ""))[:10],
                {"date": str(link.get("started_at", ""))[:10], "memories": 0, "conversations": 0, "links": 0},
            )
            row["links"] += 1
            conv_id = str(link.get("conversation_id") or "")
            if conv_id and conv_id not in seen_conversations:
                seen_conversations.add(conv_id)
                row["conversations"] += 1

        timeline = sorted(timeline_map.values(), key=lambda item: str(item.get("date") or ""))

        nodes = list(base_nodes)
        edges = list(base_edges)
        if include_conversations:
            nodes.extend(conversation_nodes[:200])
            edges.extend(conversation_edges[:400])

        return {
            "start_memory_id": center_memory_id,
            "depth": depth,
            "nodes": nodes,
            "edges": edges,
            "conversation_links": conversation_links[:500],
            "topic_clusters": topic_clusters,
            "timeline": timeline[-60:],
        }

    # If a center memory is provided, return a contextual BFS from that center.
    if center_memory_id and center_memory_id in allowed_ids:
        visited = {center_memory_id}
        frontier = {center_memory_id}
        selected_edges: list[dict[str, Any]] = []
        selected_edge_ids = set()

        for _ in range(depth):
            next_frontier = set()
            for edge in filtered_edges:
                src = edge.get("source_memory_id")
                dst = edge.get("target_memory_id")
                if src in frontier or dst in frontier:
                    edge_id = edge.get("id")
                    if edge_id not in selected_edge_ids:
                        selected_edge_ids.add(edge_id)
                        selected_edges.append(edge)
                    if src and src not in visited:
                        next_frontier.add(src)
                    if dst and dst not in visited:
                        next_frontier.add(dst)
            visited.update(next_frontier)
            frontier = next_frontier
            if not frontier or len(visited) >= max_nodes:
                break

        node_ids = set(list(visited)[:max_nodes])
        return _build_payload(node_ids=node_ids, selected_edges=selected_edges)

    # Global overview: highest-scoring edges first, bounded by max_nodes.
    filtered_edges.sort(key=lambda e: float(e.get("score", 0.0)), reverse=True)
    selected_edges = []
    node_ids: set[str] = set()
    for edge in filtered_edges:
        src = edge.get("source_memory_id")
        dst = edge.get("target_memory_id")
        if not src or not dst:
            continue
        projected_node_count = len(node_ids.union({src, dst}))
        if projected_node_count > max_nodes:
            continue
        selected_edges.append(edge)
        node_ids.update([src, dst])
        if len(node_ids) >= max_nodes:
            break

    # If graph is sparse, include top memories as isolated nodes.
    if len(node_ids) < min(25, max_nodes):
        by_importance = sorted(memories, key=lambda m: float(m.get("importance_score", 0.0)), reverse=True)
        for mem in by_importance:
            mid = mem.get("id")
            if not mid:
                continue
            node_ids.add(mid)
            if len(node_ids) >= min(max_nodes, 80):
                break

    return _build_payload(node_ids=node_ids, selected_edges=selected_edges)


async def delete_memory_graph_edges(memory_id: str, db=None) -> dict:
    """Remove all graph edges where the given memory is source or target."""
    try:
        if db is None:
            db = get_db()
        if "memory_graph_edges" not in db.table_names():
            return {"deleted": 0}
        tbl = db.open_table("memory_graph_edges")
        safe_id = re.sub(r"[^0-9a-f\-]", "", str(memory_id or "").lower())
        before = tbl.count_rows()
        tbl.delete(f"source_memory_id = '{safe_id}' OR target_memory_id = '{safe_id}'")
        after = tbl.count_rows()
        deleted = max(0, before - after)
        logger.info(f"Deleted {deleted} graph edge(s) for memory {safe_id}")
        return {"deleted": deleted}
    except Exception as e:
        logger.warning(f"Failed to delete graph edges for memory {memory_id}: {e}")
        return {"deleted": 0, "error": str(e)}
