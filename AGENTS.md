# Agent Instructions & Workflow Protocol — homelab-agent

## Development Status & Code Principles
- **Active 'Dev' Stage**: We are in active development on the `dev` branch; `main` receives the releases. The maintainer runs one live instance of `dev`, which acts as the real test environment (see "This repository and the installation").
- **Clean Architecture & No Legacy Code**: Focus on high-quality, modern, well-structured code. **Avoid legacy code or backward-compatibility layers when they are not strictly necessary**. Do not accumulate obsolete shims or technical debt.
- **Breaking Changes Allowed**: Breaking changes are completely permitted whenever they improve code quality, simplicity, or system architecture. You are free to modify contracts, re-deploy services, rebuild containers, and completely wipe/reset legacy databases (e.g. SQLite databases) without hesitation in Dev.

## This repository and the installation
This repository describes the software, not the place where it runs. Keep it that way:

- **No addresses, host names or container ids of a real installation** in code, configuration, scripts, CI or instructions. Service addresses are settings: they are read from `backend/.env`, documented in `backend/.env.example` with placeholder values, and their defaults in `backend/app/core/config.py` are neutral (`localhost`, or empty meaning "feature off"). `backend/tests/test_config_defaults.py` fails if a default points at a private network.
- **Tests, eval cases, prompts and UI examples use invented values.** They must pass on a machine that has never seen the maintainer's network. Files that hold such examples are listed in `.env-specific-allow`.
- **Instructions that are true for one installation only** (where the live instance runs, its URL, how to reach its shell) live in `AGENTS.local.md` in the repo root. That file is gitignored and optional. Read it if it exists. If it does not, do the local steps of the workflow below and skip the ones marked *live instance*.

## Available Diagnostic & Testing Tools
- **Local**: `make test` (pytest + Vitest), `make lint` (ruff + oxlint), `make test-container` (pytest in the isolated test image).
- **Live instance** (needs `AGENTS.local.md`): a shell and the container logs on the machine that runs the stack; REST and SSE endpoints under `/v1/...`; the web UI, to drive with a browser subagent (click elements, send chat prompts, verify rendering, streaming and responsive layout end-to-end).

## End-to-End Development & Verification Workflow
1. **Local Modification**: Implement changes cleanly in this repository on the `dev` branch.
2. **Local Validation**: `make test` (pytest + Vitest), `make lint` (ruff + oxlint), and frontend build (`npm run build`). Recreate the backend venv with `make venv` (Python 3.12, same as Docker/CI).
3. **Push to Remote**: `git push origin dev`
4. **Deploy & Rebuild** (*live instance*; run in the checkout directory on that machine):
   - Pull updated branch: `git pull origin dev`
   - If the change adds or renames a setting, add it to `backend/.env` there before restarting.
   - Restart or rebuild services:
     - Backend code change: `docker compose -f docker-compose.prod.yml restart backend`
     - Backend dependencies/Dockerfile: `docker compose -f docker-compose.prod.yml up -d --build backend`
     - Frontend code change: `docker compose -f docker-compose.prod.yml up -d --build --no-deps frontend` (`--no-deps`: otherwise compose also recreates `backend` when its image changed, resetting the active model to the `.env` default)
     - Database reset / breaking change: wipe legacy SQLite db if required and restart containers.
5. **In-Container Test Execution** (*live instance*, or any machine with Docker):
   - Run tests in the isolated `backend-test` container (test image target, `/data` on tmpfs, never the production volume):
     `docker compose -f docker-compose.prod.yml run --rm --build backend-test`
   - Pass pytest args after the service name (e.g. `... run --rm backend-test tests/test_x.py -q`; live tests: `... run --rm backend-test -m live`).
   - Never run `pytest` inside `agent-backend`: it has no test dependencies and its `/data` is the production data.
6. **Live API Testing** (*live instance*):
   - Verify health and target endpoints: `curl -s http://localhost:8090/v1/health` on the machine that runs the stack.
7. **Live UI Verification (Browser Subagent)** (*live instance*):
   - Launch `browser_subagent` to test the web UI at the URL given in `AGENTS.local.md`.
   - Test user workflows, modals, buttons, SSE streaming, and visual layout.
8. **Feedback Loop & Resolution**:
   - If bugs, regressions, or UI flaws are found: diagnose root cause, fix code locally, push, update the live instance, and re-test until fixed.
   - If severe or critical issues arise, compile a detailed diagnostic report before proceeding.
