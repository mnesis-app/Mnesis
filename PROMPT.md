You are an expert software architect specializing in Electron applications,
MCP (Model Context Protocol), Python backend systems, LanceDB, and developer
tooling designed for non-technical end users.

---

## Project Vision

Mnesis is a local desktop application (Mac & Windows) that acts as the
universal, central memory layer for the user across all their LLMs.

The goal: the user opens ChatGPT Desktop, then Claude Desktop, then Gemini —
each already knows their entire life, projects, and preferences, without
re-explaining anything. No manual action. No shortcuts. No extra cost.
Everything works with the user's existing LLM apps.

This is NOT a chatbot. NOT a proxy. NOT an LLM.
It is pure memory infrastructure — an external persistent brain
that all LLMs can query and feed via MCP.

---

## Architectural Philosophy: Three Strictly Separated Layers

### Layer 1 — Storage (LanceDB)
Receives, stores, indexes. Makes NO business logic decisions.
All logic about "what to store" comes from outside.

### Layer 2 — Intelligence (System Prompt + LLM)
The LLM is the sole actor deciding what to memorize, when to read,
what to inject. Mnesis never judges content — it executes.
The system prompt is the real product. It deserves as much care as code.

### Layer 3 — Interface (Electron)
Automatically configures all LLM clients detected on the machine.
Presents data to the user. Handles onboarding, conflict resolution,
native notifications. Grants the server necessary system permissions.

These three layers evolve independently. A system prompt change does not
touch Storage. A UI change does not touch Intelligence.

---

## Definitive Tech Stack (no alternatives — use exactly this)

| Component             | Technology                           | Reason                                         |
|-----------------------|--------------------------------------|------------------------------------------------|
| Desktop shell         | Electron (latest stable)             | Full system access, native .dmg/.exe           |
| Python bundling       | PyInstaller (embedded in app)        | Zero Python dependency on user machine         |
| Backend               | FastAPI (Python, embedded)           | REST API + MCP HTTP/SSE transport              |
| MCP framework         | FastMCP (Python)                     | Most mature MCP SDK, minimal boilerplate       |
| MCP stdio bridge      | mcp_stdio_bridge.py (custom, thin)   | Wraps HTTP server for stdio clients            |
| Database              | LanceDB (embedded)                   | Unified vector search + structured data, Rust  |
| Embeddings            | sentence-transformers bge-small-en   | Offline, fast, better retrieval than MiniLM    |
| UI                    | Vite + React + TailwindCSS + shadcn  | Modern stack, static build, no SSR             |
| React state           | Zustand (global) + React Query (server) | Zustand for UI state, React Query for API   |
| Streaming JSON parser | ijson                                | Memory-safe parsing of large import files      |
| Packaging             | uv (Python) + electron-builder       | Fast, modern, native .dmg/.exe output          |
| Config                | YAML (config.yaml)                   | Human-readable, manually editable              |
| DB migrations         | Custom versioning (simple Python)    | Lightweight, no heavy external dependency      |
| Optional local LLM    | Ollama (auto-detected)               | Classification at import if available          |

Do NOT use ChromaDB. Do NOT use separate SQLite. Do NOT use Next.js.
Do NOT use Jinja2. Do NOT use Redux. The stack is final.

---

## Critical: MCP Transport Architecture

### The stdio vs HTTP problem

Claude Desktop uses stdio MCP transport: it spawns a process and communicates
via stdin/stdout. Electron ALSO spawns the FastAPI backend as its subprocess.
A single process cannot have two parents. This conflict must be resolved cleanly.

### Solution: HTTP/SSE as the single transport, with a stdio bridge

The FastAPI backend runs as Electron's subprocess, serving MCP over HTTP/SSE
on port {MCP_PORT}. It is the single source of truth and is always running.

For Claude Desktop (which requires stdio), a thin bridge process is used:

**`backend/mcp_stdio_bridge.py`** — spawned by Claude Desktop, bridges stdio ↔ HTTP:
```python
#!/usr/bin/env python3
"""
Thin stdio bridge for Claude Desktop.
Claude Desktop spawns this process via its claude_desktop_config.json.
This process reads MCP messages from stdin and forwards them to the
Mnesis HTTP MCP server, then writes responses back to stdout.
It does NOT start a new server — it connects to the already-running one.
"""
import sys, json, httpx, asyncio

MCP_HTTP_URL = "http://localhost:7861"  # Read from env var at runtime
API_KEY = ""  # Read from env var at runtime

async def bridge():
    async with httpx.AsyncClient() as client:
        for line in sys.stdin:
            msg = json.loads(line.strip())
            resp = await client.post(
                f"{MCP_HTTP_URL}/mcp",
                json=msg,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            sys.stdout.write(resp.text + "\n")
            sys.stdout.flush()

asyncio.run(bridge())
```

Claude Desktop config points to this bridge:
```json
{
  "mcpServers": {
    "mnesis": {
      "command": "/path/to/mcp_stdio_bridge",
      "env": {
        "MNESIS_MCP_URL": "http://localhost:7861",
        "MNESIS_API_KEY": "{{API_KEY}}"
      }
    }
  }
}
```

The bridge is also compiled by PyInstaller into a standalone executable
(bundled inside the Electron app alongside the main backend).

All other clients (Cursor, Windsurf, ChatGPT when available) connect
directly via HTTP/SSE — no bridge needed.

### Transport summary

| Client         | Transport      | Mechanism                              |
|----------------|----------------|----------------------------------------|
| Claude Desktop | stdio          | mcp_stdio_bridge.py → HTTP/SSE         |
| Cursor         | HTTP/SSE       | Direct to MCP port                     |
| Windsurf       | HTTP/SSE       | Direct to MCP port                     |
| ChatGPT        | HTTP/SSE       | Direct (when MCP available)            |
| Ollama         | HTTP/SSE       | Direct                                 |
| Any MCP client | HTTP/SSE       | Direct                                 |

---

## Critical: Python Bundling Strategy

The user must NEVER need to install Python, pip, or any dependency.

### Build process
1. PyInstaller compiles the main backend:
   `pyinstaller --onedir --name mnesis-backend backend/main.py`
2. PyInstaller compiles the stdio bridge:
   `pyinstaller --onedir --name mcp-stdio-bridge backend/mcp_stdio_bridge.py`
3. Both `dist/` folders included in Electron bundle via `extraResources`
4. Electron locates executables:
   ```javascript
   const backendExe = path.join(
     process.resourcesPath, 'mnesis-backend',
     process.platform === 'win32' ? 'mnesis-backend.exe' : 'mnesis-backend'
   )
   const bridgeExe = path.join(
     process.resourcesPath, 'mcp-stdio-bridge',
     process.platform === 'win32' ? 'mcp-stdio-bridge.exe' : 'mcp-stdio-bridge'
   )
   ```

### Port management
Ports 7860 (REST) and 7861 (MCP). On conflict, try +1 to +10 then error dialog.
```javascript
async function findAvailablePort(preferred) {
  for (let port = preferred; port <= preferred + 10; port++) {
    if (await isPortAvailable(port)) return port
  }
  throw new Error(`No available port found starting from ${preferred}`)
}
```
Selected ports passed as env vars to Python subprocess.
All internal references use dynamically selected ports — never hardcoded.

