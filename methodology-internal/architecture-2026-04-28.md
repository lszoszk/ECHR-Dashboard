# VM Architecture After UHRI/ECHR Separation (2026-04-28)

## Background

Until 2026-04-28, the ECHR Dashboard backend (`echr-search-api` container) and the UHRI dataset API (`build_dataset_router` from `unhr_dataset_api.py`) ran inside the **same Docker container**, sharing one Python process and one `/app/main.py` file. Both project teams (the same owner — Łukasz Szoszkiewicz / HURIDOCS — but distinct codebases and deployment cadences) edited that one shared file via `docker cp`.

This caused multiple cross-project clobbering incidents. Most notably, on 2026-04-27 a UHRI deploy added `from unhr_dataset_api import build_dataset_router` to the shared `main.py` but did not include the granular `doc_types` filter (Chamber / Grand Chamber / Committee) the ECHR project had deployed earlier the same day. The ECHR filter was silently destroyed; the dashboard's filter UI continued to show the checkboxes but they had no effect on the backend. The regression went undetected until human review on 2026-04-28.

## Solution: Two compose projects, one VM

Rather than provision a new VM (cost, DNS, SSL coordination), the two apps were separated into two independent Docker compose projects on the existing VM `150.254.115.204`. Each project gets its own folder, container, port, image, and source repository. nginx remains the shared entry point and routes by URL path to the appropriate upstream.

### Final layout

```
VM 150.254.115.204
│
├── /home/amuvmuser/echr/                    ← ECHR Dashboard project
│   ├── docker-compose.yml                   container: echr-api, port 0.0.0.0:8000
│   ├── backend/                             (committed in lszoszk/ECHR-Dashboard)
│   │   ├── main.py                          ECHR API only — no UHRI imports
│   │   ├── Dockerfile                       no COPY unhr_dataset_api.py
│   │   ├── ranking.py
│   │   ├── build_db.py
│   │   ├── entrypoint.sh
│   │   └── requirements.txt
│   └── data/
│       ├── echr_search.db                   1.76 GB SQLite (FTS5 over 2M paragraphs)
│       ├── echr_search.db-shm
│       └── echr_search.db-wal
│
├── /home/amuvmuser/uhri/                    ← UHRI Dataset API project
│   ├── docker-compose.yml                   container: uhri-dataset-api, port 127.0.0.1:8001
│   ├── api/                                 (committed in lszoszk/uhri-dataset-api PRIVATE)
│   │   ├── main.py                          thin FastAPI wrapper
│   │   ├── unhr_dataset_api.py              router with 16 endpoints
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── data/
│       ├── uhri-export.json                 340 MB
│       ├── uhri-export.sqlite3              1.9 GB
│       ├── uhri-export.sqlite3-{shm,wal}
│       ├── uhri-export.final.jsonl          410 MB
│       └── pipeline/
│
├── /home/amuvmuser/mattermost-docker/       ← UHRI team comms (unchanged)
│   └── docker-compose.yml                   containers: mattermost, postgres
│
└── nginx /etc/nginx/sites-enabled/default
    ├── upstream echr_api   { server 127.0.0.1:8000; }   → echr-api container
    ├── upstream uhri_api   { server 127.0.0.1:8001; }   → uhri-dataset-api container
    └── upstream mattermost { server 127.0.0.1:8065; }   → Mattermost
```

### nginx routing (URL path → upstream)

| URL path | Upstream | Notes |
|----------|----------|-------|
| `/echr-api/api/*` | `echr_api` | ECHR full-text search (this project) |
| `/echr-api/health` | `echr_api` | ECHR liveness probe |
| `/echr-api/api/data/*` | `uhri_api` | Compatibility shim (deprecate eventually) |
| `/echr-api/api/feedback/*` | `uhri_api` | Compatibility shim |
| `/uhri-api/*` | `uhri_api` | UHRI canonical path (with caching/precompute) |
| `/api/data/*` | `uhri_api` | UHRI bare path (legacy) |
| `/api/feedback/*` | `uhri_api` | UHRI bare path (legacy) |

The `/echr-api/api/data/*` and `/echr-api/api/feedback/*` shims exist because the original ECHR Dashboard frontend was hard-coded to that path even though the endpoints belong to UHRI. They will be retired once any external consumers migrate.

### Source repositories

| Project | Repository | Visibility |
|---------|-----------|------------|
| ECHR Dashboard | `lszoszk/ECHR-Dashboard` | public |
| UHRI Dataset API | `lszoszk/uhri-dataset-api` | **PRIVATE** |
| UnitedNations_recommendations | `lszoszk/UnitedNations_recommendations` | public (analysis scripts only — separate from production API) |

### Deployment commands

**ECHR Dashboard (this repo):**
```bash
./deploy/deploy.sh <ssh_password>
# OR manually:
scp backend/{main.py,Dockerfile,*.sh,*.py,*.txt} amuvmuser@150.254.115.204:/home/amuvmuser/echr/backend/
ssh amuvmuser@150.254.115.204 "cd /home/amuvmuser/echr && docker compose up -d --build"
```

**UHRI Dataset API (separate repo):**
```bash
# from lszoszk/uhri-dataset-api repo:
scp {main.py,unhr_dataset_api.py,Dockerfile,requirements.txt} \
    amuvmuser@150.254.115.204:/home/amuvmuser/uhri/api/
ssh amuvmuser@150.254.115.204 "cd /home/amuvmuser/uhri && docker compose up -d --build"
```

**Critical:** never use `docker cp` directly into a running container. Always rebuild via `docker compose up -d --build`.

### Resource isolation guarantees

| Concern | Before (shared container) | After (separate containers) |
|---------|---------------------------|-----------------------------|
| `main.py` clobbering | Possible (both teams edited same file) | **Impossible** (each team's main.py in its own project) |
| Crash isolation | UHRI panic kills ECHR | Independent containers, independent restart policies |
| Memory leak in one team's code | Affects the other | `mem_limit: 3g` (echr) and `1g` (uhri) cap each independently |
| Independent deploy cadence | Coordination required | Each compose project deploys in seconds without affecting the other |
| Source code in version control | Mixed in one container | Two separate repos, two clean ownership boundaries |

### Migration backup

All artefacts from the migration are preserved in `/home/amuvmuser/migration-backup-20260428/` for ~1 week before deletion:

- `from-container/main.py` — `/app/main.py` from `echr-search-api` immediately before the split
- `from-container/unhr_dataset_api.py` — same, the UHRI router source baked into the old container
- `nginx/default.pre-uhri-split` — nginx config before the upstream port change
- `old-bak/` — 18 `.bak.*` files cleaned from the ECHR backend folder
- `home-cruft/` — 24 staging artefacts from `/home/amuvmuser/` (P1–P9 scripts, audit JSON files, sample regenerator outputs)

Total backup size: ~250 MB. Removable after stabilization confirmed.
