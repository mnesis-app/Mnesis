# Contributing to Mnesis

Thank you for your interest in contributing. Mnesis is a local-first memory infrastructure project — every contribution helps make it more reliable, more private, and more useful.

## Before you start

- Read the [README](README.md) to understand the project's philosophy and architecture
- Check [open issues](https://github.com/mnesis-app/Mnesis/issues) to avoid duplicate work
- For significant changes, open an issue first to discuss the approach

## Development setup

### Prerequisites

- Node.js 20+
- Python 3.11+
- npm
- Git

### Install

```bash
git clone https://github.com/mnesis-app/Mnesis.git
cd Mnesis
npm install
pip install -r backend/requirements.txt
```

### Run in development

```bash
npm run dev          # Full stack: Electron + Vite + backend with hot reload
npm run dev:vite     # UI only (browser at http://127.0.0.1:5173)
npm run dev:backend  # Backend only (API at http://127.0.0.1:7860)
```

### Run tests

```bash
npm run test             # Frontend unit tests (vitest)
npm run test:backend     # Backend tests (pytest)
npm run check:v1         # V1 release gates
```

## Project structure

```
backend/         FastAPI app, MCP server, memory core, sync, insights
src/             React UI (TypeScript, Tailwind, Zustand, TanStack Query)
electron/        Electron shell (main, preload, tray)
tests/           Backend pytest suite
```

See [CLAUDE.md](CLAUDE.md) for the full architecture reference.

## Contribution guidelines

### Code style

- **Python**: async/await throughout, type hints on public functions, `pytest` for tests
- **TypeScript**: strict mode, prefer `hooks/` for data-fetching, no `any` without justification
- **CSS**: Tailwind utility classes; component variants via `class-variance-authority`
- **Commits**: conventional commits format (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`)

### Architecture invariants — do not break these

- **Local-first**: no mandatory cloud relay; any network call must be opt-in and guarded
- **Provider-agnostic**: not tied to any single LLM vendor
- **Traceable writes**: all memory writes must carry provenance fields
- **Status transitions explicit**: never bypass the memory lifecycle states
- **Vectors backend-only**: never return raw embeddings in frontend API payloads

### Pull requests

1. Fork the repository and create a branch from `main`
2. Keep PRs focused — one feature or fix per PR
3. Add tests for new backend functionality
4. Run `npm run test` and `npm run test:backend` before submitting
5. Update documentation if you change user-facing behaviour
6. Fill in the PR template

### Security vulnerabilities

**Do not open a public issue for security vulnerabilities.**

Report them privately via GitHub's [Security Advisory](https://github.com/mnesis-app/Mnesis/security/advisories/new) feature. Include a description of the vulnerability, steps to reproduce, and potential impact. We aim to respond within 72 hours.

## Licence

By contributing, you agree that your contributions will be licensed under the [GNU Affero General Public License v3.0](LICENSE).
