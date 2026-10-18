# GNSS Trace Quality Checker on Azure + Databricks

A personal proof-of-concept that cleans **simulated** vehicle GNSS traces: it flags multipath jumps,
smooths the trajectory with a Kalman filter and checks whether the vehicle stayed inside an
operational design domain (ODD). It runs as a FastAPI + Streamlit app on Azure App Service and as a
Bronze → Silver → Gold pipeline on Azure Databricks. Both use **the same `geo/` Python module**.

> **All data in this project is simulated.** No real vehicle data is used. The simulator keeps the
> ground truth so the smoothing error can be measured.

Skills shown: Azure (App Service, Application Insights, managed identity, Databricks), Terraform
(remote state, separate state keys), GitHub Actions with OIDC (no stored secrets), Python
(FastAPI, Streamlit, pandas, Shapely), Spark `applyInPandas`, Databricks Asset Bundles.

## Architecture

```mermaid
flowchart LR
  dev[Developer] -->|git push / PR| gh[GitHub]
  subgraph GHA[GitHub Actions]
    ci[ci.yml<br/>pytest]
    infra[infra.yml<br/>terraform plan/apply]
    dapp[deploy-app.yml]
    ddbx[deploy-databricks.yml<br/>bundle deploy]
  end
  gh --> GHA
  GHA -->|OIDC federated credential| mi[User-assigned<br/>managed identity]

  subgraph AZ[Azure · southeastasia]
    subgraph RGAPP[rg-gnss-app]
      ui[Web App: Streamlit UI] -->|HTTPS /trace/clean| api[Web App: FastAPI]
      api --> appi[Application Insights<br/>+ Log Analytics]
    end
    subgraph RGDBX[rg-gnss-databricks]
      ws[Databricks workspace<br/>premium] --> cl[Single-node cluster<br/>Standard_DS3_v2, 15 min auto-stop]
      cl --> b[(bronze_points)] --> s[(silver_points)] --> g[(gold_trip_quality)]
    end
    st[(Storage account<br/>Terraform state)]
  end

  mi --> RGAPP
  mi --> ws
  mi --> st
  geo[[geo/ shared module]] -.-> api
  geo -.-> s
  user[Browser] --> ui
```

| Folder | What it is |
|---|---|
| `geo/` | Algorithms (`geo.py`) and simulator (`generate_trace.py`). Pure functions, no I/O. |
| `api/` | FastAPI app + pytest tests (`api/tests`). |
| `ui/` | Streamlit app; calls the API at `API_URL`. |
| `databricks/` | Asset Bundle (`databricks.yml`), notebooks `00`–`03`, dashboard SQL. |
| `scripts/make_fleet.py` | Generates 200 simulated trips for Databricks. |
| `infra/bootstrap` | Storage account for Terraform state (local state, applied once). |
| `infra/app` | App Service plan B1, 2 web apps, App Insights, GitHub OIDC identity. |
| `infra/databricks` | Databricks workspace, single-node cluster policy + cluster. |
| `.github/workflows` | `ci`, `infra`, `deploy-app`, `deploy-databricks`. |
| `reference/demo.py` | Original prototype; source of truth for the algorithms. |

## Algorithms

1. **Local frame** – lat/lon → metres around the first point (equirectangular).
2. **Anomalies** – implied speed between consecutive points > 200 km/h (configurable). A jump makes
   the step in *and* out too fast, so the point between them is flagged.
3. **Kalman filter** – state `[x, y, vx, vy]`, constant velocity, dt = 1 s, R = (4 m)² I. The update is
   skipped for flagged points and when the innovation Mahalanobis² > 16 (gating).
4. **ODD check** – point-in-polygon (Shapely) on the smoothed track: % of time inside, enter/exit times.
5. **Simulator** – waypoints at ~10 m/s, 1 Hz, Gaussian noise ~4 m, multipath jumps of 80–180 m.

CSV contract: input `timestamp,lat,lon` (ISO 8601, 1 Hz) → output adds `is_anomaly,smooth_lat,smooth_lon,in_odd`.
Extra columns (e.g. `true_lat,true_lon`) are passed through.

## Run locally

