# GNSS project — kế hoạch vibe code theo từng phase

Cách dùng:
1. Tạo thư mục `gnss-quality-azure`, bỏ `CLAUDE.md` vào gốc và `demo.py` vào `reference/demo.py`.
   Repo GitHub được tạo và push ngay ở **Phase 1** (xem "Quy trình Git" bên dưới).
2. Mở công cụ AI (Claude Code, Cursor…) trong repo. Làm **lần lượt từng phase**: dán prompt, để AI làm,
   rồi **tự kiểm tra** theo mục "Kiểm tra". Đạt thì commit + push rồi mới sang phase sau.
3. Các bước có ký hiệu 🧑 là việc **bạn tự làm** (đăng nhập, cấp quyền, bấm trên portal). AI không làm được.

Thời gian ước tính: Ngày 1 = Phase 0–6 (app), Ngày 2 = Phase 7–10 (Databricks + hoàn thiện).

---

## Quy trình Git

**Phase 1–4: commit thẳng lên `main`, mỗi phase một commit, push luôn.**

```bash
# Phase 1 (lần đầu): tạo repo GitHub từ thư mục local và push
git init -b main
git add . && git commit -m "feat(geo): port algorithms and simulator from reference demo"
gh repo create gnss-quality-azure --public --source . --remote origin --push

# Phase 2, 3, 4: mỗi phase một commit
git add . && git commit -m "<message của phase>" && git push
```

**Phase 5–10: mỗi phase một PR** — tạo nhánh, push, mở PR, chờ check xanh, merge.

```bash
git switch main && git pull
git switch -c <nhánh>
git add . && git commit -m "<message>"
git push -u origin HEAD
gh pr create --fill                      # hoặc --title/--body
gh pr checks --watch                     # chờ ci (và infra plan nếu có) xanh
gh pr merge --squash --delete-branch     # 1 commit gọn trên main, có số PR
git switch main && git pull
```

| Phase | Kiểu | Nhánh | Commit / tiêu đề PR |
|---|---|---|---|
| 1 | commit `main` | – | `feat(geo): port algorithms and simulator from reference demo` |
| 2 | commit `main` | – | `feat(api): FastAPI endpoints with CSV validation` |
| 3 | commit `main` | – | `feat(ui): Streamlit map and metrics` |
| 4 | commit `main` | – | `feat(infra): terraform bootstrap and app service` |
| 5 | PR #1 | `ci/github-actions-oidc` | `ci: GitHub Actions with OIDC (test, terraform, deploy)` |
| 6 | PR #2 | `feat/observability` | `feat(api): Application Insights + README` |
| 7 | PR #3 | `infra/databricks` | `feat(infra): Databricks workspace and single-node cluster` |
| 8 | PR #4 | `feat/databricks-pipeline` | `feat(databricks): bronze/silver/gold pipeline` |
| 9 | PR #5 | `feat/databricks-bundle` | `feat(databricks): asset bundle, job and deploy workflow` |
| 10 | PR #6 | `docs/final-readme` | `docs: architecture, results and limitations` |

Ghi chú:
- PR #1 tự chạy `ci.yml` (và `infra.yml` vì sửa file workflow) ngay trên chính PR đó, nên phải tạo
  GitHub secrets/variables **trước** khi mở PR.
- 🧑 Sau khi PR #1 merge: bật branch protection cho `main` (Settings → Branches → Add rule):
  *Require a pull request before merging* + *Require status checks to pass* → chọn check `test`.
  Từ đây không push thẳng lên `main` được nữa.
- Không bao giờ commit `terraform.tfvars`, `backend.hcl`, `.tfstate`, `.env` — kiểm tra `git status` trước mỗi commit.

---

## Phase 0 — Chuẩn bị (≈30 phút, không cần AI)

🧑 Việc của bạn:
- `az login`, chọn subscription Azure for Students: `az account set --subscription <id>`
- Tạo budget alert 10 USD và 30 USD trên Azure Portal (Cost Management → Budgets)
- Kiểm tra quota: `az vm list-usage --location southeastasia -o table` (xem dòng "Total Regional vCPUs")
- Cài: Azure CLI, Terraform ≥ 1.6, Python 3.12, Databricks CLI, Git, GitHub CLI (`gh`)
- `gh auth login` (repo GitHub sẽ được tạo và push ở cuối Phase 1)

---

## Phase 1 — Khung repo + module thuật toán (≈1 giờ)