### Subprocess health management
Poll `GET /health` every 500ms after spawn. Timeout: 30 seconds.
Health endpoint returns `model_ready: true` only AFTER the embedding model
is fully loaded into memory (not just the file existing on disk).
If not ready in 30s → show error dialog with path to log file.
If subprocess crashes during use → auto-restart ×3 → then native notification.
Stdout/stderr written to:
- Mac: `~/Library/Logs/Mnesis/backend.log`
- Windows: `%APPDATA%\Mnesis\Logs\backend.log`

### Embedding model singleton
The bge-small-en-v1.5 model is loaded ONCE at FastAPI startup and held
in memory as a module-level singleton:
```python
# backend/memory/embedder.py
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer('BAAI/bge-small-en-v1.5')
    return _model

def embed(text: str) -> list[float]:
    return get_model().encode(text, normalize_embeddings=True).tolist()

def embed_batch(texts: list[str]) -> list[list[float]]:
    return get_model().encode(texts, normalize_embeddings=True, batch_size=32).tolist()
```
`/health` returns `model_ready: false` until `get_model()` has been called
successfully. Load is triggered at FastAPI startup event, before serving requests.

---

## Critical: First Launch & Embedding Model Download

The bge-small-en-v1.5 model is ~130MB. Downloaded once, then 100% offline.

### Download flow
1. At startup, check if model exists in `data/models/bge-small-en-v1.5/`
2. If missing: show a dedicated "First Setup" screen (not the main UI):
   - Progress bar: percentage + MB downloaded/total + estimated time
   - "One-time setup. Mnesis is 100% offline after this."
3. Resumable download via HTTP Range requests:
   - Save partial to `data/models/.partial`
   - Rename to final path on completion
4. Verify via SHA-256 checksum after download
5. On failure: retry button + option to place model manually (advanced)
6. Main UI appears only after successful verification

---

## Critical: Concurrent Write Safety

Multiple LLM clients may call `memory_write()` simultaneously.
LanceDB handles concurrent reads safely but concurrent writes can cause
data corruption. All writes go through a single asyncio queue:

```python
# backend/memory/write_queue.py
import asyncio
from collections.abc import Callable, Awaitable

_queue: asyncio.Queue = asyncio.Queue()
_worker_task: asyncio.Task | None = None

async def enqueue_write(operation: Callable[[], Awaitable]) -> any:
    """Submit a write operation and await its result."""
    future = asyncio.get_event_loop().create_future()
    await _queue.put((operation, future))
    return await future

async def _worker():
    """Single worker that processes writes sequentially."""
    while True:
        operation, future = await _queue.get()
        try:
            result = await operation()
            future.set_result(result)
        except Exception as e:
            future.set_exception(e)
        finally:
            _queue.task_done()

async def start_write_worker():
    global _worker_task
    _worker_task = asyncio.create_task(_worker())
```

Started at FastAPI startup. All `memory_write()`, `memory_update()`,
`memory_delete()` calls go through `enqueue_write()`.
Read operations (`memory_read()`, `context_snapshot()`) bypass the queue.

---

## Electron Dev vs Production Setup

### Development mode
Vite dev server runs on port 5173. Electron loads from it:
```javascript
// electron/main.js
const isDev = process.env.NODE_ENV === 'development'
const UI_URL = isDev ? 'http://localhost:5173' : `http://localhost:${REST_PORT}`

mainWindow.loadURL(UI_URL)
```
Start sequence in dev:
1. `npm run dev:backend` → starts FastAPI with `uvicorn --reload`
2. `npm run dev:vite` → starts Vite dev server
3. `npm run dev:electron` → starts Electron pointing to Vite port

### Production mode
Vite builds to `src/dist/`. FastAPI serves it as static files:
```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="src/dist", html=True), name="ui")
```
Electron loads from `http://localhost:{REST_PORT}` (FastAPI serves both API and UI).

### package.json scripts
```json
{
  "scripts": {
    "dev:backend": "uvicorn backend.main:app --reload --port 7860",
    "dev:vite": "vite",
    "dev:electron": "NODE_ENV=development electron electron/main.js",
    "dev": "concurrently \"npm:dev:backend\" \"npm:dev:vite\" \"npm:dev:electron\"",
    "build:ui": "vite build",
    "build:backend": "pyinstaller --onedir --name mnesis-backend backend/main.py",
    "build:bridge": "pyinstaller --onedir --name mcp-stdio-bridge backend/mcp_stdio_bridge.py",
    "build": "npm run build:ui && npm run build:backend && npm run build:bridge && electron-builder",
    "test": "pytest tests/ && vitest run"
  }
}
```

---

## React State Management

### Zustand — global UI state
```typescript
// src/lib/store.ts
import { create } from 'zustand'

interface AppStore {
  selectedMemoryId: string | null
  conflictCount: number
  pendingCount: number
  backendStatus: 'starting' | 'ready' | 'error'
  activeContext: string | null
  setSelectedMemory: (id: string | null) => void
  setConflictCount: (n: number) => void
  setPendingCount: (n: number) => void
  setBackendStatus: (s: AppStore['backendStatus']) => void
  setActiveContext: (c: string | null) => void
}

export const useAppStore = create<AppStore>((set) => ({
  selectedMemoryId: null,
  conflictCount: 0,
  pendingCount: 0,
  backendStatus: 'starting',
  activeContext: null,
  setSelectedMemory: (id) => set({ selectedMemoryId: id }),
  setConflictCount: (n) => set({ conflictCount: n }),
  setPendingCount: (n) => set({ pendingCount: n }),
  setBackendStatus: (s) => set({ backendStatus: s }),
  setActiveContext: (c) => set({ activeContext: c }),
}))
```

### React Query — server state
All API calls go through React Query. No manual useEffect for data fetching.
```typescript
// src/lib/queries.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './api'

export const useMemories = (filters) =>
  useQuery({ queryKey: ['memories', filters], queryFn: () => api.memories.list(filters) })

export const useContextSnapshot = (context?: string) =>
  useQuery({ queryKey: ['snapshot', context], queryFn: () => api.snapshot.get(context),
    staleTime: 30_000 }) // Snapshot valid for 30s before refetch

export const useCreateMemory = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.memories.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memories'] })
      qc.invalidateQueries({ queryKey: ['snapshot'] })
    }
  })
}
```

Cache invalidation rules:
- After any write to memories → invalidate ['memories', *] and ['snapshot', *]
- After conflict resolution → invalidate ['conflicts'] and ['memories', *]
- After import completes → invalidate all queries

---

## Three-Level Memory Model

### Level 1 — Semantic Memory (permanent)
Categories: `identity` | `preferences` | `skills` | `relationships` | `projects`
Behavior: always injected into snapshot. Rarely changes.
Expiration: none. Updated only if confidence_score > 0.85.

### Level 2 — Episodic Memory (historical)
Category: `history`
Behavior: never injected automatically. Retrieved only by memory_read().
Expiration: archived after 90 days without reference.

### Level 3 — Working Memory (short-term)
Category: `working`
Behavior: always injected. Expires after 72h TTL.

### Forgetting Curve (Ebbinghaus)
`score(t) = initial_score × e^(-decay_rate × days_since_last_reference)`
Decay rates (configurable in Settings):
- semantic: 0.001
- episodic: 0.05
- working: 0.3
Below 0.1 → status="archived". Never deleted. Always recoverable.

