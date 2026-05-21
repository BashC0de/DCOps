#!/usr/bin/env bash
# =============================================================================
# DESTRUCTIVE: wipe TimescaleDB, Neo4j, and Chroma volumes.
# =============================================================================
# Usage: bash scripts/reset_db.sh
# Confirms before acting. Equivalent to `make nuke` but with friendlier prompts.
# =============================================================================

set -euo pipefail

echo "This will delete ALL persistent data in TimescaleDB, Neo4j, ChromaDB, and MinIO."
read -p "Type 'reset' to confirm: " confirm
if [[ "${confirm}" != "reset" ]]; then
  echo "Aborted."
  exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."
docker compose --profile demo down -v
echo "Volumes deleted. Run 'make seed' to repopulate."
