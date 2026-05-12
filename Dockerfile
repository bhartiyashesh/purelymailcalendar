# ---------- Stage 1: build the frontend ----------
FROM node:20-alpine AS web-build
WORKDIR /web

COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY web ./
RUN npm run build


# ---------- Stage 2: Python runtime ----------
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# psycopg[binary] ships wheels, so no compiler needed.
COPY pyproject.toml ./
COPY calinvite ./calinvite
COPY calinvite_web ./calinvite_web
COPY sieve ./sieve

RUN pip install -e ".[web]"

# Pull in the static frontend bundle.
COPY --from=web-build /web/dist ./web/dist

# Railway sets $PORT; default for local docker runs.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn calinvite_web.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
