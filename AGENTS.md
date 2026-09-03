# Polaris — Agent Guide

> [!CAUTION]
> **Never read or echo secret values.** When working with Doppler, `.env.example`, or any secrets-related command output, reference keys by name only — never print, log, or repeat computed secret values in responses or tool calls. Use `doppler secrets download` output only for structural comparisons (key presence, key equality checks) and discard values immediately. This applies to all secrets regardless of whether they appear sensitive — IPs, tokens, passwords, and API keys alike.

Self-hosted media + utilities infrastructure. Containerized services grouped
into isolated "gateway" clusters, orchestrated by a Python CLI, with encrypted
secrets and automated backups. See `README.md` for the full overview.

## Repo layout

```
manage.py              # Unified Python CLI (deploy/redeploy/stop/update/secrets/backup/network/hooks)
orchestrator/          # Modular Python orchestration engine (core, registry, docker, secrets, network, actions, ui, scripts)
orchestrator/ui/       # Interactive dashboard and TUI presentation layer (launched by `./manage.py` with no args)
orchestrator/scripts/hooks/ # Git hooks (pre-commit secret/state guard) + install-hooks.sh
Network/               # Core network stack: Gluetun + Tailscale + Caddy + AdGuard (host network gateway)
Utilities/             # Service gateway stacks: auth, monitoring, cloud, gateway, exit-node, etc.
Media/                 # Media gateway stacks: core, stremio, addons, comics, debrid
Docs/                  # Architecture and ops documentation — READ THESE FIRST
Archived/              # Decommissioned stacks (do not modify unless explicitly asked)
public-caddyfile-snippet.txt   # Public reverse-proxy snippet shared across VPS Caddyfiles
renovate.json          # Dependency automation config
                        # Runtime secrets are managed in Doppler SaaS
```

## Architecture Essentials & Networking Intricacies

- **Nested Gateway Pattern:** Most workloads run inside VPN-sidecar network
  namespaces (Gluetun + Tailscale), while `gateway-b` uses a Tailscale-only
  bridge and several agents use host networking. Apps in the same Gluetun
  cluster share its namespace via `network_mode: service:<gateway>`.
- **Intra-Gateway Localhost Rule:** Services in the **same gateway** share network namespace and MUST talk to each other via `127.0.0.1:<port>`, NOT container DNS names. Avoid `http://jellyfin:8096` between services in the same cluster.
- **Port Collision Prevention:** Because services in the same gateway share `127.0.0.1`, internal container ports inside a gateway namespace MUST be unique. Always audit existing `docker-compose.yml` files in that gateway directory before assigning ports.
- **Inter-Gateway & External Access:** Traffic *between* different gateways or across VPS targets must route via Tailscale MagicDNS (`https://<gateway>.<tailnet>.ts.net`) or host interfaces fronted by host Caddy reverse-proxies / Cloudflare Tunnels, NOT `127.0.0.1`.
- **Dual VPS Context:** Deployments target VPS 'A' or 'B'. Active VPS context is tracked in `.active_vps`. VPS-specific environment configurations live in Doppler projects `polaris-vps-a` and `polaris-vps-b`.
- **Hosting Reference Docs:** `Docs/CLI_GETTING_STARTED_GUIDE.md`, `Docs/NETWORK_ARCHITECTURE.md`, `Docs/TAILSCALE_URLS.md`, `Docs/CLOUDFLARE_TUNNEL.md`, and `Docs/DOPPLER_OPERATIONS_GUIDE.md`.

## Secrets & State Intricacies

- **Doppler SaaS Secret Management Workflow:**
  1. Secrets are managed centrally in Doppler SaaS (`polaris-vps-a` and `polaris-vps-b`).
  2. To verify Doppler authentication: run `./manage.py secrets verify`.
   3. Secrets are injected at runtime via `doppler run`. Compose `environment` entries receive process variables, while services that declare `env_file` receive a temporary `0600` `.env` which is removed after the command.
  4. Never paste secret values into code/PRs or commit unencrypted secrets.
  5. For historical SOPS scripts/ciphertext restoration from git history, see `Docs/DOPPLER_MIGRATION_COMMIT_REFERENCE.md`.
