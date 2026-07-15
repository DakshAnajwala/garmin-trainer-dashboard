# --- Stage 1: build the React frontend ---
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python backend, serving the built frontend too ---
FROM python:3.12-slim
WORKDIR /app

# The Garmin MCP client shells out to `npx @nicolasvegam/garmin-connect-mcp`
# at runtime (see config/settings.py GARMIN_MCP_COMMAND), so Node needs to be
# present in the runtime image too, not just the build stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Cloud Run injects PORT; uvicorn must bind to it (not a hardcoded 8000).
ENV PORT=8080
EXPOSE 8080
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