### Canonical Memory Format
All memories in consistent third-person declarative format.
Enforced by system prompt AND reconciliation pipeline.

CORRECT:
- "Thomas prefers concise answers without preamble or filler."
- "Thomas is building Mnesis, a universal LLM memory layer, since Jan 2026."
- "Thomas decided in Jan 2026 to use LanceDB over ChromaDB for performance."

INCORRECT:
- "The user likes short answers." → too vague, no name
- "Prefers Swift." → no subject
- "I like direct answers." → first person
- "Thomas might consider React." → uncertain, never write uncertain facts

### Memory length limit
Minimum: 20 characters.
Maximum: 1000 characters (not 500 — some valid memories need detail).
In tokens: reject if > 128 tokens (use tokenizer to check, not char count).
Content exceeding 128 tokens must be split into multiple memories by the LLM.

---

## LanceDB Data Schema

### Table `memories`
```python
{
    "id": str,                      # UUID
    "content": str,                 # Memory text, canonical format
    "level": str,                   # "semantic" | "episodic" | "working"
    "category": str,                # "identity"|"preferences"|"skills"|
                                    # "relationships"|"projects"|"history"|"working"
    "importance_score": float,      # 0.0 → 1.0, decays with Ebbinghaus
    "confidence_score": float,      # 0.0 → 1.0
    "privacy": str,                 # "public" | "sensitive" | "private"
    "tags": list[str],
    "source_llm": str,              # "claude"|"chatgpt"|"gemini"|"ollama"|"manual"
    "source_conversation_id": str,  # Optional FK → conversations.id
    "version": int,                 # Incremented on each update
    "status": str,                  # "active"|"archived"|"pending_review"|"conflicted"
    "created_at": datetime,
    "updated_at": datetime,
    "last_referenced_at": datetime,
    "reference_count": int,
    "vector": list[float]           # 384 dims, bge-small-en-v1.5
}
```

### Table `memory_versions`
```python
{
    "id": str,
    "memory_id": str,
    "content": str,
    "version": int,
    "changed_by": str,
    "created_at": datetime
}
```

### Table `conversations`
```python
{
    "id": str,
    "title": str,                   # From first user message, max 80 chars
    "source_llm": str,
    "started_at": datetime,
    "ended_at": datetime,
    "message_count": int,
    "memory_ids": list[str],
    "tags": list[str],
    "summary": str,
    "status": str,                  # "active" | "archived"
    "raw_file_hash": str,           # SHA-256 for import dedup
    "imported_at": datetime
}
```

### Table `messages`
```python
{
    "id": str,
    "conversation_id": str,
    "role": str,                    # "user" | "assistant"
    "content": str,
    "timestamp": datetime,
    "vector": list[float]           # Nullable, only if embed_messages=true in config
}
```

### Table `conflicts`
```python
{
    "id": str,
    "memory_id_a": str,
    "memory_id_b": str,
    "similarity_score": float,
    "detected_at": datetime,
    "resolved_at": datetime,        # Null if unresolved
    "resolution": str,              # "kept_a"|"kept_b"|"merged"|"both_valid"
    "status": str                   # "pending" | "resolved"
}
```

### Table `sessions`
```python
{
    "id": str,                      # UUID
    "api_key_id": str,              # Which client key opened this session
    "source_llm": str,
    "started_at": datetime,
    "ended_at": datetime,           # Null if still active
    "memory_ids_read": list[str],   # Memories retrieved during session
    "memory_ids_written": list[str],# Memories written during session
    "memory_ids_feedback": list[str],# Memories marked useful via feedback
    "end_reason": str               # "feedback_called"|"inactivity_timeout"|"unknown"
}
```

Sessions are used for: tracking active connections, end-of-session Ebbinghaus
updates, analytics in the dashboard (sessions per day per LLM client).

---

## API Security & CORS

### CORS policy
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{REST_PORT}",
        "app://.",           # Electron custom protocol
        "http://localhost:5173",  # Vite dev server (removed in production build)
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### API versioning
All REST routes: `/api/v1/`
MCP endpoint: port {MCP_PORT} (separate)
Breaking changes → introduce `/api/v2/` alongside v1.

### Authentication tiers
- REST API routes: no auth (local-only, CORS-protected)
- MCP endpoints: Bearer token per registered LLM client key
- Admin routes (`/api/v1/admin/*`): separate admin token (generated at first launch)
- Snapshot plain-text endpoint: dedicated read-only snapshot token (see below)

### Snapshot token
`GET /api/v1/snapshot/text?token={SNAPSHOT_TOKEN}`
The SNAPSHOT_TOKEN is:
- A separate read-only token generated at first launch
- Stored in config.yaml as `snapshot_read_token`
- Displayed in Settings → "ChatGPT Setup" section
- Can be regenerated from Settings (invalidates previous token immediately)
- Grants access ONLY to the snapshot endpoint, nothing else
- Rotated automatically every 90 days with a reminder notification

---

## MCP Tools (FastMCP)

### memory_read(query: str, limit: int = 5, context: str = None)
- Generates embedding for query
- Searches `memories` table (status="active" only)
- Re-ranking: `final_score = (0.5 × similarity) + (0.3 × importance_score) + (0.2 × recency_score)`
  where `recency_score = e^(-0.05 × days_since_last_referenced)`
- Context boost: tags matching context get ×1.3 on final_score
- Updates `last_referenced_at` and `reference_count` for returned results
- Logs read in current session's `memory_ids_read`
- Never returns privacy="private" unless source_llm is a known local LLM
- Returns: list of {id, content, category, level, importance_score, tags, source_llm}

### memory_write(content, category, level, importance=0.5, confidence=0.7, tags=[], privacy="public", source_llm)
- Validates: 20 ≤ len(content) ≤ 1000 chars, ≤ 128 tokens, valid enums
- Rejects first-person content (heuristic: starts with "I " or contains " I ")
- All writes enqueued via write_queue (concurrent safety)
- Exact dedup: SHA-256 of normalized content → return existing id, action="skipped"
- Semantic dedup: similarity > 0.92 → update existing, action="merged"
- Conflict: similarity 0.75-0.92 + contradiction heuristic → conflict entry, action="conflicted"
- Semantic + confidence < 0.85 → status="pending_review"
- Logs write in current session's `memory_ids_written`
- Returns: {id, status, action}

### memory_update(id, content, source_llm)
- Enqueued via write_queue
- Archives to `memory_versions`
- Recalculates embedding
- importance_score = max(current, 0.6)
- Resets last_referenced_at

### memory_delete(id)
- Enqueued via write_queue
- Sets status="archived" only. Never physical delete.

### memory_list(category=None, level=None, limit=20, offset=0)
- Paginated, sorted by importance_score DESC
- Returns metadata + first 100 chars of content

### memory_feedback(used_memory_ids: list[str])
- NOT enqueued (safe: only updates scores, no structural write)
- For each ID: reference_count += 1, importance_score = min(1.0, score + 0.05)
- Resets last_referenced_at for each
- Updates current session: memory_ids_feedback = used_memory_ids
- Marks session ended_at = now, end_reason = "feedback_called"

### conversation_search(query, limit=5, source_llm=None)
- Semantic on messages (if embed_messages=true) else full-text
- Returns: {conversation_id, title, source_llm, excerpt, score, date}

