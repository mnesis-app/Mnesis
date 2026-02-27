# Changelog

All notable changes to Mnesis are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [0.1.0] — 2026-02-26

### Initial public release

#### Core memory system
- Memory write/read/update/delete with full lifecycle management (pending → accepted/archived/deleted)
- Importance and confidence scoring with configurable decay
- Provenance tracking on every memory (source LLM, conversation ID, message ID, excerpt)
- Conflict detection and resolution UI
- LanceDB vector store for semantic search; KuzuDB graph for relationship traversal

#### MCP integration (15 tools)
- `memory_write`, `memory_read`, `memory_update`, `memory_delete`, `memory_list`
- `context_snapshot`, `memory_bootstrap`, `memory_feedback`, `memory_graph_search`
- `get_pending_conflicts`
- `conversation_search`, `conversation_list`, `conversation_ingest`, `conversation_sync`
- `note_exchange` — explicit user/assistant message capture
- Auto-configuration for Claude Desktop, Cursor, and other MCP clients
- Bearer token authentication with scoped access (read / write / sync)
- Resilient stdio-to-SSE bridge (Rust/Python, compiled binary)

#### User interface (8 views)
- Dashboard — memory stats, background job status, health panel
- Memories — inbox with filtering, semantic search, bulk actions
- Graph — force-directed visualization of memory relationships
- Conversations — imported conversation history with MCP trace display
- Import/Export — ChatGPT export ingestion, generic JSON import
- Conflicts — side-by-side conflict resolution
- Add Memory — manual memory creation
- Settings — tab-based layout (MCP / Insights / Sync / Dev)

#### Onboarding
- Multi-step profile seeding (name, profession, focus, communication style, constraints)
- First-run model download and embedding initialization
- Optional sync setup during onboarding

#### Remote sync (opt-in, E2E encrypted)
- Providers: AWS S3, Cloudflare R2, WebDAV (Nextcloud, ownCloud)
- AES encryption with passphrase-derived key before upload
- Full state coverage: memories, conversations, conflicts, graph edges

#### AI insights (opt-in)
- Conversation analysis: topic extraction, memory suggestions, category evolution
- Providers: OpenAI, Anthropic, Ollama
- Configurable analysis window and scheduling

#### Electron shell
- macOS (Apple Silicon + Intel) and Windows packaging
- Auto-update via electron-updater + GitHub Releases
- System tray with conflict count badge
- Splash screen with startup progress

#### Security
- Rate limiting (sliding window, per-bucket)
- Scoped MCP authentication — every tool validates its required scope
- Timing-safe token comparison (`hmac.compare_digest`)
- Content Security Policy in Electron renderer and FastAPI responses
- Config file hardening (chmod 0o600 / 0o700)
- HTTPS enforcement for WebDAV sync URLs
- URL protocol validation for `openExternal` (http/https only)
- Zero telemetry — no analytics, no crash reporting, no usage data

[0.1.0]: https://github.com/mnesis-app/Mnesis/releases/tag/v0.1.0
