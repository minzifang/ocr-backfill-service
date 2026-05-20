#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "$ROOT_DIR/deploy/ocr-service/VERSION")"
OUT_DIR="$ROOT_DIR/dist"
OUT_FILE="$OUT_DIR/ocr-service-deploy-${VERSION}.tar.gz"

mkdir -p "$OUT_DIR"

tar -czf "$OUT_FILE" \
  -C "$ROOT_DIR" \
  docker-compose.ocr.yml \
  docker-compose.ocr.cpu-fast.yml \
  docker-compose.ocr.rapid.yml \
  docker-compose.ocr.gpu.yml \
  docker-compose.ocr.gpu-shadow.yml \
  requirements-ocr-service.txt \
  requirements-ocr-service-rapid.txt \
  requirements-ocr-service-gpu-cu118.txt \
  deploy/ocr-service/Dockerfile \
  deploy/ocr-service/Dockerfile.rapid \
  deploy/ocr-service/Dockerfile.gpu \
  deploy/ocr-service/VERSION \
  src/ocr_backfill

echo "$OUT_FILE"