```
Read CLAUDE.md and reference/demo.py.

Create the repo skeleton from the layout in CLAUDE.md (empty folders with a .gitkeep where needed),
a Python .gitignore that also ignores Terraform state/.terraform/*.tfvars/.env, and a short README stub.

Then build the geo/ package by porting the logic from reference/demo.py:
- geo/geo.py with pure functions (no plotting, no file I/O):
  to_local_xy, from_local_xy, haversine_m, flag_anomalies(df, max_kmh=200),
  kalman_smooth(df, flags), odd_check(df, polygon), trip_stats(df),
  and clean_trace(df, polygon=None, max_kmh=200) that returns the output CSV contract.
- geo/generate_trace.py with generate_trace(seed, noise_m=4.0, n_jumps=5) -> DataFrame
  (keeps true_lat/true_lon) and a CLI: python -m geo.generate_trace --seed 1 --out sample.csv
- api/tests/test_geo.py with pytest tests:
  1) injected jumps are flagged, 2) median error after smoothing < median raw error,
  3) odd_check returns 100% for a polygon that covers the whole trace.
Run pytest and show me the result.
```

Kiểm tra:
- [ ] `pytest` xanh cả 3 test
- [ ] `python -m geo.generate_trace --seed 1 --out sample.csv` tạo ra file CSV đúng cột
- [ ] Mở `geo/geo.py` đọc lướt: không có code vẽ hình, không đọc/ghi file
- [ ] `git init`, commit, `gh repo create … --push` → thấy repo trên GitHub

---

## Phase 2 — API FastAPI (≈45 phút)

```
Build api/main.py with FastAPI using the geo package:
- GET /health -> {"status":"ok"}
- POST /trace/stats       (multipart CSV upload) -> trip stats JSON
- POST /trace/anomalies   (CSV + query max_kmh) -> list of flagged points
- POST /trace/smooth      (CSV) -> CSV download with smooth_lat/smooth_lon/is_anomaly
- POST /trace/odd-check   (CSV + polygon GeoJSON in form field) -> % inside + enter/exit times
- POST /trace/clean       (CSV + optional polygon) -> {"summary": {...}, "points": [...]} for the UI
Validate the CSV columns and return 422 with a clear message on bad input.
Make geo importable from api/ on App Service (copy or package it; explain the choice).
Add api/requirements.txt with pinned versions incl. gunicorn and uvicorn.
Add API tests with FastAPI TestClient. Run pytest and tell me how to start it locally.
```

Kiểm tra:
- [ ] `uvicorn main:app --reload` (trong `api/`) chạy, mở `http://localhost:8000/docs` thử upload `sample.csv`
- [ ] Upload file sai cột → nhận lỗi 422 dễ hiểu
- [ ] `pytest` vẫn xanh
- [ ] Commit + push: `feat(api): FastAPI endpoints with CSV validation`

---

## Phase 3 — Giao diện Streamlit (≈1 giờ)

```
Build ui/app.py (Streamlit) that calls the API at env var API_URL (default http://localhost:8000):
- Sidebar: CSV upload OR "Generate sample" button (seed, noise, number of jumps sliders),
  speed threshold input, a checkbox to use a default ODD polygon around the trace.
- Top row of metrics: distance km, duration, avg speed, anomalies count and %, % in ODD,
  and median error raw vs smoothed only when ground truth columns exist.
- Map with pydeck: raw trace (grey line), smoothed trace (teal line), anomalies (red dots), ODD polygon (light fill).
- Table of anomalies, and a download button for the cleaned CSV.
- A small caption: "Data is simulated for demonstration; not real vehicle data."
Add ui/requirements.txt with pinned versions. Tell me how to run UI + API together locally.
```

Kiểm tra:
- [ ] Chạy API và UI cùng lúc, bấm "Generate sample" thấy bản đồ 3 lớp giống ảnh `gnss_input_output.png`
- [ ] Có dòng chú thích "simulated"
- [ ] Commit + push: `feat(ui): Streamlit map and metrics`

---

## Phase 4 — Terraform bootstrap + hạ tầng app (≈1 giờ)

```
Write Terraform:
1) infra/bootstrap: resource group + storage account + private container "tfstate"
   for remote state. Local state is fine for this folder only. Output the names.
2) infra/app with backend "azurerm" pointing at that container (key "app.tfstate"), azurerm v4
   with subscription_id variable. Resources in southeastasia:
   resource group, Log Analytics workspace + Application Insights,
   Linux App Service plan B1, two azurerm_linux_web_app (api and ui) with python 3.12 and the
   startup commands/app settings from CLAUDE.md (ui gets API_URL = https://<api default hostname>),
   health check path /health on the api.
   A user-assigned managed identity for GitHub Actions with federated identity credentials for
   repo:<owner>/<repo>:ref:refs/heads/main and repo:<owner>/<repo>:pull_request,
   and Contributor on the app resource group. Use variables for owner/repo.
   Outputs: web app names and URLs, identity client_id, tenant_id, subscription_id.
Add an example terraform.tfvars.example (no real values). Show me the exact commands to run.
```