Python 3.12 (3.13 also works for local dev).

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r api/requirements-dev.txt -r ui/requirements.txt
pytest                            # geo + API tests
python -m geo.generate_trace --seed 1 --out sample.csv
```

Start the API and the UI in two terminals:

```bash
cd api && uvicorn main:app --reload --port 8000      # docs at http://localhost:8000/docs
```

```bash
streamlit run ui/app.py                               # http://localhost:8501, uses API_URL=http://localhost:8000
```

### API

| Method | Path | Input | Output |
|---|---|---|---|
| GET | `/health` | – | `{"status":"ok"}` |
| GET | `/trace/sample` | `seed`, `noise_m`, `n_jumps` | simulated CSV with ground truth |
| POST | `/trace/stats` | CSV file, `max_kmh` | trip stats JSON |
| POST | `/trace/anomalies` | CSV file, `max_kmh` | flagged points with implied speed |
| POST | `/trace/smooth` | CSV file | cleaned CSV download |
| POST | `/trace/odd-check` | CSV file, form `polygon` (GeoJSON, `[lon, lat]`) | % inside, enter/exit events |
| POST | `/trace/clean` | CSV file, optional `polygon` or `use_default_odd=true` | `{"summary": …, "points": […]}` |

Bad input (missing columns, non-ISO timestamps, invalid lat/lon or polygon) returns **422** with a clear message.

**Why `geo/` is copied into the API package on deploy:** App Service runs `gunicorn … main:app` from the
deployed folder. Copying `geo/` next to `main.py` in `deploy-app.yml` keeps one source of truth in git
without publishing a pip package. Locally `api/main.py` adds the repo root to `sys.path` instead.

## Deploy to Azure

Constraints: Azure for Students, `southeastasia`, ≤ 4 vCPU per region, budget < 10 USD.

### 1. Bootstrap Terraform state (once, locally)

```bash
az login
az account set --subscription <subscription-id>
cd infra/bootstrap
cp terraform.tfvars.example terraform.tfvars      # fill subscription_id
terraform init && terraform apply
terraform output backend_hcl                       # -> paste into infra/app/backend.hcl and infra/databricks/backend.hcl
terraform output storage_account_id                # -> tfstate_storage_account_id in infra/app/terraform.tfvars
```

### 2. App infrastructure (first apply locally, later via GitHub Actions)

```bash
cd infra/app
cp terraform.tfvars.example terraform.tfvars      # subscription_id, github_owner, github_repo, tfstate_storage_account_id
cp backend.hcl.example backend.hcl                 # values from step 1
terraform init -backend-config=backend.hcl
terraform apply
terraform output
```

The first apply must run locally (as subscription Owner) because it creates the role assignments for the
GitHub identity: Contributor on `rg-gnss-app`, Reader on the subscription (so CI `plan` can refresh) and
Storage Blob Data Contributor on the state account.

### 3. GitHub secrets and variables

Settings → Secrets and variables → Actions. The secrets are identifiers, not passwords (OIDC).

| Kind | Name | Value |
|---|---|---|
| Secret | `AZURE_CLIENT_ID` | `terraform output github_identity_client_id` (infra/app) |
| Secret | `AZURE_TENANT_ID` | `terraform output tenant_id` |
| Secret | `AZURE_SUBSCRIPTION_ID` | `terraform output subscription_id` |
| Variable | `TFSTATE_RESOURCE_GROUP` | `rg-gnss-tfstate` (bootstrap output) |
| Variable | `TFSTATE_STORAGE_ACCOUNT` | bootstrap output `storage_account_name` |
| Variable | `API_APP_NAME` | `terraform output api_app_name` |
| Variable | `UI_APP_NAME` | `terraform output ui_app_name` |
| Variable | `DATABRICKS_HOST` | infra/databricks output `workspace_url` |
| Variable | `DATABRICKS_CLUSTER_ID` | infra/databricks output `cluster_id` |
| Variable | `DATABRICKS_CATALOG` | the Unity Catalog catalog to use (see step 5) |
| Variable | `DATABRICKS_RUN_AS_USER` | your Databricks login e-mail |

### 4. Workflows

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | pull request | Python 3.12, install, `pytest` |
| `infra.yml` | PR / push to `main` touching `infra/app/**` | `fmt -check`, `init`, `validate`, `plan`; `apply` on `main` |
| `deploy-app.yml` | push to `main` touching `api/**`, `ui/**`, `geo/**` | tests, then matrix `[api, ui]` → `azure/webapps-deploy@v3`, API health smoke test |
| `deploy-databricks.yml` | push to `main` touching `databricks/**`, `geo/**` | `databricks bundle validate` + `deploy -t dev` |

All Azure logins use `azure/login@v2` with OIDC (`permissions: id-token: write`). Terraform jobs share a
concurrency group so two applies never run at once. Federated credential subjects:
`repo:<owner>/<repo>:ref:refs/heads/main` and `repo:<owner>/<repo>:pull_request`.

### 5. Databricks

```bash
cd infra/databricks
cp terraform.tfvars.example terraform.tfvars      # subscription_id, user_name, github_identity_client_id
cp backend.hcl.example backend.hcl
terraform init -backend-config=backend.hcl
terraform apply                                    # workspace + policy + single-node cluster (starts it once)
```

The cluster policy fixes `num_workers = 0`, `Standard_DS3_v2` (4 vCPU) and 15-minute auto-termination,
so the subscription quota is never exceeded. The GitHub managed identity is added to the workspace as an
admin service principal, which lets `deploy-databricks.yml` deploy the bundle and set the job's `run_as`.

Find your catalog name in the workspace (Catalog explorer; new workspaces get a workspace catalog), then:

```bash
python scripts/make_fleet.py --trips 200 --out data/fleet          # simulated fleet, one CSV per trip
databricks auth login --host <workspace_url>
cd databricks
databricks schemas create gnss <catalog>                           # same as notebook 00_setup
databricks volumes create <catalog> gnss raw MANAGED
databricks fs cp -r ../data/fleet dbfs:/Volumes/<catalog>/gnss/raw/ --overwrite
databricks bundle deploy -t dev --var="cluster_id=<id>" --var="catalog=<catalog>" --var="run_as_user=<you@...>"
databricks bundle run gnss_quality -t dev --var="cluster_id=<id>" --var="catalog=<catalog>" --var="run_as_user=<you@...>"
```

Check: `SELECT count(*) FROM gnss.gold_trip_quality` should return 200.

Notebook order: `00_setup` → `01_bronze` → `02_silver` → `03_gold` (all idempotent, overwrite mode).
`02_silver` imports the synced `geo/` package and runs `geo.clean_trace` per trip with
`groupBy("trip_id").applyInPandas(...)`; no algorithm code is copied into notebooks.
Dashboard queries: [`databricks/dashboard.sql`](databricks/dashboard.sql).

Tear down at the end of the day:

```bash
cd infra/databricks && terraform destroy
cd infra/app && terraform destroy          # only if you do not need the demo
```

### Observability

When `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, the API configures `azure-monitor-opentelemetry`:
requests, exceptions and logs go to Application Insights. `/trace/clean` logs the trip size, anomaly
count and processing time (custom dimensions `trip_points`, `anomalies`, `processing_ms`).

```kusto
traces
| where message startswith "trace cleaned"
| project timestamp, points = toint(customDimensions.trip_points), ms = todouble(customDimensions.processing_ms)
```

## Screenshots

_To add after the real runs (put files in `docs/screenshots/`):_

- [ ] Streamlit UI on Azure (map with raw / smoothed / anomalies / ODD)
- [ ] GitHub Actions: all workflows green
- [ ] `terraform plan` on a pull request
- [ ] Application Insights: requests + `trace cleaned` logs
- [ ] Databricks job run (4 tasks) and dashboard

## Results

_Placeholders – fill in with numbers from real runs (`databricks/dashboard.sql`, query 5). Data is simulated._

| Metric | Value |
|---|---|
| Simulated trips processed | _TBD_ |
| Usable trips (anomaly < 5 % and in ODD > 80 %) | _TBD_ |
| Median position error before smoothing | _TBD_ m |
| Median position error after smoothing | _TBD_ m |
| API `/trace/clean` processing time (App Insights, p50) | _TBD_ ms |
| Azure cost for the project | _TBD_ USD |

## Limitations

- **Simulated data only.** One base route with random variations; real GNSS has correlated errors,
  outages, urban canyons and variable sample rates that the simulator does not model.
- **Simple filter.** Constant-velocity Kalman with fixed noise, no smoother pass, no map matching,
  no IMU fusion. The speed-threshold detector can miss two consecutive jumps that move together.
- **Single-node Databricks.** The Azure for Students quota (~4 vCPU per region) allows one 4-core node,
  so the pipeline shows the Spark pattern (`applyInPandas`) rather than real scale.
- **Demo ODD.** The default ODD polygon is a fixed shape anchored at the first point of each trace.
