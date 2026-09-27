# Frontend auto-deploy: `frontend/` → Vercel `apix-dashboard`

Live URL: `https://apix-dashboard-navy.vercel.app` · Backend: `https://api.adityaai.dev`
Repo: `github.com/SameerKumar05/APIx`, production branch: `main`, app root: `frontend/`

## 1. Verdict (read-only inspection, 2026-09-27)

**Git integration is NOT enabled.** Evidence (no project setting was changed):

- `GET /v9/projects/apix-dashboard` returned `"link": null`,
  `"gitRepository": null`, `"productionBranch": null` — a Git-connected
  project would show a `link` object (`type: "github"`, `repo`, `org`) and a
  production branch (Vercel docs: production branch defaults to `main`).
- `vercel project inspect apix-dashboard` shows correct build settings but no
  Git section.
- The last deployments are all `"source": "cli"` — every deploy so far was a
  manual `vercel` CLI invocation, minutes before this check. Nothing deploys
  automatically today.

## 2. Recommendation

**Primary path: enable Vercel Git integration** (connect the GitHub repo in
the Vercel dashboard). It is the platform-native answer and strictly better
than a hand-rolled workflow for this project:

- Zero YAML: Vercel builds and deploys on every push; merges to the
  production branch (`main`) become production deployments automatically
  ([Deploying Git Repositories with Vercel](https://vercel.com/docs/git)).
- Every PR / non-production branch gets a **preview deployment** with its own
  branch-specific URL plus a commit-specific URL
  ([Environments](https://vercel.com/docs/deployments/environments)).
- Instant rollback is a domain-pointer update, not a rebuild
  ([GitHub Actions with Vercel](https://vercel.com/kb/guide/how-can-i-use-github-actions-with-vercel)).
- No token stored in the repo. Vercel's own guidance is explicit: *"most
  teams need no pipeline at all"* — add Actions only for tests, scans,
  performance budgets, or approval gates, i.e. things Vercel does not run.

**Fallback (implemented now): `.github/workflows/deploy-frontend.yml`.**
Connecting Git needs a human with Vercel dashboard access (install the GitHub
App, pick the repo), so until that happens pushes to `main` would deploy
*nothing*. The fallback workflow closes that gap with one secret and is
designed to be deleted the moment Git integration goes live. Tradeoff,
honestly stated:

| | Git integration (recommended) | Fallback CLI workflow |
|---|---|---|
| PR previews + bot comments | Automatic, per-PR URLs | None (production-only) |
| Rollback | Instant pointer update | Redeploy an older SHA manually |
| CI gating | Via Deployment Checks reading GitHub check runs | Via `workflow_run` on CI success |
| Secrets | None in repo | Static `VERCEL_TOKEN` to rotate |
| Build caching | Vercel-managed | Runner-side, manual |
| Double-deploy risk | — | Must delete this file once Git is connected |

## 3. Vercel project settings (verified current — keep pinned)

| Setting | Value | Verified |
|---|---|---|
| Root Directory | `frontend` | yes (`rootDirectory`) |
| Framework Preset | Vite | yes |
| Install Command | `bun install` | yes |
| Build Command | `bun run build` (`tsc -b && vite build`) | yes |
| Output Directory | `dist` | yes |
| `frontend/vercel.json` SPA rewrite `/(.*)` → `/index.html` | present | yes — required; the Vite preset does NOT do SPA fallback automatically |
| Env `VITE_API_BASE_URL=https://api.adityaai.dev` | production only | yes (target `['production']`) |
| Package manager | Bun (`frontend/bun.lock`, `lockfileVersion: 2`, needs bun ≥ 1.3) | yes — Vercel auto-detects Bun from the lockfile |

Do **not** commit `VITE_API_BASE_URL` (or any env value) to the repo: Vite
bakes `import.meta.env` at **build time**, so the value must exist as a
Vercel project env var, and changing it requires a new deploy.

## 4. How to connect Git integration (human step, ~5 min)

1. Vercel dashboard → `apix-dashboard` → Settings → Git → **Connect** →
   install the Vercel GitHub App on `SameerKumar05/APIx` (repo is currently
   connected to nothing, so this is a fresh connect, not a re-link).
2. Production Branch → `main` (Settings → Environments → Production →
   Branch Tracking). Default selection order is `main` first anyway.
3. Confirm Root Directory `frontend` plus the Build/Install/Output values in
   §3 when the import wizard asks (it should auto-detect Vite + Bun).
4. Push to `main` (or open a test PR): a production deployment should appear
   with **source = git** in the dashboard, and the PR should get a preview
   URL comment.
5. **Then delete `.github/workflows/deploy-frontend.yml`** (or, if you want
   to keep Actions as the deployer instead, set
   `"git": {"deploymentEnabled": false}` in `frontend/vercel.json` — never
   both active, or every push deploys twice).

## 5. Preview domains and the CORS coupling (operational consequence)

- Production deploys (Git `main` merges, or the fallback workflow's
  `vercel deploy --prebuilt --prod`) are promoted to the **same production
  domains** (`apix-dashboard-navy.vercel.app`) → the browser origin does not
  change → **no backend change needed**.
- Git-integration **preview** deployments get **different generated URLs per
  branch/commit** (branch-specific + commit-specific). Those are *different
  origins*. The backend (`https://api.adityaai.dev`) CORS allowlist
  (`BACKEND_CORS_ORIGINS`) must name the **exact** frontend origin, so:
  - Previews calling the real API will fail CORS unless the preview origin
    is added to `BACKEND_CORS_ORIGINS` on the VM (and Caddy/proxy reloaded
    as applicable), or the preview is pointed at a staging API.
  - Any **new permanent frontend domain** (custom domain, or a
    Git-integration-generated replacement of the current URL) likewise
    requires a `BACKEND_CORS_ORIGINS` update on the VM — treat
    frontend-domain changes as a coupled backend change.

## 6. Fallback workflow: what it does and what a human must configure

`.github/workflows/deploy-frontend.yml` (CLI `--prebuilt` pattern straight
from [Vercel's official guide](https://vercel.com/kb/guide/how-can-i-use-github-actions-with-vercel)
and the [`vercel deploy` CLI reference](https://vercel.com/docs/cli/deploy)):

- Trigger: `workflow_run` on `APIx CI / Quality Gate` completing with
  `conclusion == success` on `main`, plus a same-repo gate
  (`head_branch == 'main'` and `head_repository.full_name == the repo` --
  required because this repo is public: a fork PR from a fork branch *named*
  `main` would otherwise pass the branch/conclusion gates with an attacker
  `head_sha`, and `vercel build` executes the checked-out code under
  `VERCEL_TOKEN`), plus manual `workflow_dispatch`. It checks out the
  **CI-tested SHA** (`head_sha`), not the branch tip, and skips backend-only
  pushes (no `frontend/` changes → success with no deploy).
- `concurrency: group: deploy-frontend-production, cancel-in-progress: false`
  — production deploys queue; never cancel one mid-promotion.
- `vercel pull --yes --environment=production` → `vercel build --prod` →
  `vercel deploy --prebuilt --prod`, all non-interactive, authed via the
  `VERCEL_TOKEN` job env var (never a `--token` command-line flag, never
  echoed; masked in logs). `--prebuilt` means Vercel does **not** rebuild —
  one build, in the runner.
- All third-party actions pinned to full commit SHAs (checkout v4, setup-node
  v5, setup-bun v2 — SHAs recorded in comments).
- `VITE_API_BASE_URL` is set as a (public, client-baked) workflow env var so
  the runner-side `vercel build` embeds the same value as the Vercel project
  env; keep the two in sync.

**Human setup (fallback only):**

1. Create a Vercel token with access to the `aditya-ai-architects-projects`
   scope (`vercel tokens add`, ideally scoped to `apix-dashboard`) and store
   it as the repository secret **`VERCEL_TOKEN`**
   (repo Settings → Secrets and variables → Actions). No other secret is
   needed: `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID` are non-secret identifiers
   already in the workflow.
2. Nothing else — no dashboard change, no VM/SSH/Caddy change, no new
   domain, so **no CORS update** (production domains unchanged).
3. Ongoing: rotate `VERCEL_TOKEN` when team members leave (Vercel has no
   OIDC for deploy auth as of 2026-08 — static token it is).

## 7. Validation

- `deploy-frontend.yml` and `deploy-backend.yml`: validated with
  `actionlint` v1.7.12 on 2026-09-27 — **clean, zero findings** on both files
  (exit 0). Covered by the lint: `on.workflow_run.workflows` names the real
  CI workflow `APIx CI / Quality Gate`; `concurrency` present;
  `VERCEL_TOKEN` only via `${{ secrets.VERCEL_TOKEN }}` in `env` (no secret
  value in file, no `--token` flag); all third-party actions pinned to full
  SHAs (checkout v4, setup-node v5, setup-bun v2 — SHAs verified to exist in
  their upstream repos, not forks, via the GitHub API).
- No mutation was performed on the Vercel project (read-only `project
  inspect` + `GET /v9/projects` + env/deployments list; no `link`,
  `connect`, `deploy`, or `project update` calls).