- **Doppler Inheritance Structure (VPS A):** `prd` is the global root containing 11 universal keys (IPs, `TZ`, `PUID`, `PGID`, `MEDIA_SHARE`, `TAILNET_SUFFIX`). All environment configs (`admin`, `auth`, `local_media`, etc.) inherit from `prd`. Child service configs inherit from their parent environment. The `backup` env owns its own keys independently. Services with custom `PUID`/`PGID` override explicitly at the service config level.
- **`secrets prune` Limitation:** The Doppler CLI does not expose whether a key is explicitly set or merely inherited — `doppler secrets download` returns fully-resolved values regardless of source. The prune tool therefore cannot distinguish inherited keys from explicit ones and will over-report counts. **Always use the Doppler UI** (which shows the source config per key) to verify redundant explicit entries before running `./manage.py secrets prune`. Only run it when configs have known explicit duplicates from a migration or bulk-copy operation — not for routine maintenance.
- **Runtime Data & Volume Protection:** Never edit databases (`*.db`), runtime state files, or live container volumes inside `data/` or `state/` manually. Use `./manage.py backup` for volume snapshots.
- **Archived/ Directory:** `Archived/` contains historical reference stacks. Never attempt to "fix", update, or run compose commands inside `Archived/`.

## Workflow & Development Rules

- **Workflow Strategy:** 
  - **Big Picture / Multi-Stack Changes:** Create a clear implementation plan first outlining architecture, compose changes, and env variables before touching code.
  - **Direct Fixes / Single-Stack Edits:** Implement directly and cleanly.
- **Pre-PR Workflow Execution (Strict):** Always run and verify all local workflows, lint/build checks, and compose validations (`docker compose config`) **before creating any PR or requesting code review**.
- **New Service Addition Checklist:**
  1. Define service in the appropriate stack compose file under `Utilities/` or `Media/`.
  2. Ensure `network_mode: service:<gateway>` and verify no port collisions exist on `127.0.0.1`.
   3. Add variable keys with safe defaults to `.env.example`, create the matching Doppler config, and populate production values there.
  4. Update `Network/Caddyfile` or `public-caddyfile-snippet.txt` if public/Tailscale routing is required.
  5. Validate compose config (`docker compose config`) and verify Doppler authentication (`./manage.py secrets verify`).

## Common Commands

```bash
./manage.py                       # Interactive TUI dashboard
./manage.py deploy [svc ...]      # Deploy stacks or specific apps (e.g. bazarr sonarr, --vps A|B, --last)
./manage.py redeploy [svc ...]    # Refresh active containers or specific apps (--build, --recreate)
./manage.py stop [svc ...]        # Stop running containers (all, --vps A|B, or specific apps like jellyfin)
./manage.py backup snapshots      # List Restic backup snapshots
./manage.py backup stats          # Inspect repository storage statistics & compression (--mode raw-data)
./manage.py backup prune          # Enforce retention and prune unused blobs (--max-unused 10%)
./manage.py backup restore        # Restore from snapshot (prompts unless --yes; confirms BEFORE decrypt)
./manage.py status                # Real-time container health & port inspector (--vps A|B, --json)
./manage.py logs <service>        # Stream container logs by short service name (-f, --tail=N)
./manage.py doctor                # Pre-flight infrastructure diagnostics (Doppler, VPN, Tailscale)
./manage.py validate              # Validate Compose & Caddyfile configs across repository
./manage.py history               # View persistent operation audit history log (--json)
./manage.py secrets verify        # Verify Doppler CLI authentication
./manage.py secrets open          # Open the Doppler dashboard
./manage.py secrets snapshot      # Refresh offline SOPS/age encrypted fallback snapshots (--vps A|B)
./manage.py secrets snapshots     # List offline encrypted snapshot inventory
./manage.py secrets sync-branch   # Automated snapshot sync to dedicated git branch via worktree
./manage.py network fix           # Repair Tailscale/gateway network state
./manage.py hooks install         # Install the pre-commit secret/state guard (run once per clone)
./manage.py hooks verify         # Check the pre-commit hook is installed
./manage.py cli install           # Install system-wide 'polaris' CLI wrapper (or ./install-cli.sh)
./manage.py cli verify            # Verify 'polaris' CLI wrapper installation status
# Global flag on all mutating subcommands: --yes / -y auto-confirm destructive prompts (scripts/CI)
```

Execute `./manage.py` from the repository root or run `polaris` from any directory on the host once installed via `./install-cli.sh`. Prefer CLI commands over raw `docker compose` calls to maintain active VPS and gateway state.

## Defense-in-depth: hooks & extensions

Secret/state protection is layered (lowest layer is the guarantee):

