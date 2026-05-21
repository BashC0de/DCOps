#!/usr/bin/env bash
# =============================================================================
# Download Backblaze SMART dataset for Sentinel training.
# =============================================================================
# Ships: Week 4 (Sentinel training).
#
# Backblaze publishes quarterly drive-stats archives at:
#   https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data
# We download a recent quarter and stage it under data/backblaze/.
# =============================================================================

set -euo pipefail

DATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/backblaze"
mkdir -p "$DATA_DIR"

# Pick a known quarterly archive. Update when training on a newer quarter.
QUARTER="${BACKBLAZE_QUARTER:-data_Q1_2024}"
URL="https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/${QUARTER}.zip"

if [[ -f "${DATA_DIR}/${QUARTER}.zip" ]]; then
  echo "[backblaze] ${QUARTER}.zip already present; skipping download."
else
  echo "[backblaze] downloading ${URL}"
  curl -fL "${URL}" -o "${DATA_DIR}/${QUARTER}.zip"
fi

if [[ ! -d "${DATA_DIR}/${QUARTER}" ]]; then
  echo "[backblaze] extracting"
  unzip -q "${DATA_DIR}/${QUARTER}.zip" -d "${DATA_DIR}/"
fi

echo "[backblaze] ready in ${DATA_DIR}/${QUARTER}/"