### conversation_list(source_llm=None, limit=20, offset=0)
- Paginated, metadata only

### context_snapshot(context: str = None)

Returns structured Markdown block. Max 800 tokens. Built fresh from LanceDB.

```markdown
# Memory Context — {ISO timestamp}

## Identity
{top 3 semantic, category=identity, by importance_score}

## Preferences & Working Style
{top 5 semantic, category=preferences, by importance_score}

## Active Projects
{all semantic, category=projects, by importance_score}

## Key Relationships
{top 5 semantic, category=relationships, by importance_score}

## Skills & Expertise
{top 5 semantic, category=skills, by importance_score}

## Recent Context (last 72h)
{all working memories, by created_at DESC}
```

Token budget: if > 800, truncate in reverse priority:
Skills → Relationships → Preferences → Projects → Recent Context → Identity (never truncated)

privacy="sensitive" → "[Redacted — ask user if relevant for this topic]"
privacy="private" → completely excluded (unless local LLM connection)
context parameter reorders: "development" → Projects + Skills first

### /health (REST GET, not MCP)
```json
{
  "status": "ok",
  "version": "1.0.0",
  "db_ready": true,
  "model_ready": true,
  "write_queue_depth": 0,
  "active_sessions": 2
}
```

---

## The System Prompt — Core Product

Delivered as tested, production-ready files in `system_prompts/`.
One file per client. The source_llm value is HARDCODED per file.

### Base system prompt

```
You have access to an external memory server via MCP (Mnesis).
This server stores the user's persistent memory across all LLM conversations.
Your fixed source identifier for all write operations: "{SOURCE_LLM_VALUE}"

━━━ MANDATORY RULES ━━━

[1] CONVERSATION START — execute silently, never announce

    Detect topic from user's first message, then call:
    context_snapshot(context="{detected}")

    Context values:
    - Code / APIs / architecture / debugging → "development"
    - Personal / emotions / relationships → "personal"
    - Writing / design / creativity → "creative"
    - Work / strategy / business → "business"
    - No clear topic → omit context parameter entirely

    Internalize the snapshot. Never quote it back.
    Your first response must feel like you already know this person.

[2] WHEN TO READ (during conversation)

    Call memory_read(query="...", context="...") when:
    - User references a project, person, place, or past decision
    - User says "as usual", "you know", "like we discussed", "remember"
    - You are about to make an assumption — verify it first
    Do NOT call on every message. Use judgment.

[3] WHEN TO WRITE (during conversation)

    Call memory_write() IMMEDIATELY when user:
    ✓ States name, profession, location, or major personal fact
    ✓ Expresses a clear, durable preference ("I always prefer X", "I hate Y")
    ✓ Describes an active project with meaningful detail
    ✓ Makes a significant, durable decision
    ✓ Corrects something you believed about them
    ✓ Mentions a key person in their life (family, colleague, client)

    Do NOT write for:
    ✗ Temporary states ("I'm tired", "I'm busy today")
    ✗ Hypothetical or uncertain info ("I might try React someday")
    ✗ General opinions not specific to this user
    ✗ Information already in memory (always check with memory_read first)

    Format rules — MANDATORY:
    - Third-person declarative: "{name} prefers..." not "I prefer..."
    - Complete and specific: include names, dates, context
    - Factual only: never write uncertain or conditional facts
    - Length: 20 to 1000 characters, under 128 tokens
    - If content would exceed 128 tokens: split into multiple memory_write calls

    Level selection:
    - "semantic" → lasting personal facts, identity, stable preferences, projects
    - "episodic" → specific past events, decisions made, conclusions reached
    - "working" → active context relevant for the next 72h only

[4] CONFLICT HANDLING

    If user states something contradicting a known memory:
    Call memory_write() with the new information.
    Acknowledge naturally: "Got it, I'll keep that in mind."
    Do not debate — the user's current statement takes precedence.

[5] CONVERSATION END

    Call memory_feedback(used_memory_ids=[...]) when:
    - User says: goodbye, "that's all", "thanks", "see you", "done for now"
    - You generate a clearly final or summary response
    - Conversation topic has fully resolved

    Include ONLY memory IDs that genuinely influenced your responses.
    Do not include every memory retrieved — only those actually useful.

[6] ABSOLUTE DISCRETION

    Never mention Mnesis, MCP, or memory calls to the user.
    Never say "I'm saving this to memory" or "I'm checking my memory."
    Memory must feel like natural knowledge, not an operated system.
    Only exception: if user explicitly asks how you remember things,
    give a brief, honest explanation.
```

### Per-client files

**`system_prompts/claude_desktop.md`**
SOURCE_LLM_VALUE = "claude"
Transport: stdio via mcp_stdio_bridge
Auto-injected into Claude Desktop Project system prompt by Electron

**`system_prompts/chatgpt.md`**
SOURCE_LLM_VALUE = "chatgpt"
Today: ChatGPT Custom Instructions variant (see ChatGPT fallback below)
Future: same base prompt + MCP Action

**`system_prompts/cursor.md`**
SOURCE_LLM_VALUE = "cursor"
Delivered to `.cursor/rules`
MCP via `.cursor/mcp.json` (HTTP/SSE)

**`system_prompts/ollama.md`**
SOURCE_LLM_VALUE = "ollama"
Additional: may access privacy="private" memories
Delivered as system prompt in Ollama Modelfile or LM Studio config

---

## ChatGPT Fallback Strategy (Today, Without Native MCP)

### Plain-text snapshot endpoint
`GET /api/v1/snapshot/text?token={SNAPSHOT_TOKEN}`
Returns context_snapshot() as plain text, max 600 tokens, no Markdown.

### "ChatGPT Setup" page in dashboard
Step-by-step with screenshots:
1. Open ChatGPT → Settings → Custom Instructions
2. Paste the following (auto-generated, "Copy" button):
   ```
   Before every response, recall this about me:
   [snapshot content — regenerated each time user clicks Refresh]
   Treat this as if you already know me. Do not quote it back.
   ```
3. "Refresh Snapshot" button: regenerates + copies to clipboard
4. Note: "Refresh and re-paste when your life or projects change significantly."

### Dashboard client status badges
- Claude Desktop: "🟢 Automatic (MCP)"
- Cursor: "🟢 Automatic (MCP)"
- ChatGPT: "🟡 Manual — refresh when needed" or "🟢 Automatic" when MCP available

### Future migration
Settings shows "Upgrade ChatGPT to Automatic" when MCP is available.
Electron auto-injects config. No data migration — memory store is unchanged.

---

## End-of-Conversation Detection

MCP has no native session-end event. Two complementary mechanisms:

