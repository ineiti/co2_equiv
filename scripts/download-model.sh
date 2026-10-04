#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  source .env
  set +a
elif [ -f .env.example ]; then
  set -a
  source .env.example
  set +a
fi

if [ -z "${MODEL_URL:-}" ]; then
  echo "Error: MODEL_URL is not set (checked .env and .env.example)." >&2
  exit 1
fi

TARGET_DIR="./data/llm"
TARGET_FILE="$TARGET_DIR/model.gguf"

if [ -f "$TARGET_FILE" ]; then
  echo "Model already present at $TARGET_FILE, skipping download."
  exit 0
fi

mkdir -p "$TARGET_DIR"
echo "Downloading model from $MODEL_URL to $TARGET_FILE ..."
curl -L --fail -o "$TARGET_FILE" "$MODEL_URL"
echo "Done."
