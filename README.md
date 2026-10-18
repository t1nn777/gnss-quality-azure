# GNSS Trace Quality Checker on Azure + Databricks

Personal proof-of-concept that cleans **simulated** vehicle GNSS traces (anomaly detection,
Kalman smoothing, ODD check) and runs on Azure. **All data is simulated, not real vehicle data.**

Work in progress – see `PROMPTS.md` for the phase plan and `CLAUDE.md` for project context.

## Quick start

```bash
python -m venv .venv
pip install -r api/requirements-dev.txt
pytest
python -m geo.generate_trace --seed 1 --out sample.csv
```
