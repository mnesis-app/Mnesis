# Mnesis — CLAUDE.md

Local-first memory infrastructure for multi-LLM workflows. Desktop app (macOS + Windows) exposing a shared memory layer via MCP across Claude, ChatGPT, Cursor, and other clients.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand, TanStack Query, Radix UI |
| Backend | Python, FastAPI, LanceDB (vector), KuzuDB (graph), sentence-transformers |
| Desktop | Electron |
| Bridge | Python (`mcp_stdio_bridge.py`) |

## Dev ports

- UI: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:7860`

## Key commands

```bash
npm run dev              # Full stack: backend + vite + electron (with hot reload)
npm run dev:backend      # Backend only
npm run dev:vite         # UI only
npm run test             # Frontend vitest
npm run test:backend     # Backend pytest
npm run check:v1         # V1 public readiness checks
npm run clean:tmp        # Cleanup tmp workspace artifacts
```

## Repository structure

```
backend/         FastAPI app, memory core, MCP server, scheduler, sync
  routers/       HTTP API routers (memories, conversations, search, admin, ...)
  database/      DB schema and client
  memory/        Write/read logic, scoring, lifecycle, dedupe, provenance
  insights/      Conversation analysis jobs and workers
  sync/          Remote sync logic
src/             React UI
  components/    Page-level and shared UI components
electron/        Electron shell and process orchestration
tests/           Backend pytest suite
scripts/         Dev/ops utility scripts
system_prompts/  Per-client MCP system prompt templates
```

## Architecture invariants

- **Local-first**: no mandatory cloud relay; online exposure is BYO tunnel only.
- **Provider-agnostic**: not tied to any single LLM vendor.
- **Traceable writes**: all memory writes carry provenance (source LLM, conversation, message, excerpt).
- **Status transitions** for memories are explicit — do not bypass lifecycle states.
- **Vectors are backend-only**: never return raw embeddings in frontend API payloads.

## Backend startup order (for debugging)

1. DB init / migrations
2. Config baseline hardening
3. Write queue start
4. Analysis worker start
5. Model warmup (background thread)
6. Scheduler start
7. Config watcher + MCP autoconfig

## Key data entities

- `Memory`: content, category, level, status, importance/confidence scores, provenance fields, decay/temporal fields
- `Conversation` + `Message`: imported from LLM clients, hashed for dedup
- `Conflict / PendingConflict`: write collision resolution state
- `conversation_analysis_*` tables: async analysis jobs and candidates
- `memory_events` / `client_runtime_metrics`: telemetry

## Conventions

- Python: FastAPI + async throughout the backend; pytest for tests.
- TypeScript: strict mode; prefer `hooks/` for data-fetching logic.
- State: Zustand for global UI state, TanStack Query for server state.
- Styling: Tailwind utility classes; component variants via `class-variance-authority`.
- No cloud dependency in the critical path — any network call should be opt-in and guarded.
