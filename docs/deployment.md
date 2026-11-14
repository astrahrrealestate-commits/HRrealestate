# Deployment

Two separately deployable units, each with its own production Docker image. Infrastructure choice (which AWS
service, or any other host) is not decided yet — this page is the contract each side needs regardless of where it
runs: what image to build, what it needs at boot, and how the two talk to each other. Real provider credentials
(WhatsApp, Gmail, S3, BRIXX, the LLM) are [docs/go-live-channels.md](go-live-channels.md); this page is the
container/runtime side, not the credentials side.

## Backend (`docker/Dockerfile`)

One image, three roles picked by the command at run time — `docker/compose.yml` shows the exact invocation of each:

| Role | Command | Runs |
|---|---|---|
| migrate | `alembic upgrade head` | once per deploy, before `api`/`worker` start |
| api | `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000` | the FastAPI app |
| worker | `python -m app.worker` | DBOS workflows, queues, cron |

Build once, run the same image three ways:

```bash
docker build -f docker/Dockerfile -t estateos-backend .
```

Non-root user, read-only application layer (only `/app/.data` is writable, and that path is dev-only — prod refuses
local storage), digest-pinned base images. Needs `DATABASE_URL` (Postgres 16 + pgvector) and `ENV=prod`; startup
(`app/core/startup.py: production_problems`) refuses to boot under `ENV=prod` with any fake provider, local storage,
or a missing required secret — a half-configured deploy fails at boot, not silently. Each `worker` replica needs its
own `DBOS__VMID` (`docker/compose.yml` sets `worker-0`; a second replica needs a different id, ADR 0001).

## Frontend (`frontend/Dockerfile`)

Multi-stage production build (`npm run build` in a builder stage, Next's `output: "standalone"` server copied into a
minimal non-root runtime stage — not the dev server). Build with the public API origin baked in at build time
(`NEXT_PUBLIC_API_URL` is read client-side, so it must be a build arg, not a runtime environment variable):

```bash
docker build -f frontend/Dockerfile --build-arg NEXT_PUBLIC_API_URL=https://app.example.com -t estateos-frontend frontend
```

**Set `NEXT_PUBLIC_API_URL` to the SPA's own real public origin, always** — if it is left unset, the frontend code
falls back to `http://localhost:8000`, which only works on a dev machine. There is no "leave it empty for same
origin" option; set it explicitly even when both sides share a host.

## Wiring the two together

The default, and simplest, topology is **same-origin behind one reverse proxy**: the browser only ever talks to one
public host; the frontend's own server proxies `/api/*` to the backend (`frontend/next.config.ts`'s `rewrites()`,
using `INTERNAL_BACKEND_URL`, e.g. `http://backend:8000` on an internal network — never exposed publicly). This is
why `FRONTEND_BASE_URL` and `NEXT_PUBLIC_API_URL` end up equal in that topology: both name the one public origin.
Also set `GOOGLE_LOGIN_REDIRECT_URI` to that origin's `/api/auth/login/google/callback` if using Google login.

A split-host topology (separate `api.example.com` / `app.example.com`) also works, documented in `.env.example`
right above `DASHBOARD_CORS_ORIGINS` and `DASHBOARD_COOKIE_DOMAIN` — needed only if the two are not proxied
same-origin.

## CI already proves both images build

`.github/workflows/ci.yml`'s `image` job builds the backend image and runs a Trivy CVE scan on every push to
`main`/`stage`/`dev`; the `frontend` job runs `npx tsc --noEmit`, `npm run lint` (advisory) and `npm run build`. A
green `ci-success` check means both sides are known to build; it does not build or push the frontend Docker image
(no step does yet — add one once a registry/target exists).

## What is intentionally not decided here

Which AWS service runs each container (ECS/Fargate, EC2, App Runner, …), autoscaling, the load balancer / TLS
termination point, and a registry + push step for the frontend image are all open. This page gives the two images
and their contract so that choice can be made independently of application code.