1. **Doppler SaaS at rest** — runtime secrets are stored centrally and injected at process start; any required transient `.env` is restricted to `0600` and cleaned after the command.
2. **`pre-commit` git hook** (`orchestrator/scripts/hooks/pre-commit`, installed via `./manage.py hooks install`) — blocks ANY committer (human, agent, CI) from staging decrypted `.env`, `.env.vps-*`, `keys.txt`, `secrets/`, `state/`, `data/`, `*.db*`, `Archived/`. Templates (`.env.example`) and ciphertext (`.env.enc`) pass. Escape hatch: `git commit --no-verify`. Must be installed per-clone (not auto-installed — no hook framework dependency by design).
3. **`manage.py` confirm gates** — `stop`, `redeploy --build`/`--recreate`, `deploy --force-gateways`, `backup restore` prompt before acting; `--yes`/`-y` auto-confirms (CI). Restore confirms BEFORE decrypting, so declining never writes secrets to disk.
4. **`.pi/extensions/` (pi agent only)** — `secrets-guard.ts` blocks the agent from read/edit/bash on runtime secrets; `protected-paths.ts` blocks writes to state/DBs/Archived; `confirm-destructive.ts` gates destructive `docker`/`git` commands. These are a pi-scoped backstop — do NOT treat them as the layer that prevents leaks; Doppler and the hook do that.

## Conventions

- **Docker Compose:** v2 syntax (`services:` top-level key). Pin image tags to specific stable versions where supported. Avoid `:latest` for production app images. Set `restart: unless-stopped` by default.
- **Env Variables:** `UPPER_SNAKE_CASE`. Provide inline fallback defaults (`${VAR:-default}`). Document every variable in `.env.example`.
- **Python Code:** 3.10+. Runtime dependencies are pinned in `requirements.txt`; test and lint dependencies are pinned in `requirements-dev.txt`.
- **Git & Commits:** Conventional Commits with scopes (`feat(cli):`, `fix(tui):`, `docs(network):`, `chore(deps)`).
  - **Branch Protection & PR Requirement:** Direct pushes to `main` are blocked by GitHub branch protection rules. All work must be developed on a non-main branch (e.g. `feat/*`, `fix/*`, `docs/*`, `chore/*`, or any custom branch name) and submitted via Pull Request so GitHub Actions CI workflows (`validate-compose`, `python-ci`, `gitleaks-scan`, `security-scan`) can validate changes before merging. PRs are squash-merged into `main`.
  - **Detailed Commit Messages:** Commit titles follow `type(scope): summary`. The commit body must include a clear, detailed breakdown explaining **what changed and why**.

## Before You Submit a PR / Complete a Task

1. **Branch Check:** Verify current branch is NOT `main` (`main` is protected; use any non-main feature/topic branch).
2. **Unit Tests:** Execute unit tests (`python3 -m unittest discover -s orchestrator/tests -v`).
3. **Compose & Caddy Validation:** Run `./manage.py validate` to ensure all active Compose projects and Caddy routing pass validation checks.
4. **Secrets & Environment Guard:** Verify Doppler authentication (`./manage.py secrets verify`) and confirm no decrypted `.env`, `keys.txt`, or `state/` files are present in `git status`.
5. **Git Hooks:** Confirm the pre-commit secret guard is active (`./manage.py hooks verify`).
6. **Detailed Commit:** Commit with a clear title and a detailed message body explaining what changed and why, then push to `origin <branch>`.
7. **CI / PR Checks:** Ensure PR satisfies all GitHub Actions CI checks (`validate-compose.yml`, `python-ci.yml`, `gitleaks-scan.yml`, `security-scan.yml`).

## Strict Don'ts

- Don't push directly to `main` — `main` is protected by GitHub branch rules; always develop on non-main branches and submit a PR.
- Don't write short/vague commit messages — always detail what changed and why in the commit message body.
- Don't expose container ports directly on host interfaces for cluster-internal services.
- Don't use container DNS names (e.g. `http://authelia:9091`) between services sharing a gateway network namespace.
- Don't run manual `docker compose up` commands during managed deployments; use `./manage.py`.
- Don't edit `Archived/` or live database files in `state/` / `data/` by hand.
- Don't commit decrypted `.env` files, age private keys, or `keys.txt`.
- Don't bypass the pre-commit hook with `git commit --no-verify` for files that are genuinely secrets/state — the hook exists to prevent leaks; only bypass for a verified false positive.
- Don't bump image tags without reviewing release notes.
- Don't open or submit a PR without executing local validation workflows and unit tests first.
