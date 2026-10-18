# Project context: GNSS Trace Quality Checker (Azure + Databricks)

> Context file for AI coding assistants. Keep it at the repo root.
> Claude Code reads `CLAUDE.md`; for Cursor copy it to `.cursorrules`; for Codex/others copy it to `AGENTS.md`.

## What this project is

A personal proof-of-concept that cleans **simulated** vehicle GNSS traces and runs on Azure.
It exists to demonstrate Cloud & DevOps skills: Azure, Terraform, GitHub Actions, Databricks, Python APIs/Streamlit.

- One shared Python module `geo/` holds all algorithm logic.
- `api/` (FastAPI) and `ui/` (Streamlit) run on **Azure App Service** and process one trip at a time.
- `databricks/` runs the **same `geo/` module** on 200 simulated trips (Bronze → Silver → Gold Delta tables).
- All infrastructure is **Terraform**. All deployment is **GitHub Actions** with **OIDC** (no secrets).

## Honesty rule (important)

The data is simulated. Never describe it as real vehicle data in code, README, UI text or comments.
Always say "simulated" where data origin is shown.

## Repo layout (target)

```
geo/                  geo.py (algorithms), generate_trace.py (simulator), __init__.py
api/                  main.py, requirements.txt, tests/
ui/                   app.py, requirements.txt
databricks/           databricks.yml, notebooks/01_bronze.py, 02_silver.py, 03_gold.py
infra/bootstrap/      storage account for Terraform state (applied once, locally)
infra/app/            App Service plan, 2 web apps, Application Insights, identity for OIDC
infra/databricks/     Databricks workspace + single-node cluster + cluster policy
.github/workflows/    ci.yml, infra.yml, deploy-app.yml, deploy-databricks.yml
reference/demo.py     working prototype of the algorithms (source of truth for geo/)
```

## Algorithms (port from reference/demo.py, do not reinvent)

- Convert lat/lon to local metres around the first point (equirectangular is fine).
- Anomaly: implied speed between consecutive points > threshold (default 200 km/h) → flag the jumped point.
- Kalman filter: state [x, y, vx, vy], constant velocity, dt = 1 s, R = (4 m)^2 I.
  Skip the update step when the point is flagged or the Mahalanobis^2 of the innovation > 16 (gating).
- ODD check: point-in-polygon (Shapely), report % of time inside and enter/exit timestamps.
- Simulator: waypoints → 1 Hz at ~10 m/s, Gaussian noise ~4 m, a few multipath jumps of 80–180 m.
  Output keeps ground truth columns `true_lat`, `true_lon` so error can be measured.

CSV contract: input `timestamp,lat,lon` (ISO timestamps, 1 Hz).
Output adds `is_anomaly,smooth_lat,smooth_lon,in_odd`.

## Platform constraints (Azure for Students subscription)

- Region: `southeastasia`. Budget target: under 10 USD total.
- **Max ~4 vCPU per region, no quota increase.** Databricks must use a **single-node** cluster
  with a 4-core VM (e.g. `Standard_DS3_v2`), auto-termination 15 min. Never create multi-node clusters.
- App Service plan SKU `B1` (F1 breaks Streamlit websockets).
- OIDC: prefer a **user-assigned managed identity with a federated credential** for GitHub
  (created by Terraform). Use an App Registration only if the managed identity route fails.

## Technical rules

- Python 3.12. Pin versions in requirements.txt.
- Terraform >= 1.6, `azurerm` provider v4 (requires `subscription_id` in the provider block),
  remote state in the bootstrap storage account. `infra/app` and `infra/databricks` use **separate state keys**.
- Streamlit web app: `websockets_enabled = true`, startup
  `python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0`.
- FastAPI web app startup: `gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app`.
- Both web apps: `SCM_DO_BUILD_DURING_DEPLOYMENT=true`, `APPLICATIONINSIGHTS_CONNECTION_STRING`. UI also gets `API_URL`.
- GitHub Actions: `azure/login@v2` with OIDC (`permissions: id-token: write`), `azure/webapps-deploy@v3`.
- Never commit secrets, `.tfstate`, `.terraform/`, `*.tfvars` with real IDs, or `.env`. Keep a `.gitignore`.
- Never create Azure resources by hand in code comments' instructions except the documented bootstrap step.

## Working style for the AI

- Work one phase at a time (see PROMPTS.md). Small, reviewable changes.
- Git: Phase 1–4 = one commit per phase directly on `main`, pushed right away (the GitHub repo is
  created and pushed at the end of Phase 1). Phase 5 onward = one branch + PR per phase
  (branch, push, `gh pr create`, wait for green checks, squash merge, pull `main`).
  Branch names and commit messages: see the table in PROMPTS.md "Quy trình Git".
- Never add AI attribution: no `Co-Authored-By: Claude …`, no "Generated with Claude Code" in
  commit messages, PR titles or PR bodies. I am the only author.
- After code changes, run `pytest` and say which commands you ran and the result.
- If something needs my Azure/GitHub login or a click in a portal, stop and tell me the exact command or step.
- Do not invent results or numbers for the README; leave placeholders until real runs exist.
