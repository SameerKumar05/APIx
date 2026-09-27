# APIx backend auto-deploy (GitHub Actions → GCE over SSH)

Workflow: `.github/workflows/deploy-backend.yml`. Deploys the FastAPI backend
to the shared GCE VM (`/opt/apix`, compose project `apix-deploy`) on every
push to `main` **that passed CI**. Standing operational record of the manual
deploy: `docs/deployment_run_2026-09-26.md`. Frontend deploys are a separate
workflow owned separately.

## How the gate works

`workflow_run` on `APIx CI / Quality Gate` (types `[completed]`,
branches `[main]`) + job `if:` requiring `conclusion == 'success'` AND
`head_branch == 'main'` AND `head_repository.full_name == github.repository`.
The repo is public, so the same-repo check is load-bearing, not cosmetic: a
fork PR opened from a fork branch *named* `main` would satisfy
`branches:[main]` + `conclusion==success` while `head_sha` points at attacker
code (which this workflow would then rsync to the VM and `docker build` as
root). The workflow checks out `github.event.workflow_run.head_sha` -- the
exact commit CI blessed, not the branch tip (which may be newer).
`workflow_dispatch` allows manual re-deploys (always deploys; skips change
detection).

`concurrency: deploy-backend-production / cancel-in-progress: false`:
rapid pushes queue behind a running deploy instead of interleaving two
`docker compose` runs against one project.

## Required GitHub configuration (human setup)

Repository **Settings → Secrets and variables → Actions**:

| Name | Type | Value |
|---|---|---|
| `GCE_SSH_HOST` | secret | VM hostname or IP (currently `34.131.69.223`; prefer a stable hostname if one exists) |
| `GCE_SSH_USER` | secret | `adi-IL` |
| `GCE_SSH_PRIVATE_KEY` | secret | Contents of a **dedicated deploy-only** ed25519 key (see below), including `BEGIN`/`END` lines |
| `GCE_SSH_KNOWN_HOSTS` | secret | Output of `ssh-keyscan -t ed25519 <host>` for the VM (fail-closed host verification; the workflow uses `StrictHostKeyChecking yes` and never `accept-new`/`no`) |
| `GCE_SSH_PORT` | variable | `22` (optional; defaults to 22 when unset) |

Generate the deploy key OFF the VM and OFF any personal machine identity:

```bash
ssh-keygen -t ed25519 -f apix-deploy-key -N '' -C 'apix-gh-deploy'
# public half -> VM authorized_keys (see VM setup); private half -> GCE_SSH_PRIVATE_KEY
```

This must be a restricted deploy-only key, **not** anyone's personal SSH key.
Rotate it on any suspected leak by replacing both the secret and the VM entry.

## Required VM configuration (one-time, human)

As `adi-IL` on the VM (deploy user already has passwordless sudo):

```bash
# 1. restricted deploy key: this host only, non-interactive commands only
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cat >> ~/.ssh/authorized_keys <<'EOF'
restrict,pty,from="<github-runner-egress-or-jump-host>" <contents of apix-deploy-key.pub>
EOF
chmod 600 ~/.ssh/authorized_keys
# 2. confirm the tree and secrets the workflow depends on
ls -la /opt/apix/.env /opt/apix/docker-compose.yml /opt/apix/docker-compose.deploy.yml
stat -c '%a %n' /opt/apix/.env   # must be 600
sudo -n true                     # must succeed: passwordless sudo for docker
```

Notes:

- `restrict` disables port/agent/X11 forwarding; add `from="..."` scoping
  when the runner egress range is known. The workflow only needs
  `ssh` + `rsync` + passwordless `sudo docker ...`.
- The workflow asserts `/opt/apix/.env` exists before doing anything and
  rsync excludes `.env`, so a deploy can never delete or overwrite VM secrets.

## Deploy order on the VM (why it is this way)

1. `rsync --delete` (excludes: `.git .venv node_modules frontend/dist
   *.db evidence/ artifacts/ .env backups/ .vercel/`).
2. `up -d db` (idempotent) then `build backend` -- new image ready, old
   container still serving.
3. `run --rm --no-deps backend alembic upgrade head` with the synced
   `alembic.ini`/`migrations/` mounted read-only (the image does not ship
   them) -- **migrations complete before new code serves**. The lifespan's
   `create_all` swallows errors and never adds columns, so reversing steps
   3-4 would produce a "healthy" app whose full-row reads 503
   (`tests/test_migration_drift.py`).
4. `up -d backend` (recreate on the migrated schema).
5. Poll `http://127.0.0.1:8000/health` (DB-probing; 503 on stale schema)
   for ~5 min; on timeout dump `compose ps` + backend logs and exit 1.

Everything is scoped `-p apix-deploy -f docker-compose.yml
-f docker-compose.deploy.yml` with named services only. The workflow never
touches Caddy (`mcp.`/`review.` share it -- no validate/reload/restart),
never runs unscoped `down`, and never publishes the DB to the host.

## Rollback

Data survives in named volumes. If a deploy fails after migration:
`alembic downgrade` is deliberately NOT automated (unsafe without review).
Fix forward on `main` (CI + deploy re-run), or manually
`up -d backend` a previous image tag on the VM. Dated `pg_dump` backups per
`deployment_run_2026-09-26.md` §11 remain the safety net.
