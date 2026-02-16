# GLH Timer

Mobile-first timing app for Go Like Hell Triathlon Club.

## Quickstart

1. Set env vars: `DATABASE_URL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`.
2. Install deps: `pip install -r requirements.txt` (or `pip install .`).
3. Run: `uvicorn app.main:app --reload`.

## Docker

`docker compose up --build`

## CI/CD (GitHub Actions -> DockerHub)

This repo now includes `.github/workflows/build-push-dockerhub.yml`.

On every push to `main` (including merges), it will:
1. Build the Docker image.
2. Tag it as `<run_id>_<commit_id>` (using first 12 chars of the commit SHA).
3. Push both the immutable tag and `latest` to DockerHub.

Configure these GitHub repository settings before running the workflow:

Repository variables:
- `DOCKERHUB_IMAGE` (example: `youruser/glh-timer_v2`)

Repository secrets:
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
