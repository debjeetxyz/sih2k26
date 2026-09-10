# VayuDev — SIH 2026

AI-Enabled Real-Time 3D Digital Twin & Predictive Maintenance Ground Control
Station (GCS) for MALE UAV Rotax 912 ULS aero-piston engines.

## Repo map

| Folder                  | Owner(s)                | What lives here-------------------------------------------------------------------------------------------------------|
|-------------------------|-------------------------|-----------------------------------------------------------------------------------------------------------------------|
| `backend/`              | Debjeet & Sagar         | Telemetry ingestion (WS/UDP), inference pipeline integration, security (JWT/RBAC, MAVLink signing), Docker/deployment |
| `frontend/`             | Payel & Baishali      | Three.js/React 3D digital twin HUD                                                                                    |
| `ml/`                   | Somdeep                 | `inference.py` (XGBoost model + physics guardrail), training notebooks, model artifacts                               |
| `cad/`                  | Subhadip                | Rotax 912 ULS CAD source (`.SLDPRT`, `.STEP`) and reference imagery                                                   |
| `postman/`, `.postman/` | API/integration owner   | Postman-synced collections, environments, mocks, specs — **edit via Postman app/extension, not by hand**              |
| `docs/`                 | Everyone                | Architecture diagrams, SIH submission docs, decision notes                                                            |

## Getting started

Each subfolder that has its own runtime (backend, frontend, ml) should carry
its own README with setup instructions specific to that stack. Start there
before touching code.

## Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # fill in secrets
docker compose up -d   # or run uvicorn directly, see backend/README.md
```

## Conventions

- One PR per feature/fix, reviewed by at least one other person before merge.
- Don't hand-edit `postman/` — changes should come from the Postman app so
  the sync stays consistent.
- Secrets (`.env`, API keys, JWT signing keys) never get committed — see the
  root `.gitignore`.
- Large binary CAD/model assets belong in `cad/`, not scattered in service
  folders.
