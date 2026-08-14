#!/usr/bin/env bash
# ===========================================================
#  DataPilot AI - one-click launcher (macOS / Linux)
#
#  Run:  ./start.sh          start everything
#        ./start.sh reset    wipe chat history + demo data
# ===========================================================
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '  %s\n' "$*"; }

printf '\n  DataPilot AI\n  ============\n\n'

if [ "${1:-}" = "reset" ]; then
  say "Resetting demo data..."
  rm -f backend/data/*.db backend/db/*.db 2>/dev/null || true
  say "Done - the database will be re-seeded on the next start."
  printf '\n'
fi

# ---------- prerequisites ----------
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  say "[X] Python not found. Install Python 3.11+ and try again."
  exit 1
fi

PKG=""
for candidate in bun npm; do
  if command -v "$candidate" >/dev/null 2>&1; then PKG="$candidate"; break; fi
done
if [ -z "$PKG" ]; then
  say "[X] Neither Bun nor Node.js found. Install Node.js LTS and try again."
  exit 1
fi

# ---------- backend deps ----------
if [ ! -x "backend/.venv/bin/python" ]; then
  say "[1/4] Creating Python environment (first run only, ~1 min)..."
  "$PY" -m venv backend/.venv
  say "      Installing backend packages..."
  backend/.venv/bin/python -m pip install --quiet --upgrade pip
  backend/.venv/bin/python -m pip install --quiet -r backend/requirements.txt
else
  say "[1/4] Python environment ready."
fi

# ---------- frontend deps ----------
if [ ! -d "frontend/node_modules" ]; then
  say "[2/4] Installing frontend packages (first run only, ~2 min)..."
  (cd frontend && "$PKG" install)
else
  say "[2/4] Frontend packages ready."
fi

# ---------- .env ----------
if [ ! -f backend/.env ] && [ -f backend/.env.example ]; then
  cp backend/.env.example backend/.env
  say "      Created backend/.env - add an API key there for full AI mode."
  say "      Without one the app still works using the offline engine."
fi

# ---------- launch ----------
cleanup() {
  printf '\n  Stopping DataPilot...\n'
  kill ${API_PID:-} ${WEB_PID:-} 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

say "[3/4] Starting API on http://localhost:8000 ..."
(cd backend && ../backend/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000) \
  >/tmp/datapilot-api.log 2>&1 &
API_PID=$!

say "[4/4] Starting web app on http://localhost:8080 ..."
(cd frontend && "$PKG" run dev) >/tmp/datapilot-web.log 2>&1 &
WEB_PID=$!

printf '\n  Waiting for the app to come up...\n'
READY=""
for _ in $(seq 1 45); do
  if curl -fsS -o /dev/null http://127.0.0.1:8080/ 2>/dev/null; then READY=1; break; fi
  sleep 1
done

if [ -n "$READY" ]; then
  (command -v open >/dev/null 2>&1 && open http://localhost:8080) \
    || (command -v xdg-open >/dev/null 2>&1 && xdg-open http://localhost:8080) \
    || true
  say "Ready. DataPilot is open in your browser."
else
  say "Still starting - check /tmp/datapilot-api.log and /tmp/datapilot-web.log"
fi

cat <<'EOF'

    App   http://localhost:8080
    API   http://localhost:8000
    Docs  http://localhost:8000/docs

  Press Ctrl+C to stop.
EOF

wait
