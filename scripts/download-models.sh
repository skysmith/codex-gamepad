#!/bin/bash

set -euo pipefail

DESTINATION=${1:-"$HOME/.local/share/codex-gamepad/models"}
BASE_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
MODEL_SHA256="7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"
VOICES_SHA256="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"

mkdir -p "$DESTINATION"

download() {
  local name=$1
  local expected=$2
  local output="$DESTINATION/$name"
  local temporary="$output.part"
  if [[ -f "$output" ]] && [[ "$(shasum -a 256 "$output" | awk '{print $1}')" == "$expected" ]]; then
    echo "$name already verified"
    return
  fi
  curl -fL --retry 3 --progress-bar "$BASE_URL/$name" -o "$temporary"
  local actual
  actual=$(shasum -a 256 "$temporary" | awk '{print $1}')
  if [[ "$actual" != "$expected" ]]; then
    rm -f "$temporary"
    echo "Checksum failed for $name" >&2
    exit 1
  fi
  chmod 644 "$temporary"
  mv "$temporary" "$output"
}

download "kokoro-v1.0.onnx" "$MODEL_SHA256"
download "voices-v1.0.bin" "$VOICES_SHA256"

echo "Kokoro model files installed in $DESTINATION"
