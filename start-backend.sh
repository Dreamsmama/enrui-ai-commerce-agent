#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "==> Backend: http://127.0.0.1:8000"
cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt
fi
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created backend/.env — please set LLM_API_KEY"
fi
exec .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
