#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PREFIX=${CODEX_GAMEPAD_PREFIX:-"$HOME/.local/share/codex-gamepad"}
BIN_DIR=${CODEX_GAMEPAD_BIN_DIR:-"$HOME/.local/bin"}
PLIST="$HOME/Library/LaunchAgents/com.codex-gamepad.receiver.plist"
RULE="$HOME/.config/karabiner/assets/complex_modifications/codex-gamepad.json"
REMOVE_MODELS=0
KARABINER_CONFIG=${CODEX_GAMEPAD_KARABINER_CONFIG:-"$HOME/.config/karabiner/karabiner.json"}
RUNTIME_DIR="$HOME/Library/Application Support/Codex Gamepad"

canonical_under_home() {
  local value=${1%/}
  local existing suffix name base home_base
  [[ "$value" == /* ]] || return 1
  case "$value/" in
    */../*|*/./*) return 1 ;;
  esac
  existing=$value
  suffix=
  while [[ ! -e "$existing" ]]; do
    name=${existing##*/}
    suffix="/$name$suffix"
    existing=${existing%/*}
    [[ -n "$existing" ]] || existing=/
  done
  [[ -d "$existing" ]] || return 1
  base=$(cd -P "$existing" && pwd)
  home_base=$(cd -P "$HOME" && pwd)
  value="$base$suffix"
  [[ "$value" == "$home_base/"* ]] || return 1
  printf '%s\n' "$value"
}

find_python() {
  local name candidate
  if [[ -n "${CODEX_GAMEPAD_PYTHON:-}" ]] && is_supported_python "$CODEX_GAMEPAD_PYTHON"; then
    printf '%s\n' "$CODEX_GAMEPAD_PYTHON"
    return
  fi
  if is_supported_python "$PREFIX/venv/bin/python"; then
    printf '%s\n' "$PREFIX/venv/bin/python"
    return
  fi
  for name in python3.13 python3.12 python3.11 python3.10 python3 /usr/bin/python3; do
    if candidate=$(command -v "$name" 2>/dev/null) && is_supported_python "$candidate"; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  return 1
}

is_supported_python() {
  [[ -x "$1" ]] && "$1" -c '
import sys
raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 14) else 1)
' >/dev/null 2>&1
}

if ! PREFIX=$(canonical_under_home "$PREFIX"); then
  echo "Unsafe CODEX_GAMEPAD_PREFIX: $PREFIX" >&2
  exit 2
fi
if ! BIN_DIR=$(canonical_under_home "$BIN_DIR"); then
  echo "Unsafe CODEX_GAMEPAD_BIN_DIR: $BIN_DIR" >&2
  exit 2
fi
if ! RUNTIME_DIR=$(canonical_under_home "$RUNTIME_DIR"); then
  echo "Unsafe Codex Gamepad runtime directory: $RUNTIME_DIR" >&2
  exit 2
fi
PROFILE_STATE="$RUNTIME_DIR/karabiner-profile-state.json"

if [[ ${1:-} == "--models" ]]; then
  REMOVE_MODELS=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--models]" >&2
  exit 2
fi

MARKER="$PREFIX/.codex-gamepad-install"
OWNERSHIP_MANIFEST="$PREFIX/.codex-gamepad-ownership.json"
if [[ ! -f "$MARKER" || -L "$MARKER" ]] || ! grep -qx 'codex-gamepad-v1' "$MARKER"; then
  echo "Install marker missing; left $PREFIX untouched." >&2
  exit 1
fi

PROFILE_PYTHON=$(find_python 2>/dev/null || true)
if [[ -z "$PROFILE_PYTHON" ]]; then
  echo "Python 3.10–3.13 is required to verify install ownership and restore profiles safely." >&2
  exit 1
fi

OWNERSHIP_HELPER="$PREFIX/scripts/manage_install_ownership.py"
if [[ ! -f "$OWNERSHIP_HELPER" || -L "$OWNERSHIP_HELPER" ]]; then
  OWNERSHIP_HELPER="$ROOT/scripts/manage_install_ownership.py"
fi
if [[ ! -f "$OWNERSHIP_HELPER" || -L "$OWNERSHIP_HELPER" ]]; then
  echo "Install ownership helper is missing or unsafe; rerun the source installer." >&2
  exit 1
fi

UNINSTALL_LAUNCHER="$BIN_DIR/codex-gamepad-uninstall"
OWNERSHIP_ALLOWED=(
  --allow-regular launcher "$BIN_DIR/codex-speak-last"
  --allow-symlink uninstaller "$UNINSTALL_LAUNCHER" "$PREFIX/scripts/uninstall-local.sh"
  --allow-regular karabiner_rule "$RULE"
  --allow-regular launch_agent "$PLIST"
)

PROFILES_EXPECTED=$("$PROFILE_PYTHON" "$OWNERSHIP_HELPER" status \
  --manifest "$OWNERSHIP_MANIFEST" \
  "${OWNERSHIP_ALLOWED[@]}" \
  --field profiles-expected)

PROFILE_HELPER="$PREFIX/scripts/configure_gamepad_profiles.py"
if [[ ! -f "$PROFILE_HELPER" || -L "$PROFILE_HELPER" ]]; then
  PROFILE_HELPER="$ROOT/scripts/configure_gamepad_profiles.py"
fi
PROFILE_STATE_PRESENT=0
if [[ -e "$PROFILE_STATE" || -L "$PROFILE_STATE" ]]; then
  PROFILE_STATE_PRESENT=1
fi
if [[ "$PROFILES_EXPECTED" == "1" || $PROFILE_STATE_PRESENT -eq 1 ]]; then
  if [[ ! -f "$PROFILE_HELPER" || -L "$PROFILE_HELPER" ]]; then
    echo "Installed Karabiner profile helper is missing or unsafe: $PROFILE_HELPER" >&2
    exit 1
  fi
fi
if [[ "$PROFILES_EXPECTED" == "1" ]]; then
  "$PROFILE_PYTHON" "$PROFILE_HELPER" \
    --config "$KARABINER_CONFIG" \
    --state "$PROFILE_STATE" \
    --check-remove
elif [[ $PROFILE_STATE_PRESENT -eq 1 ]]; then
  "$PROFILE_PYTHON" "$PROFILE_HELPER" \
    --config "$KARABINER_CONFIG" \
    --state "$PROFILE_STATE" \
    --check-finalize-remove
fi

HAS_LAUNCHER=$("$PROFILE_PYTHON" "$OWNERSHIP_HELPER" status \
  --manifest "$OWNERSHIP_MANIFEST" \
  "${OWNERSHIP_ALLOWED[@]}" \
  --field has-artifact \
  --name launcher)
if [[ "$HAS_LAUNCHER" == "1" ]]; then
  "$PROFILE_PYTHON" "$OWNERSHIP_HELPER" run-owned \
    --manifest "$OWNERSHIP_MANIFEST" \
    "${OWNERSHIP_ALLOWED[@]}" \
    --name launcher \
    -- --stop
fi

HAS_LAUNCH_AGENT=$("$PROFILE_PYTHON" "$OWNERSHIP_HELPER" status \
  --manifest "$OWNERSHIP_MANIFEST" \
  "${OWNERSHIP_ALLOWED[@]}" \
  --field has-artifact \
  --name launch_agent)
if [[ "$HAS_LAUNCH_AGENT" == "1" ]]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
fi

if [[ "$PROFILES_EXPECTED" == "1" ]]; then
  "$PROFILE_PYTHON" "$PROFILE_HELPER" \
    --config "$KARABINER_CONFIG" \
    --state "$PROFILE_STATE" \
    --prepare-remove
  "$PROFILE_PYTHON" "$OWNERSHIP_HELPER" set-profiles-expected \
    --manifest "$OWNERSHIP_MANIFEST" \
    "${OWNERSHIP_ALLOWED[@]}" \
    --value 0
  "$PROFILE_PYTHON" "$PROFILE_HELPER" \
    --config "$KARABINER_CONFIG" \
    --state "$PROFILE_STATE" \
    --finalize-remove
elif [[ $PROFILE_STATE_PRESENT -eq 1 ]]; then
  "$PROFILE_PYTHON" "$PROFILE_HELPER" \
    --config "$KARABINER_CONFIG" \
    --state "$PROFILE_STATE" \
    --finalize-remove
fi

"$PROFILE_PYTHON" "$OWNERSHIP_HELPER" remove-owned \
  --manifest "$OWNERSHIP_MANIFEST" \
  "${OWNERSHIP_ALLOWED[@]}"

if [[ $REMOVE_MODELS -eq 1 ]]; then
  rm -rf "$PREFIX"
else
  find "$PREFIX" -mindepth 1 -maxdepth 1 \
    ! -name models \
    ! -name .codex-gamepad-install \
    ! -name .codex-gamepad-ownership.json \
    -exec rm -rf {} +
fi

if [[ -d "$RUNTIME_DIR" ]]; then
  if [[ $REMOVE_MODELS -eq 1 ]]; then
    rm -rf "$RUNTIME_DIR"
  else
    find "$RUNTIME_DIR" -mindepth 1 -maxdepth 1 ! -name models -exec rm -rf {} +
  fi
fi

echo "Codex Gamepad removed."