### Mechanism 1: Server-side inactivity timeout
FastAPI tracks last MCP call per API key in the `sessions` table.
Background task checks every 5 minutes for sessions idle > 30 minutes:
1. Mark session: ended_at = now, end_reason = "inactivity_timeout"
2. Run Ebbinghaus update for memories read/written in that session
3. Do NOT call memory_feedback (LLM's responsibility)

### Mechanism 2: System prompt explicit triggers
System prompt defines exact closure signals the LLM should detect:
- User says: "goodbye", "that's all", "thanks", "see you", "done", "bye"
- LLM generates a final summary or closing response
- Conversation topic fully resolved with no follow-up

Dual mechanism ensures coverage: LLM handles clean endings,
server timeout handles abrupt closures.

---

## Import Pipeline & Onboarding

### Supported formats

| Source  | Files                                    | Notes                                       |
|---------|------------------------------------------|---------------------------------------------|
| Claude  | `memories.json` + `conversations.json`   | memories.json imported directly, no re-extract |
| ChatGPT | `memories.json` + `conversations.json`   | memories.json imported directly, no re-extract |
| Gemini  | Google Takeout ZIP                       | Stream-parsed via zipfile + ijson           |
| Manual  | UI questionnaire                         | Structured onboarding form                  |

### Large file streaming
All parsers use ijson for JSON streaming — files never fully loaded into RAM:
```python
import ijson

def stream_memories(filepath: str, chunk_size: int = 100):
    with open(filepath, 'rb') as f:
        parser = ijson.items(f, 'item')
        chunk = []
        for item in parser:
            chunk.append(item)
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk
```
Progress reported via Server-Sent Events to UI progress bar.
On error in any chunk: log + skip + continue (never abort full import).

### Claude memories.json format
```json
[
  {
    "title": "General Preferences",
    "content": "Prefers concise communication",
    "created_at": "2026-01-15T10:00:00Z"
  }
]
```

### ChatGPT memories.json format
```json
[
  {
    "memory": "User prefers concise answers",
    "created_at": "2026-01-15T10:00:00Z"
  }
]
```

### Taxonomic normalization — explicit mapping tables

Claude category → Mnesis (level, category):
```python
CLAUDE_CATEGORY_MAP = {
    "General Preferences": ("semantic", "preferences"),
    "Personal Information": ("semantic", "identity"),
    "Technical Preferences": ("semantic", "preferences"),
    "Professional Background": ("semantic", "identity"),
    "Projects": ("semantic", "projects"),
    "Relationships": ("semantic", "relationships"),
    "Skills": ("semantic", "skills"),
    "Goals": ("semantic", "projects"),
    "Communication Style": ("semantic", "preferences"),
    # Fallback for any unknown Claude category:
    "_default": ("semantic", "preferences"),
}
```

ChatGPT category → Mnesis:
ChatGPT does not use categories in its memories.json export (flat list).
All ChatGPT memories are classified by keyword heuristics:
```python
CHATGPT_KEYWORD_MAP = [
    # (keywords_in_content, level, category)
    (["name is", "called", "my name"], "semantic", "identity"),
    (["work", "job", "profession", "developer", "engineer", "designer"],
     "semantic", "identity"),
    (["project", "building", "working on", "creating"], "semantic", "projects"),
    (["prefer", "like", "love", "hate", "dislike", "always use", "never use"],
     "semantic", "preferences"),
    (["skill", "expert", "know", "experienced", "familiar with"], "semantic", "skills"),
    (["wife", "husband", "partner", "colleague", "friend", "boss", "client"],
     "semantic", "relationships"),
    # Fallback:
    ("_default", "semantic", "preferences"),
]
```
If Ollama is available: use local LLM to classify instead of keyword heuristics.

### Cross-source reconciliation pipeline

1. Taxonomic normalization (using maps above)
2. Format normalization → canonical third-person declarative format
   (Ollama if available, regex + flag as "needs_review" if not)
3. Exact deduplication: SHA-256 of content.lower().strip()
4. Semantic deduplication: embed → similarity > 0.92 → merge
5. Conflict detection: similarity 0.75-0.92 + contradiction heuristic
6. Importance scoring:
   - 0.5 default
   - 0.8 if contains proper nouns, dates, numbers, explicit preferences
   - 0.9 if present in BOTH source exports
7. Preview before confirmation (no DB writes until confirmed)
8. Batch write: 50 per batch, progress via SSE

### Preview screen (before confirmation)
Show:
- Total memories found per source
- Duplicates to be skipped (count)
- Conflicts detected (count + 3 examples)
- 10 sample memories to be created
- Estimated import time
→ "Confirm Import" button only after this preview

### Cold start onboarding questionnaire
Triggered when: onboarding_completed=false in config.yaml AND < 10 active memories.
`onboarding_completed` is set to `true` in config.yaml after Step 4 below.
Creates semantic memories with importance_score = 0.9.

Questions:
1. What is your name?
2. What do you do professionally?
3. Where are you based? (optional)
4. What are you currently working on? (one project per input, add multiple)
5. What are your main skills or tools? (optional)
6. How should LLMs communicate with you?
   → Concise / Detailed / Casual / Formal (radio)
7. Any key people in your life to remember? (optional, add multiple)

Each answer → canonical memory created in real-time (user sees them appear).
After completion → set onboarding_completed=true in config.yaml.

---

## Conflict Resolution UI

Dashboard: "Conflicts to resolve" badge with count.
Empty state: "No conflicts — your memory is consistent."

For each conflict:
- Left card: Memory A — source LLM badge, date, full content
- Right card: Memory B — source LLM badge, date, full content
- Similarity score shown between cards
- Actions: "Keep A" | "Keep B" | "Merge" | "Both are valid"
- "Merge" → text editor pre-filled with both; user writes unified version
- Progress: "3 of 7 conflicts resolved"

Conflicts are NEVER auto-resolved. Always a human decision.
Unresolved conflicts appear in snapshots with "[Conflicting info — verify with user]".

---

## Config Watcher

Background thread in FastAPI. Checks every 60 seconds.
Rate limiting: max 1 native notification per event type per hour.
(Prevents notification spam if config is repeatedly overwritten.)

```python
# Notification rate limit state
_last_notified: dict[str, datetime] = {}
NOTIFY_COOLDOWN_HOURS = 1

def should_notify(event_type: str) -> bool:
    last = _last_notified.get(event_type)
    if last is None or (datetime.now() - last).hours >= NOTIFY_COOLDOWN_HOURS:
        _last_notified[event_type] = datetime.now()
        return True
    return False
```

Reads `clients.yaml` for all client definitions.
For each client:
1. Parse config file on disk
2. Verify Mnesis entry is present and correct
3. If wrong/missing → restore → notify (if cooldown passed) → log

All changes logged to `data/config_watcher.log`.

`clients.yaml`:
```yaml
clients:
  claude_desktop:
    name: "Claude Desktop"
    mac_config_path: "~/Library/Application Support/Claude/claude_desktop_config.json"
    windows_config_path: "%APPDATA%/Claude/claude_desktop_config.json"
    transport: "stdio_bridge"
    system_prompt_file: "system_prompts/claude_desktop.md"
    mcp_bridge_env:
      MNESIS_MCP_URL: "http://localhost:{MCP_PORT}"
      MNESIS_API_KEY: "{CLIENT_API_KEY}"

  cursor:
    name: "Cursor"
    mac_config_path: "~/.cursor/mcp.json"
    windows_config_path: "%USERPROFILE%/.cursor/mcp.json"
    transport: "http"
    system_prompt_file: "system_prompts/cursor.md"
    rules_path_mac: "~/.cursor/rules"
    rules_path_windows: "%USERPROFILE%/.cursor/rules"
```

Adding new LLM clients: edit clients.yaml only. Zero code changes.

---

## Multi-Device Sync

### V1 — Cloud folder
data/ path configurable in Settings. Supported: iCloud, Dropbox, Google Drive, any synced folder.
Installer asks "Do you use multiple devices?" → guides cloud folder setup if yes.

Write lock via `data/.lock` (hostname + PID + timestamp):
- Different hostname → read-only mode + notification
- Same hostname → stale lock (crash recovery) → delete, proceed
- No lock → create, proceed
- Rechecked every 30 seconds

### V2 (roadmap)
Docker-based remote server with proper concurrent write support.

---

## Scheduled Tasks

State in `data/scheduler_state.json`. Catch-up runs at startup if missed.

### Ebbinghaus decay (target: daily)
```python
def run_ebbinghaus():
    if (now - read_last_run("ebbinghaus")).hours < 20:
        return
    for memory in get_all_active_memories():
        days = (now - memory.last_referenced_at).days
        new_score = memory.importance_score * exp(-DECAY_RATES[memory.level] * days)
        archive_memory(memory.id) if new_score < 0.1 else update_importance(memory.id, new_score)
    write_last_run("ebbinghaus", now)
```

### Weekly maintenance (target: Sunday, catch-up if missed)
- Detect new semantic conflicts in recent memories
- LanceDB compaction
- Rebuild dashboard statistics
- Clean sessions older than 90 days

### Snapshot token rotation (every 90 days)
- Auto-regenerate snapshot_read_token in config.yaml
- Send native notification: "Your ChatGPT snapshot link has been refreshed.
  Update your ChatGPT Custom Instructions."
- Old token invalidated immediately

### Update check (startup, non-blocking, 3s timeout)
- GET GitHub Releases API, compare versions
- Show dashboard banner if newer (never auto-update)
- Fail silently on network error

---

## Database Migrations

```
backend/migrations/
├── 001_initial_schema.py   # All tables
├── 002_add_sessions.py     # Sessions table
├── 003_add_privacy.py      # Privacy field
└── ...
```

Each file exports:
```python
VERSION = 1
DESCRIPTION = "Initial schema — all LanceDB tables"

def up(db: lancedb.DBConnection):
    # Additive only. Never drop columns/tables. Never delete data.
    pass
```

At FastAPI startup (before any request):
```python
current = int(read_file("data/schema_version.txt", default="0"))
for m in sorted([m for m in migrations if m.VERSION > current], key=lambda m: m.VERSION):
    m.up(db)
    write_file("data/schema_version.txt", str(m.VERSION))
```

Failed migration → startup stops, error shown with log path.

---

## Testing Strategy

Tests are written BEFORE moving to the next implementation step.
No step is "done" until its tests pass.

### Unit tests (`tests/unit/`)

**`test_retrieval.py`**
- Scoring formula for all weight combinations
- Snapshot never exceeds 800 tokens (1000 fake memories as input)
- Truncation priority order is correct
- Context parameter correctly reorders sections
- Ebbinghaus decay at 1, 7, 30, 90, 365 days per level

**`test_memory_write.py`**
- Content too short (< 20 chars) → rejected
- Content too long (> 1000 chars) → rejected
- Content > 128 tokens → rejected
- First-person content → rejected
- SHA-256 exact match → action="skipped"
- Semantic similarity > 0.92 → action="merged"
- Similarity 0.75-0.92 + contradiction → action="conflicted"
- Semantic + confidence < 0.85 → status="pending_review"
- Concurrent writes (10 simultaneous) → no corruption, all processed

**`test_importers.py`**
- Claude memories.json: all categories correctly mapped
- ChatGPT memories.json: keyword heuristics correctly classify
- Gemini ZIP: structure parsed correctly
- 1GB+ file: streamed without OOM error
- Malformed input: parser continues, logs error, never crashes

**`test_reconciliation.py`**
- Same fact, different wording → merged (not duplicated)
- Contradicting facts → conflict entry created
- Memory in both exports → importance 0.9
- Full pipeline on mixed good/bad input → completes with partial success

**`test_write_queue.py`**
- 50 concurrent memory_write calls → all complete, no corruption
- Queue processes in order (FIFO)
- Failed write does not block queue

### Integration tests (`tests/integration/`)

**`test_mcp_tools.py`**
- memory_write → memory_read round-trip (retrieved within top 5)
- context_snapshot always under 800 tokens with realistic data set
- memory_feedback updates reference_count and importance correctly
- privacy="private" excluded from cloud LLM read
- stdio bridge correctly forwards to HTTP server and back

**`test_config_watcher.py`**
- Overwritten Claude Desktop config → restored within 60 seconds
- Notification rate limit: second notification suppressed within 1 hour
- Missing config file → created correctly from template
- Other MCP entries in config → preserved on restore

**`test_api_security.py`**
- REST routes reject non-localhost origins (CORS)
- MCP routes reject invalid Bearer token (401)
- Snapshot text endpoint rejects invalid snapshot token (401)
- Admin routes reject non-admin token (403)

**`test_electron_backend.py`** (Electron integration)
- Backend starts within 30 seconds on clean install
- /health correctly reports model_ready=false before load, true after
- Port conflict handled: alternative port selected automatically
- Subprocess crash: auto-restarts, /health recovers

### System prompt evaluation (`tests/prompts/`)

`scenarios.json` format:
```json
[
  {
    "id": "sc001",
    "description": "LLM calls context_snapshot at conversation start",
    "user_message": "Help me write a function to parse JSON in Swift.",
    "expected_mcp_calls": ["context_snapshot"],
    "expected_context_param": "development",
    "must_not_contain_in_response": ["Mnesis", "MCP", "memory server"]
  },
  {
    "id": "sc002",
    "description": "LLM writes memory for stated preference",
    "user_message": "I always prefer concise answers without preamble.",
    "expected_mcp_calls": ["context_snapshot", "memory_write"],
    "expected_memory_format": "third_person_declarative",
    "expected_level": "semantic"
  },
  {
    "id": "sc003",
    "description": "LLM does NOT write memory for temporary state",
    "user_message": "I'm really tired today.",
    "expected_mcp_calls": ["context_snapshot"],
    "must_not_call": ["memory_write"]
  },
  {
    "id": "sc004",
    "description": "LLM calls memory_feedback on conversation close",
    "user_message": "Thanks, that's all I needed!",
    "expected_mcp_calls": ["memory_feedback"],
    "memory_feedback_must_contain_only_used_ids": true
  }
]
```

`tests/prompts/evaluator.py` replays each scenario against a live LLM,
captures all MCP calls made, checks against expectations, reports pass/fail.
Minimum pass rate: 90% per client before shipping that client's system prompt.

---

## Windows-Specific Implementation

Windows is a first-class platform from day one.

### Auto-start
`app.setLoginItemSettings({ openAtLogin: true })` — Electron handles both platforms natively.

### File paths
```javascript
// Always use Electron's path APIs
const dataPath = path.join(app.getPath('userData'), 'Mnesis')
const logPath = path.join(app.getPath('logs'), 'backend.log')
```
Python: always `pathlib.Path`. Never string concatenation.
clients.yaml uses `%APPDATA%` and `%USERPROFILE%` — expanded with `os.path.expandvars()`.

### PyInstaller Windows
```
pyinstaller --onedir --name mnesis-backend --windowed backend/main.py
pyinstaller --onedir --name mcp-stdio-bridge --windowed backend/mcp_stdio_bridge.py
```
`--windowed` prevents terminal window on Windows.

### Notifications
Electron `Notification` API works natively on both Mac and Windows.

---

## User Interface (Vite + React + shadcn/ui + Zustand + React Query)

### Pages

**1. Dashboard**
Stat cards: active memories / conversations / pending review / open conflicts
Breakdown bars: by level (semantic/episodic/working) and by source LLM
30-day sparkline: memories written per day
LLM client status row: one badge per detected client (🟢/🟡/🔴)
"Conflicts to resolve" alert card — shown only if conflictCount > 0
Last 5 memories (inline edit via React Query mutation)
Quick actions: Add Memory / Import / Context Preview

**2. Memory Browser**
Semantic search input (memory_read, 300ms debounce via React Query)
Filters: level, category, source LLM, privacy, status (Zustand filter state)
List row: content preview (100 chars), tags, importance bar, source badge, date
Expanded row: full content, edit in place, archive button, source conversation link
Status badges: "Pending review" / "Conflicted" / toggle archived visibility

**3. Conflict Resolver**
Count badge in nav. Empty state: "No conflicts."
Side-by-side cards per conflict: content, source, date, similarity score
Actions: Keep A / Keep B / Merge / Both are valid
Merge editor: pre-filled text area, user writes unified version
Progress tracker: "3 of 7 resolved"

**4. Conversation Archive**
Search + filters: source LLM, date range, tags
List: title, source badge, date, message count, summary on hover
Click → Conversation Viewer

**5. Conversation Viewer**
Chat bubbles: user right / assistant left, color-differentiated
Source badge + conversation dates at top
Right sidebar: linked memories (click → Memory Browser), tags, summary
"Extract more memories" button (re-runs pipeline on demand)
"Export as Markdown" button

**6. Add Memory (manual)**
Content textarea with live validation:
- Character count (20–1000)
- Token count (≤ 128)
- Format hint: "Write in third person: 'Thomas prefers...'"
- Red border + error message if invalid
Fields: category, level, privacy, tags, importance slider
Live preview of how it appears in context_snapshot
Save → confirmation with memory ID

**7. Context Preview**
Live render of context_snapshot() (React Query, staleTime 30s)
Context selector: Development / Personal / Business / Creative / (none)
Token counter: "642 / 800 tokens"
"Copy to clipboard" button (for ChatGPT manual paste)
"Refresh" button (invalidates React Query cache)

**8. Onboarding** (shown when onboarding_completed=false in config)
Step 1: Import from LLM exports — drag & drop, source selector
Step 2: Questionnaire — if Step 1 skipped or as supplement
Step 3: Conflict resolution — shown only if conflicts detected
Step 4: context_snapshot() preview — "This is what LLMs will know about you"
Step 5: Client configuration status — "Claude Desktop ✅ | ChatGPT setup →"
On completion → POST /api/v1/admin/onboarding-complete → sets flag in config.yaml

**9. Export / Import**
Section A: Native export (full JSON) / import (restore)
Section B: LLM import → source → upload → preview → progress (SSE) → success
Section C: ChatGPT manual setup — snapshot URL, refresh button, copy-paste text
Section D: Export individual conversation as Markdown

**10. Settings**
LLM Clients: list, status badge, "Reconfigure" button
API Keys: masked + regenerate per client
Snapshot Token: masked + regenerate (with ChatGPT warning on regenerate)
Data folder: current path + "Change" → sync setup flow
Memory validation: Auto / Review / Strict (radio + descriptions)
Encryption: toggle AES-256 (warning dialog)
Embed messages: toggle (affects conversation semantic search)
Decay rates: sliders per level (Advanced, collapsed by default)
Language: interface language selector
About: version, update status, GitHub link

### Design rules
- Dark mode default, light mode via system preference
- shadcn/ui for all components — no custom reinventing
- Zero technical jargon. Full glossary enforced:
  - importance_score → "importance"
  - archived → "forgotten" (tooltip: "saved but hidden, never deleted")
  - pending_review → "waiting for review"
  - semantic → "long-term"
  - working → "recent"
  - episodic → "past events"
  - MCP → never shown to users
  - source_llm → "from [Claude/ChatGPT/etc.]"
- Every destructive action requires explicit confirmation dialog
- Every list has a helpful, actionable empty state
- All error messages in plain language with a suggested next action

---

## Project Structure

```
mnesis/
├── electron/
│   ├── main.js                        # Main: subprocess mgmt, ports, tray, window
│   ├── preload.js                     # contextBridge: secure renderer↔main IPC
│   └── tray.js                        # Menu bar icon, context menu, status dot
├── src/                               # React app (Vite)
│   ├── main.tsx
│   ├── App.tsx                        # Router + QueryClientProvider + layout
│   ├── pages/
│   │   ├── Dashboard.tsx
│   │   ├── MemoryBrowser.tsx
│   │   ├── ConflictResolver.tsx
│   │   ├── ConversationArchive.tsx
│   │   ├── ConversationViewer.tsx
│   │   ├── AddMemory.tsx
│   │   ├── ContextPreview.tsx
│   │   ├── Onboarding.tsx
│   │   ├── ExportImport.tsx
│   │   └── Settings.tsx
│   ├── components/
│   │   ├── MemoryCard.tsx
│   │   ├── ConflictCard.tsx
│   │   ├── SnapshotPreview.tsx
│   │   ├── ImportProgress.tsx
│   │   └── ClientStatusBadge.tsx
│   └── lib/
│       ├── api.ts                     # Typed HTTP client for all REST routes
│       ├── store.ts                   # Zustand global UI state
│       ├── queries.ts                 # React Query hooks for all data fetching
│       └── types.ts                   # TypeScript types mirroring Python schemas
├── backend/
│   ├── main.py                        # FastAPI factory, startup, CORS, static, routes
│   ├── mcp_server.py                  # All MCP tools (FastMCP, HTTP/SSE)
│   ├── mcp_stdio_bridge.py            # Thin stdio↔HTTP bridge for Claude Desktop
│   ├── health.py                      # /health endpoint
│   ├── memory/
│   │   ├── models.py                  # Pydantic schemas for all tables
│   │   ├── store.py                   # All LanceDB CRUD
│   │   ├── retrieval.py               # Scoring, re-ranking, snapshot generation
│   │   ├── ebbinghaus.py              # Decay calculations, archive logic
│   │   ├── embedder.py                # Model singleton, embed(), embed_batch()
│   │   ├── write_queue.py             # Asyncio write queue for concurrent safety
│   │   └── importers/
│   │       ├── base.py                # Abstract: parse() → list[RawMemory]
│   │       ├── claude.py              # Claude memories.json + conversations.json
│   │       ├── chatgpt.py             # ChatGPT memories.json + conversations.json
│   │       ├── gemini.py              # Google Takeout ZIP (streaming)
│   │       └── reconciliation.py     # Full cross-source reconciliation pipeline
│   ├── api/
│   │   └── v1/
│   │       ├── memories.py            # Memory CRUD + search
│   │       ├── conversations.py       # Archive routes
│   │       ├── conflicts.py           # Conflict resolution
│   │       ├── import_export.py       # Import (SSE progress) + export
│   │       ├── snapshot.py            # Snapshot REST + plain-text endpoint
│   │       ├── settings.py            # Config, keys, client status
│   │       └── admin.py               # Admin-only: onboarding-complete, token rotation
│   ├── auth.py                        # Bearer middleware (MCP + admin tiers)
│   ├── config_watcher.py              # Background: monitor + repair LLM configs
│   ├── scheduler.py                   # Background: Ebbinghaus, maintenance, token rotation
│   ├── migrations/
│   │   ├── 001_initial_schema.py      # All core tables
│   │   ├── 002_add_sessions.py        # Sessions table
│   │   └── 003_add_privacy_field.py   # Privacy field on memories
│   └── config.py                      # YAML → Pydantic config loader
├── system_prompts/
│   ├── claude_desktop.md              # Tested system prompt, source_llm="claude"
│   ├── chatgpt.md                     # Tested system prompt, source_llm="chatgpt"
│   ├── cursor.md                      # Tested system prompt, source_llm="cursor"
│   └── ollama.md                      # Tested system prompt, source_llm="ollama"
├── tests/
│   ├── unit/
│   │   ├── test_retrieval.py
│   │   ├── test_memory_write.py
│   │   ├── test_importers.py
│   │   ├── test_reconciliation.py
│   │   └── test_write_queue.py
│   ├── integration/
│   │   ├── test_mcp_tools.py
│   │   ├── test_config_watcher.py
│   │   ├── test_api_security.py
│   │   └── test_electron_backend.py
│   └── prompts/
│       ├── scenarios.json             # 20 evaluation scenarios per client
│       └── evaluator.py              # Runs scenarios, reports pass/fail rates
├── clients.yaml                       # LLM client definitions (no code changes needed)
├── config.yaml                        # Generated at first launch, user-editable
│                                      # Contains: api_keys, ports, data_path,
│                                      # snapshot_read_token, onboarding_completed,
│                                      # validation_mode, decay_rates, encrypt
├── pyproject.toml                     # Python deps: fastapi, fastmcp, lancedb,
│                                      # sentence-transformers, ijson, httpx, pydantic,
│                                      # uvicorn, python-jose, cryptography
├── package.json                       # Node deps: electron, vite, react, tailwindcss,
│                                      # shadcn-ui, zustand, @tanstack/react-query,
│                                      # electron-builder, concurrently
├── vite.config.ts                     # Vite config: build output to src/dist/
├── electron-builder.config.js         # .dmg (Mac) + .exe (Windows) + extraResources
├── docker-compose.yml                 # V2: remote server with multi-writer support
├── README.md                          # Non-technical user guide (plain language)
├── README_DEV.md                      # Architecture, dev setup, contribution guide
└── data/                              # All user data — gitignored, never in repo
    ├── lancedb/                       # LanceDB tables
    ├── models/                        # Embedding model (downloaded once)
    ├── schema_version.txt             # Current DB schema version number
    ├── scheduler_state.json           # Last run timestamps per task
    ├── config_watcher.log             # Config change history
    ├── configured_clients.json        # Which LLM clients are configured
    └── .lock                          # Multi-device write lock
```

---

## Implementation Order

Ask for explicit confirmation before each step.
Do not start the next step until current step's tests pass.

1. **DB schema + LanceDB init + write queue**
   `memory/models.py`, `memory/store.py`, `memory/write_queue.py`,
   `migrations/001_initial_schema.py`, `migrations/002_add_sessions.py`,
   `migrations/003_add_privacy_field.py`
   Tests: CRUD round-trips, concurrent writes (50 simultaneous), migrations

2. **Embedder singleton + retrieval + Ebbinghaus**
   `memory/embedder.py`, `memory/retrieval.py`, `memory/ebbinghaus.py`
   Tests: singleton loads once, scoring formula, snapshot token budget,
   decay at all time intervals

3. **MCP server + stdio bridge + auth**
   `mcp_server.py`, `mcp_stdio_bridge.py`, `auth.py`
   Tests: all tools via HTTP MCP client, stdio bridge round-trip, auth rejection

4. **System prompts — all clients**
   `system_prompts/*.md`
   Evaluation: run all scenarios via evaluator.py, ≥90% pass rate required

5. **Import pipeline + reconciliation**
   `memory/importers/*`, `reconciliation.py`
   Tests: all formats, category mapping complete, streaming on 1GB+, dedup, conflicts

6. **FastAPI backend — all routes**
   `api/v1/*`, `health.py`, CORS, versioning, snapshot token auth
   Tests: all routes, CORS policy, all auth tiers, snapshot token isolation

7. **Config watcher + scheduler**
   `config_watcher.py`, `scheduler.py`
   Tests: config restored <60s, notification rate limit, catch-up on missed runs,
   token rotation at 90 days

8. **React UI — all 10 pages**
   In order: Dashboard → Memory Browser → Conflict Resolver →
   Conversation Archive → Conversation Viewer → Add Memory →
   Context Preview → Onboarding → Export/Import → Settings

9. **Electron shell + first launch flow**
   `electron/main.js`, `preload.js`, `tray.js`
   Port selection, health polling, subprocess mgmt, tray, auto-start,
   model download screen, LLM client auto-configuration

10. **Packaging + clean install tests**
    `electron-builder.config.js`, PyInstaller scripts
    Must: install on clean Mac VM (no Python) ✅ + clean Windows VM ✅

11. **Docker Compose** (V2 remote server groundwork)

12. **Documentation**
    `README.md` (non-tech, plain language, no jargon)
    `README_DEV.md` (architecture, dev setup, how to add new LLM client)

---

## Success Criteria

Complete only when ALL of the following are true:

✅ Non-technical user downloads .dmg or .exe, installs like any app, completes
   onboarding in under 5 minutes. First Claude Desktop conversation already
   knows who they are. Zero terminal. Zero manual config.

✅ User switches Claude Desktop → ChatGPT Desktop. ChatGPT immediately knows
   full context of who this person is via context_snapshot(). No re-explanation.

✅ 50 simultaneous memory_write() calls from two different LLM clients produce
   zero data corruption. All writes complete. Write queue processes all of them.

✅ Importing Claude memories.json + ChatGPT memories.json → unified memory
   without duplicates. All conflicts visible in dashboard for human resolution.

✅ 2GB ChatGPT conversations.json imports without OOM crash. Live progress bar
   in UI. Resumes correctly after cancellation.

✅ Claude Desktop updates and overwrites MCP config → restored within 60 seconds.
   Native notification sent. If it happens again within the hour: no notification
   spam (rate limit respected).

✅ Machine off for 5 days → Ebbinghaus catch-up runs at next startup.
   Scores updated correctly. Stale working memories expired.

✅ All data in ./data/. Exportable as one JSON. Fully restorable on new machine.

✅ 100% offline after first launch (model download is the only network call).

✅ Adding a new MCP-compatible LLM client: add entry to clients.yaml + one
   system prompt file. Zero code changes. Zero restart needed.

✅ All unit tests pass. All integration tests pass.
   System prompt evaluation: ≥90% pass rate per client.

✅ Clean install test passes on: Mac (no prior Python) ✅ Windows (no prior Python) ✅

---

Start by outputting the complete project structure with a one-line description
for each file and directory. Then implement file by file in the defined order.
Ask for explicit confirmation before each step.
Never skip a step. Never skip tests. Never leave a TODO in the code.

