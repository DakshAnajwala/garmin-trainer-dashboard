#!/bin/bash
# Runs both the backend (FastAPI, :8000) and frontend (Vite, :5173) for the
# dashboard. Run this yourself in your own terminal — Ctrl+C stops both.
set -e
cd "$(dirname "$0")"

cleanup() {
  echo "Stopping..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
}
trap cleanup EXIT

source .venv/bin/activate
uvicorn api.main:app --reload --port 8000 &
BACKEND_PID=$!

(cd frontend && npm run dev) &
FRONTEND_PID=$!

echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop both."

wait
