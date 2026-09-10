# syntax=docker/dockerfile:1
#
# VayuDev GCS Backend — production image.
#
# Design notes for the air-gapped deployment target:
#   - Build happens on a machine WITH internet access (or an internal PyPI
#     mirror); the resulting image is what actually ships into the air-gapped
#     environment, so the runtime stage has zero outbound dependency.
#   - Multi-stage build keeps compilers/toolchains out of the final image.
#   - Runs as a non-root user.
#   - No CDN references anywhere — this is a pure Python backend, so there is
#     nothing to fetch at runtime beyond what's baked into the image.

# ---------- Stage 1: build wheels ----------
FROM python:3.12-slim-trixie AS builder

WORKDIR /build

# Pull latest OS-level security patches at build time (vulnerabilities are
# almost always in system packages like openssl/libc, not in Python itself),
# then install the compilers needed to build wheels.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim-trixie AS runtime

# Metadata
LABEL org.opencontainers.image.title="vayudev-backend" \
      org.opencontainers.image.description="VayuDev GCS telemetry/inference/security backend"

# Same rationale as the builder stage: patch OS packages before anything else.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 vayudev \
    && useradd --uid 1000 --gid vayudev --shell /bin/bash --create-home vayudev

WORKDIR /app

# Install from pre-built wheels only — no network access needed at this step
# once wheels are vendored, which matters for reproducing the build inside an
# air-gapped CI runner too.
COPY --from=builder /build/wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt

COPY app ./app

# Drop privileges
USER vayudev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO \
    RING_BUFFER_SIZE=100

EXPOSE 8000/tcp
EXPOSE 14550/udp

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
