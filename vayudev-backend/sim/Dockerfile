FROM python:3.12-slim-bookworm
WORKDIR /sim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY simulate.py .
CMD ["python", "simulate.py"]
