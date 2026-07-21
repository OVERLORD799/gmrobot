#!/usr/bin/env bash
# Export the built image as a tar archive for transfer to another machine.
#
# Usage:
#   ./export.sh              # export as gmdisturb_latest.tar
#   ./export.sh --tag v2.0   # export a specific tag
set -euo pipefail

TAG="gmdisturb:paper-demo-20260718"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    *)     echo "Unknown: $1"; exit 1 ;;
  esac
done

OUTFILE="gmdisturb_$(echo "${TAG}" | tr '/:' '_').tar"

echo "Exporting ${TAG} -> ${OUTFILE}..."
docker save -o "${OUTFILE}" "${TAG}"
ls -lh "${OUTFILE}"
echo "Transfer: scp ${OUTFILE} user@target-machine:/path/"
echo "Load:     docker load < ${OUTFILE}"
