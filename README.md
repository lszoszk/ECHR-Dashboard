# ECHR Dashboard

This repository includes a full ECHR dashboard project with:

- Online static search app (no install needed): `docs/index.html`
- Online analytics dashboard: `docs/analytics.html`
- Flask app (optional local backend version): `echr_dashboard/`
- Sample JSONL dataset for testing: `data/echr_decisions_sample.jsonl`

## Online access (no installation)

After GitHub Pages deploy is active, use:

- Search app: `https://lszoszk.github.io/ECHR-Dashboard/`
- Analytics: `https://lszoszk.github.io/ECHR-Dashboard/analytics.html`

## Quick start (local)

1. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. Launch the app:

```bash
bash echr_dashboard/run.sh
```

Open: `http://127.0.0.1:5001`

## Dataset selection

The app resolves dataset files in this order:

1. `ECHR_DATA_FILE` (if set)
2. `data/echr_decisions_sample.jsonl`
3. `echr_cases_optionB.jsonl`
4. `echr_cases_20260207_121847.jsonl`

Example with a custom dataset:

```bash
ECHR_DATA_FILE=/absolute/path/to/your_cases.jsonl python3 echr_dashboard/app.py
```

## Build static GitHub Pages dashboard

```bash
python3 scripts/build_pages_dashboard.py
```

This regenerates:

- `docs/data/stats.json` (analytics payload)
- `docs/data/echr_cases.jsonl` (dataset used by the online search app)

## GitHub Pages deployment

Workflow file: `.github/workflows/deploy-pages.yml`

On each push to `main`/`master`, GitHub Actions:

1. Builds `docs/data/stats.json`
2. Copies JSONL dataset to `docs/data/echr_cases.jsonl`
3. Uploads `docs/`
4. Deploys to GitHub Pages

Enable Pages in repository settings:

- Settings → Pages → Source: **GitHub Actions**