🧑 Việc của bạn:
- `cd infra/bootstrap && terraform init && terraform apply`
- Điền tên storage vào backend của `infra/app`, tạo `terraform.tfvars` thật (không commit)
- `cd infra/app && terraform init && terraform apply`

Kiểm tra:
- [ ] Trên Portal thấy 2 web app, App Insights, managed identity
- [ ] `terraform plan` lần hai báo "No changes"
- [ ] `git status` không có file `.tfstate` hay `terraform.tfvars`
- [ ] Commit + push: `feat(infra): terraform bootstrap and app service` (commit cuối cùng thẳng lên `main`)

Nếu lỗi quyền khi tạo federated credential / role assignment → báo AI, chuyển sang dùng App Registration.

---

## Phase 5 — GitHub Actions + OIDC (≈1,5 giờ)

```
Create GitHub Actions workflows using OIDC (azure/login@v2 with client-id, tenant-id,
subscription-id from repository secrets AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID;
these are identifiers, not passwords):
- ci.yml: on pull_request -> setup Python 3.12, install, pytest.
- infra.yml: on pull_request touching infra/app/** -> terraform fmt -check, init, validate, plan;
  on push to main touching infra/app/** -> apply -auto-approve. Backend config via env/secrets.
- deploy-app.yml: on push to main touching api/**, ui/**, geo/** -> run tests, then a matrix
  [api, ui] that packages the folder (including geo/) and deploys with azure/webapps-deploy@v3.
Use concurrency groups so two applies never run at once. Pin action versions.
List exactly which GitHub secrets/variables I must create.
```

🧑 Việc của bạn:
- Lấy output từ Terraform, tạo các GitHub secrets/variables mà AI liệt kê (Settings → Secrets and variables → Actions)
- Nhánh `ci/github-actions-oidc` → push → mở **PR #1** → chờ `ci` + `infra` (plan) xanh → squash merge
- Sau merge, `deploy-app` chạy trên `main`; bật branch protection cho `main` (xem "Quy trình Git")

Kiểm tra:
- [ ] Trên PR #1 thấy check `test` và `terraform` xanh
- [ ] Sau merge, `deploy-app` trên `main` xanh
- [ ] Mở URL web app UI trên Azure, "Generate sample" chạy được (UI gọi được API)
- [ ] Mở một PR đổi 1 dòng trong `infra/app` → thấy `terraform plan` chạy trên PR

Lỗi hay gặp: `AADSTS70021` = subject của federated credential không khớp repo/branch.
Streamlit kẹt "Please wait…" = thiếu websockets hoặc sai port.

---

## Phase 6 — Quan sát + chụp ảnh (≈30 phút)

```
Add Application Insights / OpenTelemetry instrumentation to the FastAPI app
(azure-monitor-opentelemetry) so requests and exceptions show up. Log trip size and processing time
for /trace/clean. Keep it minimal. Then update README with: what the project is, the architecture,
how to run locally, how deployment works, and placeholders for screenshots and real results.
State clearly that data is simulated.
```

🧑 Việc của bạn: chụp UI trên Azure, các workflow xanh, App Insights có request.
Mở **PR #2** (`feat/observability`), chờ xanh, merge → `deploy-app` tự deploy lại. **Hết ngày 1.**

---

## Phase 7 — Hạ tầng Databricks (≈1 giờ)

```
Write infra/databricks (separate backend key "databricks.tfstate"):
- azurerm_databricks_workspace, sku premium, southeastasia, its own resource group.
- databricks provider configured against that workspace (azure_workspace_resource_id + host).
- A cluster policy that forces single node, node type Standard_DS3_v2, autotermination 15 minutes.
- One single-node cluster using that policy: num_workers = 0,
  spark_conf spark.databricks.cluster.profile=singleNode and spark.master=local[*],
  custom_tags ResourceClass=SingleNode, data_security_mode SINGLE_USER for my user,
  latest LTS runtime via databricks_spark_version data source.
- Outputs: workspace URL, cluster id.
My subscription allows only ~4 vCPU per region, so never more than one 4-core node.
Show me the commands, and how to destroy it at the end of the day.
```

🧑 Việc của bạn: `terraform init && terraform apply` trong `infra/databricks`, mở workspace URL, đăng nhập.
Mở **PR #3** (`infra/databricks`), chờ xanh, merge.

Kiểm tra:
- [ ] Cluster khởi động được (không báo `QuotaExceeded`)
- [ ] Cluster tự tắt sau 15 phút không dùng

---

## Phase 8 — Pipeline Bronze → Silver → Gold (≈2,5 giờ)

