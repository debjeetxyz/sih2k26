FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
WORKDIR /sim
COPY simulate.py .
CMD ["python", "simulate.py"]
