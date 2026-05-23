#!/usr/bin/env python3
"""Train Sentinel's XGBoost classifier.

Pipeline:
    1. Load Backblaze SMART quarterly CSV(s) from `data/backblaze/`.
       Run `scripts/download_backblaze.sh` first.
    2. Engineer features that mirror Sentinel's online feature_columns():
       per-disk rolling mean/max/slope/count for matching SMART attrs.
    3. Label rows `failure_within_24h` using the Backblaze `failure` column
       projected backwards onto the preceding observation rows.
    4. Synthesize GPU XID + ECC samples so the model also sees GPU
       failure shapes (Backblaze is disks only).
    5. Train XGBoost binary classifier; print precision/recall on a
       held-out slice; persist to `data/models/sentinel.xgb`.

Usage:
    python scripts/train_sentinel.py
    python scripts/train_sentinel.py --max-rows 500000 --horizon-h 24

The defaults target the Week-4 success criterion: precision@24h > 0.7.
Tune `--horizon-h` and `--max-rows` as needed for your machine.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Make `apps.*` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.agents.sentinel.features import FEATURE_METRICS, feature_columns  # noqa: E402
from apps.ingestion.schema import CanonicalMetric  # noqa: E402

# ---------------------------------------------------------------------------
# Backblaze SMART → DCOps canonical feature mapping
# ---------------------------------------------------------------------------
# Backblaze CSV columns we care about. Most SMART metrics map to two columns
# (`smart_N_normalized` and `smart_N_raw`); we use the raw values.
#   smart_5_raw   → reallocated sectors          → disk.reallocated.sectors
#   smart_197_raw → current pending sectors      → disk.pending.sectors
#   smart_194_raw → temperature C                → disk.temp.celsius
_BB_TO_CANONICAL: dict[str, CanonicalMetric] = {
    "smart_5_raw":   CanonicalMetric.DISK_REALLOCATED_SECTORS,
    "smart_197_raw": CanonicalMetric.DISK_PENDING_SECTORS,
    "smart_194_raw": CanonicalMetric.DISK_TEMP_CELSIUS,
}


def _project_failure_label(
    rows: list[dict[str, Any]],
    horizon_h: float,
) -> list[int]:
    """Label a row as positive iff this disk fails within `horizon_h` hours.

    Assumes `rows` are sorted by `date` ascending for one serial number.
    The Backblaze schema has a `failure=1` row on the day the drive died;
    we walk backwards and tag all rows within the horizon as positive.
    """
    n = len(rows)
    labels = [0] * n
    # Find failure indices.
    failure_idx = [i for i, r in enumerate(rows) if int(r.get("failure", 0) or 0) == 1]
    if not failure_idx:
        return labels
    # Mark all rows within horizon-h days of any failure as positive.
    horizon_days = horizon_h / 24.0
    for fi in failure_idx:
        # date is "YYYY-MM-DD"; treat each row as one day apart.
        for j in range(fi, -1, -1):
            if (fi - j) > horizon_days:
                break
            labels[j] = 1
    return labels


def _rows_to_feature_dict(
    rows: list[dict[str, Any]],
    *,
    samples_per_window: int = 10,
) -> dict[str, float]:
    """Compute the canonical feature columns from a window of rows."""
    feats: dict[str, float] = {}
    for col in feature_columns():
        feats[col] = math.nan
    for bb_col, canonical in _BB_TO_CANONICAL.items():
        values: list[float] = []
        for r in rows[-samples_per_window:]:
            v = r.get(bb_col)
            if v in (None, "", "NA"):
                continue
            try:
                values.append(float(v))
            except (ValueError, TypeError):
                continue
        if not values:
            continue
        feats[f"{canonical.value}__mean"] = sum(values) / len(values)
        feats[f"{canonical.value}__max"] = max(values)
        feats[f"{canonical.value}__count"] = float(len(values))
        feats[f"{canonical.value}__slope_per_min"] = (
            (values[-1] - values[0]) / max(1, len(values))
        )
    return feats


def _load_backblaze(
    data_dir: Path,
    max_rows: int,
    horizon_h: float,
) -> tuple[list[dict[str, float]], list[int]]:
    """Stream-read every CSV in `data_dir`, group by serial, build (X, y).

    Returns lists of feature dicts (one row per window) and 0/1 labels.
    """
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas required: `uv add pandas`") from exc

    rows_seen = 0
    by_serial: dict[str, list[dict[str, Any]]] = {}

    csvs = sorted(data_dir.glob("**/*.csv"))
    if not csvs:
        raise FileNotFoundError(
            f"No CSVs under {data_dir}. Run scripts/download_backblaze.sh first."
        )

    keep_cols = ["date", "serial_number", "failure", *_BB_TO_CANONICAL.keys()]

    for csv in csvs:
        try:
            df = pd.read_csv(csv, usecols=lambda c: c in keep_cols)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] skipping {csv}: {exc}", file=sys.stderr)
            continue
        df = df.sort_values(["serial_number", "date"])
        for _, row in df.iterrows():
            serial = row.get("serial_number")
            if not isinstance(serial, str):
                continue
            by_serial.setdefault(serial, []).append(row.to_dict())
            rows_seen += 1
            if rows_seen >= max_rows:
                break
        if rows_seen >= max_rows:
            break

    feats_out: list[dict[str, float]] = []
    labels_out: list[int] = []
    for serial, rows in by_serial.items():
        if len(rows) < 5:
            continue
        labels = _project_failure_label(rows, horizon_h)
        # Build one feature window per row (excluding the first 4 — too little history).
        for i in range(4, len(rows)):
            window = rows[max(0, i - 9): i + 1]
            feats_out.append(_rows_to_feature_dict(window))
            labels_out.append(labels[i])
    return feats_out, labels_out


def _synthesize_gpu(n_per_class: int) -> tuple[list[dict[str, float]], list[int]]:
    """Generate synthetic GPU samples so the model also sees GPU failure shapes."""
    import random
    rng = random.Random(42)
    feats_out: list[dict[str, float]] = []
    labels_out: list[int] = []

    def _empty() -> dict[str, float]:
        return {c: math.nan for c in feature_columns()}

    # Healthy GPUs — moderate temps, no ECC, util varies.
    for _ in range(n_per_class):
        f = _empty()
        f["gpu.temp.celsius__mean"] = rng.uniform(60.0, 75.0)
        f["gpu.temp.celsius__max"] = f["gpu.temp.celsius__mean"] + rng.uniform(0, 4)
        f["gpu.temp.celsius__slope_per_min"] = rng.uniform(-0.2, 0.2)
        f["gpu.temp.celsius__count"] = 10.0
        f["gpu.power.watts__mean"] = rng.uniform(300.0, 450.0)
        f["gpu.power.watts__count"] = 10.0
        f["gpu.util.percent__mean"] = rng.uniform(30.0, 90.0)
        f["gpu.ecc.correctable__count"] = 10.0
        f["gpu.ecc.correctable__mean"] = rng.uniform(0.0, 5.0)
        feats_out.append(f)
        labels_out.append(0)

    # Failing GPUs — ECC spikes, temp climbing, XID present.
    for _ in range(n_per_class):
        f = _empty()
        f["gpu.temp.celsius__mean"] = rng.uniform(82.0, 95.0)
        f["gpu.temp.celsius__max"] = f["gpu.temp.celsius__mean"] + rng.uniform(2, 6)
        f["gpu.temp.celsius__slope_per_min"] = rng.uniform(0.5, 2.5)
        f["gpu.temp.celsius__count"] = 10.0
        f["gpu.power.watts__mean"] = rng.uniform(350.0, 500.0)
        f["gpu.power.watts__count"] = 10.0
        f["gpu.util.percent__mean"] = rng.uniform(40.0, 100.0)
        f["gpu.ecc.correctable__mean"] = rng.uniform(500.0, 5000.0)
        f["gpu.ecc.correctable__max"] = f["gpu.ecc.correctable__mean"] * rng.uniform(1.5, 4.0)
        f["gpu.ecc.correctable__count"] = 10.0
        f["gpu.ecc.uncorrectable__max"] = float(rng.choice([0, 0, 1, 3]))
        f["gpu.ecc.uncorrectable__count"] = 10.0
        f["gpu.xid.code__max"] = float(rng.choice([0, 43, 48, 63]))
        feats_out.append(f)
        labels_out.append(1)

    return feats_out, labels_out


def _train(X: Any, y: Any, *, n_splits: int = 1) -> tuple[Any, dict[str, float]]:
    try:
        import numpy as np
        import xgboost as xgb
        from sklearn.metrics import (
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )
        from sklearn.model_selection import train_test_split
    except ImportError as exc:
        raise RuntimeError(
            "Training requires xgboost + scikit-learn + numpy"
        ) from exc

    X_arr = np.asarray(X, dtype=float)
    y_arr = np.asarray(y, dtype=int)
    X_train, X_val, y_train, y_val = train_test_split(
        X_arr, y_arr, test_size=0.2, random_state=42, stratify=y_arr
    )

    # Handle class imbalance: scale_pos_weight = (neg / pos).
    pos = max(int(y_train.sum()), 1)
    neg = int(len(y_train) - pos)
    scale_pos_weight = neg / pos

    booster = xgb.train(
        params={
            "objective": "binary:logistic",
            "eval_metric": "aucpr",
            "max_depth": 6,
            "eta": 0.1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "scale_pos_weight": scale_pos_weight,
            "tree_method": "hist",
            "nthread": 4,
            "verbosity": 1,
        },
        dtrain=xgb.DMatrix(X_train, label=y_train, feature_names=feature_columns()),
        num_boost_round=200,
        evals=[
            (xgb.DMatrix(X_val, label=y_val, feature_names=feature_columns()), "val"),
        ],
        early_stopping_rounds=20,
        verbose_eval=False,
    )

    val_pred = booster.predict(
        xgb.DMatrix(X_val, feature_names=feature_columns())
    )
    val_label = (val_pred >= 0.5).astype(int)
    metrics = {
        "precision": float(precision_score(y_val, val_label, zero_division=0)),
        "recall": float(recall_score(y_val, val_label, zero_division=0)),
        "f1": float(f1_score(y_val, val_label, zero_division=0)),
        "auc_pr": float(roc_auc_score(y_val, val_pred)),
        "pos_rate_val": float(y_val.mean()),
        "n_train": int(len(y_train)),
        "n_val": int(len(y_val)),
    }
    return booster, metrics


def _feats_to_matrix(feats: list[dict[str, float]]) -> Iterable[list[float]]:
    cols = feature_columns()
    for f in feats:
        yield [f.get(c, math.nan) for c in cols]


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Sentinel XGBoost classifier.")
    parser.add_argument("--data-dir", default="data/backblaze",
                        help="Directory of Backblaze SMART CSVs (recursive).")
    parser.add_argument("--model-out", default="data/models/sentinel.xgb")
    parser.add_argument("--max-rows", type=int, default=500_000,
                        help="Cap on Backblaze rows ingested.")
    parser.add_argument("--horizon-h", type=float, default=24.0,
                        help="Failure-within horizon (hours) for labeling.")
    parser.add_argument("--synthetic-gpu-n", type=int, default=20_000,
                        help="Synthetic GPU samples per class.")
    parser.add_argument("--skip-backblaze", action="store_true",
                        help="Train on synthetic data only (smoke test).")
    args = parser.parse_args()

    print(f"[train] feature columns: {len(feature_columns())}")

    feats: list[dict[str, float]] = []
    labels: list[int] = []

    if not args.skip_backblaze:
        try:
            bb_feats, bb_labels = _load_backblaze(
                Path(args.data_dir), args.max_rows, args.horizon_h
            )
        except FileNotFoundError as exc:
            print(f"[train] {exc}", file=sys.stderr)
            print("[train] use --skip-backblaze to train on synthetic only.")
            sys.exit(2)
        print(f"[train] Backblaze: {len(bb_feats):,} rows, "
              f"positive rate {sum(bb_labels) / max(1, len(bb_labels)):.4%}")
        feats.extend(bb_feats)
        labels.extend(bb_labels)

    gpu_feats, gpu_labels = _synthesize_gpu(args.synthetic_gpu_n)
    feats.extend(gpu_feats)
    labels.extend(gpu_labels)
    print(f"[train] synthetic GPU: {len(gpu_feats):,} rows "
          f"({args.synthetic_gpu_n} per class)")

    if not feats:
        print("[train] no data to train on", file=sys.stderr)
        sys.exit(1)

    X = list(_feats_to_matrix(feats))
    booster, metrics = _train(X, labels)

    out_path = Path(args.model_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out_path))
    print(f"[train] saved: {out_path}")
    print("[train] metrics:")
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: {v}")

    if metrics["precision"] < 0.7:
        print("[train] WARNING: precision < 0.7 — Week 4 success criterion not met.")


if __name__ == "__main__":
    main()
