FROM node:24-bookworm-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json tsconfig.json vite.config.ts ./
COPY frontend ./frontend
RUN npm ci --ignore-scripts --no-audit --no-fund && npm run build

FROM python:3.13-slim-bookworm AS api
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -g 10001 lean && useradd -m -u 10001 -g 10001 lean && mkdir /data && chown lean:lean /data
WORKDIR /app
COPY backend ./backend
COPY --from=frontend /app/frontend/dist ./frontend/dist
ARG SOURCE_SHA256=unbound
LABEL io.lean-observatory.source-sha256=$SOURCE_SHA256
USER 10001:10001
EXPOSE 8787
CMD ["python3", "-m", "backend.api", "--host", "0.0.0.0", "--data", "/data"]

FROM ubuntu:24.04 AS lean-tools
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 curl git ca-certificates xz-utils zstd elan build-essential && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 10001 lean && useradd -m -u 10001 -g 10001 lean && mkdir /data && chown lean:lean /data
ENV ELAN_HOME=/home/lean/.elan PATH=/home/lean/.elan/bin:$PATH
USER 10001:10001
RUN elan toolchain install leanprover/lean4:v4.33.1 && elan default leanprover/lean4:v4.33.1 \
 && lean --version
FROM python:3.13-slim-bookworm AS worker
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 SANDBOX_ROOT=/sandbox
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=lean-tools /usr /sandbox/usr
COPY --from=lean-tools /etc /sandbox/etc
COPY --from=lean-tools /home/lean/.elan /sandbox/home/lean/.elan
RUN mkdir -p /data /sandbox/work /sandbox/tmp /sandbox/dev \
 && chown 10001:10001 /data \
 && ln -s usr/bin /sandbox/bin && ln -s usr/sbin /sandbox/sbin && ln -s usr/lib /sandbox/lib \
 && if [ -d /sandbox/usr/lib64 ]; then ln -s usr/lib64 /sandbox/lib64; fi \
 && mkdir -p /sandbox/proc && chmod 1777 /sandbox/tmp \
 && touch /sandbox/dev/null /sandbox/dev/urandom
WORKDIR /app
COPY backend ./backend
ARG SOURCE_SHA256=unbound
LABEL io.lean-observatory.source-sha256=$SOURCE_SHA256
CMD ["python3", "-m", "backend.worker", "--data", "/data"]