```
Build the Databricks pipeline as Python source notebooks in databricks/notebooks/:
- A script scripts/make_fleet.py that generates 200 simulated trips with varying noise and jump
  counts (trip_id column added) into data/fleet/*.csv, plus instructions to upload them to a
  Unity Catalog volume with the Databricks CLI (dbfs:/Volumes/<catalog>/gnss/raw/).
- 00_setup: CREATE SCHEMA IF NOT EXISTS gnss; CREATE VOLUME IF NOT EXISTS gnss.raw.
- 01_bronze: read all CSVs from the volume, add trip_id + ingest time, write Delta table gnss.bronze_points.
- 02_silver: make the repo's geo/ package importable (sys.path to the bundle files), then
  groupBy("trip_id").applyInPandas(clean_trip, schema) using geo.clean_trace; write gnss.silver_points.
- 03_gold: one row per trip: points, distance_km, anomaly_pct, pct_in_odd, median_err_raw_m,
  median_err_smooth_m, usable (anomaly_pct < 5 and pct_in_odd > 80); write gnss.gold_trip_quality.
Keep each notebook short and idempotent (overwrite mode). Tell me the order to run them.
```

🧑 Việc của bạn: chạy `make_fleet.py`, upload dữ liệu theo hướng dẫn, chạy lần lượt 4 notebook trên cluster.
Mở **PR #4** (`feat/databricks-pipeline`), chờ xanh, merge.

Kiểm tra:
- [ ] `SELECT count(*) FROM gnss.gold_trip_quality` = 200
- [ ] Silver dùng **chung** code `geo/` (không copy-paste thuật toán vào notebook)
- [ ] Ghi lại số thật: bao nhiêu chuyến `usable`, sai số trung vị trước/sau lọc

---

## Phase 9 — Job, dashboard và Asset Bundle (≈1,5 giờ, bản đầy đủ)

```
1) Create databricks/databricks.yml (Databricks Asset Bundle) that syncs geo/ and the notebooks,
   and defines a job "gnss_quality" running 00→03 in order on the existing single-node cluster id
   (variable). Target "dev" = my workspace.
2) Add .github/workflows/deploy-databricks.yml: on push to main touching databricks/** or geo/**,
   install Databricks CLI, authenticate to the workspace with GitHub OIDC (Azure workload identity
   federation via the same managed identity; add it to the workspace if needed and tell me how),
   then databricks bundle validate and databricks bundle deploy -t dev.
3) Give me SQL queries for a dashboard: usable vs not usable trips, anomaly % per trip (bar),
   worst 10 trips, and anomaly points on a map.
```

🧑 Việc của bạn: thêm managed identity vào workspace (nếu AI yêu cầu), tạo dashboard từ các câu SQL, chạy job một lần.
Mở **PR #5** (`feat/databricks-bundle`), chờ xanh, merge → `deploy-databricks` chạy trên `main`.

Kiểm tra:
- [ ] Sau merge PR #5, workflow deploy-databricks trên `main` xanh
- [ ] Job chạy hết 4 bước từ giao diện Jobs
- [ ] Dashboard có số liệu

Nếu kẹt ở xác thực OIDC cho Databricks quá 1 giờ: bỏ bước 2, giữ bundle deploy chạy từ máy local. CV vẫn đúng với "workspace via Terraform".

---

## Phase 10 — Hoàn thiện (≈1 giờ)

```
Update README with the final architecture diagram (mermaid), screenshots list, and a Results
section where I will paste real numbers. Add a "Limitations" section: simulated data, simple
constant-velocity Kalman, single-node Databricks due to subscription quota.
Review the whole repo for secrets, unused files and broken links, and list anything I should fix.
```

🧑 Việc của bạn:
- Dán số liệu **thật** vào README, chụp dashboard, mở **PR #6** (`docs/final-readme`), merge
- `terraform destroy` trong `infra/databricks` (và `infra/app` nếu không cần demo ngay)
- Cập nhật CV nếu số chuyến hoặc phạm vi khác với bản hiện tại

---

## Mẹo khi vibe code

- **Commit + push sau mỗi phase** (từ Phase 5 qua PR). AI làm hỏng thì `git checkout .` quay lại, đỡ mất cả buổi.
- **Đọc diff trước khi chấp nhận**, nhất là Terraform: chú ý tên resource, region, SKU, số node.
- AI hay "tự sáng tạo" thuật toán. Nhắc: *"port from reference/demo.py, don't change the logic"*.
- Khi lỗi, dán **nguyên văn** thông báo lỗi cho AI, kèm lệnh bạn vừa chạy.
- **Hiểu từng phần trước khi sang phase sau.** Phỏng vấn sẽ hỏi vì sao chọn OIDC, state để ở đâu,
  vì sao single-node. Hỏi lại AI: *"explain this file to me as if I must defend it in an interview"*.
