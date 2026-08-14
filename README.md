# Full Stack AI Agent App

This repository contains the complete full-stack application integrating a TanStack Start (SSR) + React 19 + Tailwind 4 frontend with a FastAPI Python backend.

## Structure

- `/frontend`: Contains the Vite + React frontend application (based on Lovable template).
- `/backend`: Contains the FastAPI backend and AI agent orchestration code.

## Key Features & Fixes
- **Offline Mode Fixes**: The frontend correctly handles `final` SSE events with `sql`, `chart`, and `diagram` embedded payloads in offline mode. The offline `final` answer logic handles falling back to `text` or `answer` inside the event stream.
- **Charts & Diagrams**: ECharts are rendered accurately based on backend payload schema, and Mermaid ER diagrams are properly streamed via SSE.
- **Session Persistence**: Chat and session history persists, maintaining chart, sql, diagram, and mode payloads correctly upon reload.
- **Dashboard & Integration**: The dashboard handles pinning, link sharing, and CSV data file imports seamlessly.
- **Proxy Configuration**: The Vite frontend proxies `/api` and `/health` calls transparently to the `:8000` backend server.

## Running the Application

Both the frontend and backend are designed to run side-by-side.

### 1. Start the Backend
Navigate to the `backend` folder, install requirements, and start the FastAPI server:
```bash
cd backend
pip install -r requirements.txt
# Alternatively, if using a virtual environment:
# python -m venv .venv
# .venv\Scripts\activate
# pip install -r requirements.txt

python main.py
```
*The backend will run on `http://localhost:8000`.*

### 2. Start the Frontend
Navigate to the `frontend` folder, install dependencies (using Bun, npm, or pnpm), and start the dev server:
```bash
cd frontend
bun install
bun run dev
```
*The frontend will run on `http://localhost:8080` (or whatever Vite assigns) and proxy API requests to `:8000`.*

## Resetting the Database

If you need to reset the demo database (for example, to start with a clean slate or re-seed data), stop the backend server, remove the SQLite files, and restart the backend:

```bash
# 1. Stop the backend server
# 2. Delete all .db files in backend/data/
rm backend/data/*.db   # On Mac/Linux
del backend\data\*.db  # On Windows

# 3. Restart the backend (it will auto-seed)
python main.py
```
