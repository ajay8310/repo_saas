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
└── env/
    ├── backend.env.example
    └── frontend.env.example
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

## Deploy flow (per push)

1. Build + push both images to their ECR repos (tag = git SHA).
2. Register the updated task definitions (substitute `{{IMAGE_TAG}}`).
3. Run the migrate task once (`aws ecs run-task`), wait for exit code 0.
4. Update the api, worker, beat, frontend services with `--force-new-deployment`.
5. Wait for the api + frontend services to reach steady state.

See the `Jenkinsfile` at the repo root for the automated pipeline.

## How the frontend reaches the backend

The React app calls `/api/v1/...` (relative). In production the Nginx image
proxies `/api/` to the backend API, controlled by the `API_UPSTREAM` env var
on the frontend task (default `http://repo-saas-dev-api.internal:8000`). Set it
to your API service's internal address — ECS Service Connect / Cloud Map DNS,
or an internal ALB.

## Environment / secrets

- Plain config lives in each task definition's `environment` block.
- Secrets (DB URL, Redis URL, JWT keys) come from AWS Secrets Manager via the
  `secrets` block, under `/dev/repo_saas/*`.
- `deploy/env/*.example` document every variable for reference and local runs.

## Local development

Local dev is unchanged — use the root `docker-compose.yml` and root
`Dockerfile` (multi-stage) with `docker compose up`. The `deploy/` images are
for ECS only.
