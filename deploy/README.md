# Deployment — AWS ECS (per-service)

Each part of the platform deploys as its own ECS service, from its own image
in its own ECR repository. This directory holds everything needed to build and
deploy them independently.

## Layout

```
deploy/
├── backend/
│   ├── Dockerfile          # one image for api + worker + beat + migrate
│   └── .dockerignore
├── frontend/
│   ├── Dockerfile          # build (Vite) + serve (Nginx), proxies /api
│   ├── nginx.conf
│   └── .dockerignore
├── ecs/
│   ├── api.task.json       # uvicorn, behind ALB on :8000
│   ├── worker.task.json    # celery worker, no LB
│   ├── beat.task.json      # celery beat, no LB, exactly 1 task
│   ├── migrate.task.json   # one-off alembic upgrade
│   └── frontend.task.json  # nginx, behind ALB on :80
├── env/
│   ├── backend.env.example
│   └── frontend.env.example
└── jenkins/
    ├── Jenkinsfile.api       # build backend + migrate + deploy api
    ├── Jenkinsfile.worker    # build backend + deploy worker
    ├── Jenkinsfile.beat      # build backend + deploy beat
    └── Jenkinsfile.frontend  # build frontend + deploy frontend
```

## Images and ECR repositories

| Image | ECR repo | Runs as |
|-------|----------|---------|
| Backend | `repo_saas_dev_backend` | api, worker, beat, migrate (same image, different command) |
| Frontend | `repo_saas_dev_frontend` | frontend (Nginx) |

The backend uses **one image** across four ECS task definitions — each just
overrides the container `command`. This keeps builds simple: build once, run
everywhere.

## ECS services

| Service | Task def | Load balanced | Count |
|---------|----------|:---:|:---:|
| `repo_saas_dev_api` | `api.task.json` | Yes (ALB → :8000) | 1+ |
| `repo_saas_dev_worker` | `worker.task.json` | No | 1+ |
| `repo_saas_dev_beat` | `beat.task.json` | No | **1** |
| `repo_saas_dev_frontend` | `frontend.task.json` | Yes (ALB → :80) | 1+ |
| migrate | `migrate.task.json` | run-task only | — |

> **Beat must stay at exactly 1** — multiple schedulers would fire duplicate
> periodic tasks.

## Build commands

Run from the repo root.

```bash
# Backend (context = repo root)
docker build -f deploy/backend/Dockerfile \
  -t <acct>.dkr.ecr.ap-south-2.amazonaws.com/repo_saas_dev_backend:<tag> .

# Frontend (context = repo root; Dockerfile copies from frontend/)
docker build -f deploy/frontend/Dockerfile \
  -t <acct>.dkr.ecr.ap-south-2.amazonaws.com/repo_saas_dev_frontend:<tag> .
```

## Jenkins pipelines (one per service)

Each service has its own Jenkinsfile in `deploy/jenkins/`, so any service can
be built and deployed independently. Create one Jenkins Pipeline job per file,
pointing "Script Path" at the file below.

| Service | Jenkinsfile | What it does |
|---------|-------------|--------------|
| API | `deploy/jenkins/Jenkinsfile.api` | build backend image → push → **run migrations** → deploy api |
| Worker | `deploy/jenkins/Jenkinsfile.worker` | build backend image → push → deploy worker |
| Beat | `deploy/jenkins/Jenkinsfile.beat` | build backend image → push → deploy beat |
| Frontend | `deploy/jenkins/Jenkinsfile.frontend` | build frontend image → push → deploy frontend |

Notes:
- The **API pipeline owns migrations** (runs `alembic upgrade head` as a
  one-off task before deploying). Worker/beat pipelines skip migrations to
  avoid racing.
- All three backend pipelines build+push the same `repo_saas_dev_backend`
  image. Deploy the API first when schema changes are involved, then worker/beat.
- Each pipeline ends by waiting for its service to reach steady state.

## ALB architecture

Everything routes through Application Load Balancers.

```
                 Internet
                    │
          ┌─────────▼──────────┐
          │  Public ALB        │  :443 / :80
          │  (frontend)        │
          └─────────┬──────────┘
                    │  → repo_saas_dev_frontend target group (:80, nginx)
                    │
   Nginx proxies /api/*  ──────────────┐
                                        ▼
                          ┌─────────────────────────┐
                          │  Internal ALB            │  :80
                          │  (api)                   │
                          └────────────┬─────────────┘
                                       │ → repo_saas_dev_api target group (:8000)
```

- **Frontend** sits behind a public ALB (443/80 → container :80).
- **API** sits behind an internal ALB (:80 → container :8000).
- **Worker** and **Beat** have no ALB — they only talk to Redis/DB.

## How the frontend reaches the backend

The React app calls `/api/v1/...` (relative). The Nginx image proxies `/api/`
to the internal API ALB, controlled by the `API_UPSTREAM` env var on the
frontend task definition:

```
API_UPSTREAM=http://internal-repo-saas-dev-alb.ap-south-2.elb.amazonaws.com
```

Set it to your **internal API ALB's DNS name**. Because the frontend proxies
through Nginx, the browser only ever talks to the public frontend ALB — the API
ALB stays internal.

## Environment / secrets

- Plain config lives in each task definition's `environment` block.
- Secrets (DB URL, Redis URL, JWT keys) come from AWS Secrets Manager via the
  `secrets` block, under `/dev/repo_saas/*`.
- `deploy/env/*.example` document every variable for reference and local runs.

## Local development

Local dev is unchanged — use the root `docker-compose.yml` and root
`Dockerfile` (multi-stage) with `docker compose up`. The `deploy/` images are
for ECS only.
