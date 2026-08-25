# --- Stage 1: build the React/Vite frontend -------------------------------
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python backend + baked-in built frontend ---------------------
FROM python:3.12-slim
WORKDIR /app

# ortools' compiled extension needs libstdc++ at runtime on slim images.
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY sih_solver/ ./sih_solver/
COPY parsers/ ./parsers/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# uploads/ and timetables_generated/ are runtime data, not image content --
# backend/app.py creates them on startup (BASE / "uploads", relative to
# backend/app.py's own location, i.e. /app here) if missing. In production
# this directory should be a mounted volume so job data survives restarts
# and redeploys (see fly.toml).
RUN mkdir -p uploads timetables_generated

EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
