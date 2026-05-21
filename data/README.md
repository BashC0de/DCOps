# Data directory

Holds seed data, downloadable training datasets, and (gitignored) generated artifacts.

## Layout

```
data/
├── README.md                  ← you are here
├── seeds/                     ← committed seed files (small, curated)
│   ├── incidents_sample.json  ← seed incidents for ChromaDB embedding pre-fill
│   └── runbooks/              ← Markdown runbook chunks for Operator retrieval
└── backblaze/                 ← downloaded SMART dataset (gitignored)
```

## Backblaze SMART dataset

Used by **Sentinel** for predictive failure training (Week 4). Backblaze publishes quarterly drive-stats archives publicly:

https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data

Download a recent quarter:

```bash
bash scripts/download_backblaze.sh
# or with a specific quarter:
BACKBLAZE_QUARTER=data_Q1_2024 bash scripts/download_backblaze.sh
```

The full archive is ~2 GB. We use a single recent quarter for training/validation.

## Seed data

`data/seeds/` is committed. It holds small files that prime the system:

- **`incidents_sample.json`** — synthetic incident reports used to pre-fill the ChromaDB `incidents` collection so Forensic can retrieve "similar past incidents" on day 1. Ships Week 5.
- **`runbooks/`** — Markdown documents chunked and embedded into ChromaDB's `runbooks` collection for Operator. Ships Week 6.

## Generated / cached data

- `data/raw/` and `data/cache/` are gitignored. Anything regenerable lives here.
- Time-series telemetry lives in TimescaleDB, not in this directory.

## Licensing note

The Backblaze drive-stats dataset is published under the Creative Commons Attribution license. Cite Backblaze when republishing derived metrics.
