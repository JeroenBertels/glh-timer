#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi
uvicorn app.main:app --reload
