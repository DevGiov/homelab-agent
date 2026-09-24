# Agent Instructions & Workflow Protocol — homelab-agent

## Development Status & Code Principles
- **Active 'Dev' Stage**: We are in active development on the `dev` branch. The only real running instance is **CT 125** (`192.168.1.185` / `agent-dev.deggio.local`), which acts as our real test environment.
- **Clean Architecture & No Legacy Code**: Focus on high-quality, modern, well-structured code. **Avoid legacy code or backward-compatibility layers when they are not strictly necessary**. Do not accumulate obsolete shims or technical debt.
- **Breaking Changes Allowed**: Breaking changes are completely permitted whenever they improve code quality, simplicity, or system architecture. You are free to modify contracts, re-deploy services, rebuild containers, and completely wipe/reset legacy databases (e.g. SQLite databases) without hesitation in Dev.

## Available Diagnostic & Testing Tools
- **`proxmox-mcp` tools**:
  - `exec_lxc_command(vmid=125, command="...")`: Execute shell commands inside CT 125 (`git pull`, `docker compose`, `docker exec`).
  - `get_lxc_service_logs(vmid=125, ...)`: Inspect container logs.
- **Live API Testing**: Test REST and SSE streaming endpoints directly on CT 125 (`http://192.168.1.185:8090/v1/...` or `http://agent-dev.deggio.local/v1/...`).
- **Live UI Testing via Browser Subagent**: Use `browser_subagent` to open `http://agent-dev.deggio.local` (or `http://192.168.1.185`), interact with UI components, click elements, send chat prompts, and verify rendering, streaming, and responsive layout end-to-end.

## End-to-End Development & Verification Workflow
1. **Local Modification**: Implement changes cleanly in this repository on the `dev` branch.
2. **Local Validation**: Run local unit tests (`pytest`), linting (`ruff`), and frontend build (`npm run build`).
3. **Push to Remote**: `git push origin dev`
4. **Deploy & Rebuild in CT 125 via MCP**:
   - Pull updated branch:
     `exec_lxc_command(vmid=125, command="cd /opt/homelab-agent && git pull origin dev")`
   - Restart or rebuild services:
     - Backend code change: `exec_lxc_command(vmid=125, command="cd /opt/homelab-agent && docker compose -f docker-compose.prod.yml restart backend")`
     - Backend dependencies/Dockerfile: `exec_lxc_command(vmid=125, command="cd /opt/homelab-agent && docker compose -f docker-compose.prod.yml up -d --build backend")`
     - Frontend code change: `exec_lxc_command(vmid=125, command="cd /opt/homelab-agent && docker compose -f docker-compose.prod.yml up -d --build frontend")`
     - Database reset / breaking change: wipe legacy SQLite db if required and restart containers.
5. **In-Container Test Execution**:
   - Run tests inside container:
     `exec_lxc_command(vmid=125, command="docker exec agent-backend pytest")`
6. **Live API Testing**:
   - Verify health and target endpoints:
     `exec_lxc_command(vmid=125, command="curl -s http://localhost:8090/v1/health")`
7. **Live UI Verification (Browser Subagent)**:
   - Launch `browser_subagent` to test the web UI at `http://agent-dev.deggio.local`.
   - Test user workflows, modals, buttons, SSE streaming, and visual layout.
8. **Feedback Loop & Resolution**:
   - If bugs, regressions, or UI flaws are found: diagnose root cause, fix code locally, push, update CT 125, and re-test until fixed.
   - If severe or critical issues arise, compile a detailed diagnostic report before proceeding.
