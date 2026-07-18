#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PREFIX=${CODEX_GAMEPAD_PREFIX:-"$HOME/.local/share/codex-gamepad"}
BIN_DIR=${CODEX_GAMEPAD_BIN_DIR:-"$HOME/.local/bin"}
PYTHON=${CODEX_GAMEPAD_PYTHON:-}
PYTHON_CONFIGURED=0
[[ -n "$PYTHON" ]] && PYTHON_CONFIGURED=1
DRY_RUN=0
CREATE_VENV=0
WITH_KOKORO=0
SKIP_RECEIVER=0
SKIP_KARABINER=0
ENABLE_MANAGED_RULES=0
UV_BIN=${CODEX_GAMEPAD_UV:-}
RECEIVER_BINARY=
PROFILE_SOURCE=
KARABINER_CLI=${CODEX_GAMEPAD_KARABINER_CLI:-"/Library/Application Support/org.pqrs/Karabiner-Elements/bin/karabiner_cli"}
KARABINER_CONFIG=${CODEX_GAMEPAD_KARABINER_CONFIG:-"$HOME/.config/karabiner/karabiner.json"}
RUNTIME_DIR="$HOME/Library/Application Support/Codex Gamepad"
CODEX_PROFILE_NAME="Codex Controller"
GAME_PROFILE_NAME="Game Mode"
ARCADE_CHROME_MARKER=${CODEX_GAMEPAD_ARCADE_CHROME_MARKER:-"--user-data-dir=$HOME/Library/Application Support/Codex Arcade/Chrome"}
LIVING_FOREST_MARKER=${CODEX_GAMEPAD_LIVING_FOREST_MARKER:-"$HOME/Library/Application Support/Living Forest/runtime/players/"}
MODE_SWITCHING=0
OWNERSHIP_HELPER="$ROOT/scripts/manage_install_ownership.py"

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

MARKER="$PREFIX/.codex-gamepad-install"
OWNERSHIP_MANIFEST="$PREFIX/.codex-gamepad-ownership.json"
if [[ -e "$PREFIX" && ! -d "$PREFIX" ]]; then
  echo "CODEX_GAMEPAD_PREFIX is not a directory: $PREFIX" >&2
  exit 2
fi
LEGACY_MARKER_PREEXISTED=0
if [[ -f "$MARKER" && ! -L "$MARKER" ]] && grep -qx 'codex-gamepad-v1' "$MARKER"; then
  LEGACY_MARKER_PREEXISTED=1
fi
if [[ -d "$PREFIX" && $LEGACY_MARKER_PREEXISTED -eq 0 ]]; then
  if [[ -n "$(find "$PREFIX" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "Refusing nonempty unowned prefix: $PREFIX" >&2
    exit 2
  fi
fi

PREFIX_EXISTED_AT_START=0
[[ -d "$PREFIX" ]] && PREFIX_EXISTED_AT_START=1
VENV_CREATED_THIS_INVOCATION=0
INSTALL_TEMP=
cleanup_install_attempt() {
  local status=$?
  if [[ -n "$INSTALL_TEMP" ]]; then
    rm -rf "$INSTALL_TEMP"
  fi
  if ((status != 0 && VENV_CREATED_THIS_INVOCATION == 1)); then
    rm -rf "$PREFIX/venv"
    if ((LEGACY_MARKER_PREEXISTED == 0)); then
      rm -f "$MARKER"
    fi
    if ((PREFIX_EXISTED_AT_START == 0)); then
      rmdir "$PREFIX" 2>/dev/null || true
    fi
  fi
  trap - EXIT
  exit "$status"
}
trap cleanup_install_attempt EXIT

usage() {
  echo "Usage: $0 [--dry-run] [--python PATH] [--create-venv] [--uv PATH] [--with-kokoro] [--receiver-binary PATH] [--profile PATH] [--enable-managed-rules] [--skip-receiver] [--skip-karabiner]"
}

while (($#)); do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --python)
      shift
      PYTHON=${1:?--python requires a path}
      PYTHON_CONFIGURED=1
      ;;
    --create-venv)
      CREATE_VENV=1
      ;;
    --uv)
      shift
      UV_BIN=${1:?--uv requires a path}
      ;;
    --with-kokoro)
      WITH_KOKORO=1
      ;;
    --receiver-binary)
      shift
      RECEIVER_BINARY=${1:?--receiver-binary requires a path}
      ;;
    --profile)
      shift
      PROFILE_SOURCE=${1:?--profile requires a path}
      ;;
    --enable-managed-rules)
      ENABLE_MANAGED_RULES=1
      ;;
    --skip-receiver)
      SKIP_RECEIVER=1
      ;;
    --skip-karabiner)
      SKIP_KARABINER=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  shift
done

has_kokoro() {
  [[ -x "$1" ]] && "$1" -c '
import importlib.metadata
import sys
import kokoro_onnx
import soundfile
supported = (3, 10) <= sys.version_info[:2] < (3, 14)
version = importlib.metadata.version("kokoro-onnx")
raise SystemExit(0 if supported and version == "0.5.0" else 1)
' >/dev/null 2>&1
}

is_supported_python() {
  [[ -x "$1" ]] && "$1" -c '
import sys
raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 14) else 1)
' >/dev/null 2>&1
}

if [[ $CREATE_VENV -eq 1 && $PYTHON_CONFIGURED -eq 1 ]]; then
  echo "--create-venv cannot be combined with --python or CODEX_GAMEPAD_PYTHON." >&2
  exit 2
fi

if [[ $CREATE_VENV -eq 1 ]]; then
  if [[ -z "$UV_BIN" ]]; then
    UV_BIN=$(command -v uv 2>/dev/null || true)
  fi
  if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
    echo "uv is required for --create-venv; pass --uv PATH or install uv." >&2
    exit 1
  fi
  PYTHON="$PREFIX/venv/bin/python"
  if [[ $DRY_RUN -eq 0 && ! -x "$PYTHON" ]]; then
    if [[ ! -e "$PREFIX/venv" && ! -L "$PREFIX/venv" ]]; then
      VENV_CREATED_THIS_INVOCATION=1
    fi
    mkdir -p "$PREFIX"
    "$UV_BIN" venv --python 3.13 "$PREFIX/venv"
  fi
  if [[ $DRY_RUN -eq 0 && $WITH_KOKORO -eq 1 ]]; then
    "$UV_BIN" pip install --python "$PYTHON" 'kokoro-onnx==0.5.0' 'soundfile>=0.12,<1'
  fi
fi

if [[ -z "$PYTHON" ]]; then
  candidates=(
    "$PREFIX/venv/bin/python"
  )
  for name in python3.13 python3.12 python3.11 python3.10 python3; do
    if candidate=$(command -v "$name" 2>/dev/null); then
      candidates+=("$candidate")
    fi
  done
  for candidate in "${candidates[@]}"; do
    if is_supported_python "$candidate" && { [[ $WITH_KOKORO -eq 0 ]] || has_kokoro "$candidate"; }; then
      PYTHON=$candidate
      break
    fi
  done
fi

if [[ $PYTHON_CONFIGURED -eq 1 ]] && ! is_supported_python "$PYTHON"; then
  echo "--python and CODEX_GAMEPAD_PYTHON must name an executable Python 3.10–3.13 interpreter." >&2
  exit 1
fi

if [[ -z "$PYTHON" ]]; then
  echo "A Python 3.10–3.13 environment is required." >&2
  echo "Pass --python PATH or use --create-venv." >&2
  exit 1
fi
if [[ $DRY_RUN -eq 0 ]] && ! is_supported_python "$PYTHON"; then
  echo "A Python 3.10–3.13 environment is required." >&2
  echo "Pass --python PATH or use --create-venv." >&2
  exit 1
fi
if [[ $DRY_RUN -eq 0 && $WITH_KOKORO -eq 1 ]] && ! has_kokoro "$PYTHON"; then
  echo "The optional Kokoro backend requires kokoro-onnx 0.5.0 and soundfile." >&2
  echo "Use --create-venv --with-kokoro, or pass a compatible --python PATH." >&2
  exit 1
fi

echo "Python: $PYTHON"
echo "App: $PREFIX"
echo "Launcher: $BIN_DIR/codex-speak-last"
echo "Uninstaller: $PREFIX/scripts/uninstall-local.sh"

UTILITY_PYTHON=
utility_candidates=("$PYTHON")
for name in python3.13 python3.12 python3.11 python3.10 python3 /usr/bin/python3; do
  if candidate=$(command -v "$name" 2>/dev/null); then
    utility_candidates+=("$candidate")
  fi
done
for candidate in "${utility_candidates[@]}"; do
  if is_supported_python "$candidate"; then
    UTILITY_PYTHON=$candidate
    break
  fi
done
if [[ -z "$UTILITY_PYTHON" ]]; then
  echo "Python 3.10–3.13 is required to validate install ownership safely." >&2
  exit 1
fi

RULE_DIR="$HOME/.config/karabiner/assets/complex_modifications"
RULE="$RULE_DIR/codex-gamepad.json"
ENDPOINT="$RUNTIME_DIR/user-command.sock"
PLIST="$HOME/Library/LaunchAgents/com.codex-gamepad.receiver.plist"
LOG="$HOME/Library/Logs/codex-gamepad-receiver.log"
INSTALL_LAUNCH_AGENT=0

if [[ $SKIP_KARABINER -eq 0 ]]; then
  echo "Karabiner rule: $RULE"
  if [[ -f "$KARABINER_CONFIG" && -x "$KARABINER_CLI" ]]; then
    MODE_SWITCHING=1
    echo "Karabiner profiles: $CODEX_PROFILE_NAME / $GAME_PROFILE_NAME"
  else
    echo "Automatic game handoff skipped: Karabiner must be opened once and its CLI must be available." >&2
  fi
fi
if [[ -n "$PROFILE_SOURCE" ]]; then
  if [[ ! -f "$PROFILE_SOURCE" || -L "$PROFILE_SOURCE" ]]; then
    echo "--profile must name a regular non-symlink JSON file." >&2
    exit 2
  fi
else
  PROFILE_SOURCE="$ROOT/karabiner/codex-gamepad.json"
fi
if [[ $MODE_SWITCHING -eq 0 && ( -e "$PROFILE_STATE" || -L "$PROFILE_STATE" ) ]]; then
  echo "Existing Codex Gamepad profile ownership requires a normal Karabiner-enabled reinstall or uninstall." >&2
  exit 1
fi

if [[ $SKIP_RECEIVER -eq 0 && -d /Applications/Karabiner-Elements.app ]]; then
  INSTALL_LAUNCH_AGENT=1
  echo "LaunchAgent: $PLIST"
fi

INSTALL_TEMP=$(mktemp -d "${TMPDIR:-/tmp}/codex-gamepad-install.XXXXXX")
OWNERSHIP_LEGACY_PREFIX="$INSTALL_TEMP/no-preexisting-marker"
if ((LEGACY_MARKER_PREEXISTED == 1)); then
  OWNERSHIP_LEGACY_PREFIX="$PREFIX"
fi

"$UTILITY_PYTHON" "$ROOT/scripts/render_template.py" \
  "$ROOT/scripts/codex-speak-last.in" \
  "$INSTALL_TEMP/codex-speak-last" \
  --mode shell \
  "APP_PATH=$PREFIX" \
  "PYTHON_PATH=$PYTHON"

OWNERSHIP_ARTIFACTS=(
  --regular launcher "$BIN_DIR/codex-speak-last" "$INSTALL_TEMP/codex-speak-last" 755
  --symlink uninstaller "$BIN_DIR/codex-gamepad-uninstall" "$PREFIX/scripts/uninstall-local.sh"
)

if [[ $SKIP_KARABINER -eq 0 ]]; then
  "$UTILITY_PYTHON" "$ROOT/scripts/render_profile.py" \
    "$PROFILE_SOURCE" \
    "$INSTALL_TEMP/codex-gamepad.json" \
    --endpoint "$ENDPOINT" \
    --speaker "$BIN_DIR/codex-speak-last"
  OWNERSHIP_ARTIFACTS+=(
    --regular karabiner_rule "$RULE" "$INSTALL_TEMP/codex-gamepad.json" 644
  )
  if [[ $MODE_SWITCHING -eq 1 ]]; then
    PROFILE_CHECK_ARGS=(
      --check
      --config "$KARABINER_CONFIG" \
      --state "$PROFILE_STATE" \
      --rules-file "$INSTALL_TEMP/codex-gamepad.json"
    )
    if [[ $ENABLE_MANAGED_RULES -eq 1 ]]; then
      PROFILE_CHECK_ARGS+=(--enable-managed-rules)
    fi
    "$UTILITY_PYTHON" "$ROOT/scripts/configure_gamepad_profiles.py" "${PROFILE_CHECK_ARGS[@]}"
  fi
fi

if [[ $INSTALL_LAUNCH_AGENT -eq 1 ]]; then
  "$UTILITY_PYTHON" "$ROOT/scripts/render_template.py" \
    "$ROOT/launchd/com.codex-gamepad.receiver.plist.in" \
    "$INSTALL_TEMP/com.codex-gamepad.receiver.plist" \
    --mode xml \
    "RECEIVER_PATH=$PREFIX/bin/codex-gamepad-receiver" \
    "LOG_PATH=$LOG" \
    "ENDPOINT_PATH=$ENDPOINT" \
    "MODE_SWITCHING=$MODE_SWITCHING" \
    "KARABINER_CLI=$KARABINER_CLI" \
    "CODEX_PROFILE=$CODEX_PROFILE_NAME" \
    "GAME_PROFILE=$GAME_PROFILE_NAME" \
    "ARCADE_CHROME_MARKER=$ARCADE_CHROME_MARKER" \
    "LIVING_FOREST_MARKER=$LIVING_FOREST_MARKER" \
    "SPEAKER_PATH=$BIN_DIR/codex-speak-last"
  OWNERSHIP_ARTIFACTS+=(
    --regular launch_agent "$PLIST" "$INSTALL_TEMP/com.codex-gamepad.receiver.plist" 644
  )
fi

"$UTILITY_PYTHON" "$OWNERSHIP_HELPER" check-install \
  --prefix "$OWNERSHIP_LEGACY_PREFIX" \
  --manifest "$OWNERSHIP_MANIFEST" \
  --home "$HOME" \
  --profiles-expected "$MODE_SWITCHING" \
  "${OWNERSHIP_ARTIFACTS[@]}"

if [[ $SKIP_RECEIVER -eq 0 ]]; then
  if [[ -n "$RECEIVER_BINARY" ]]; then
    if [[ ! -f "$RECEIVER_BINARY" || ! -x "$RECEIVER_BINARY" ]]; then
      echo "--receiver-binary must name an executable file." >&2
      exit 2
    fi
  else
    if ! command -v swift >/dev/null 2>&1; then
      echo "Swift/Xcode Command Line Tools are required unless --receiver-binary or --skip-receiver is used." >&2
      exit 1
    fi
    RECEIVER_BINARY="$ROOT/receiver/.build/release/codex-gamepad-receiver"
    if [[ $DRY_RUN -eq 0 ]]; then
      swift build -c release --package-path "$ROOT/receiver"
    fi
  fi
fi

if [[ $DRY_RUN -eq 0 ]]; then
  mkdir -p "$PREFIX/src" "$PREFIX/bin" "$PREFIX/scripts"
  install -m 600 "$ROOT/scripts/install-marker" "$MARKER"
  VENV_CREATED_THIS_INVOCATION=0
  rm -rf "$PREFIX/src/codex_gamepad"
  cp -R "$ROOT/src/codex_gamepad" "$PREFIX/src/codex_gamepad"
  find "$PREFIX/src/codex_gamepad" -type d -name __pycache__ -prune -exec rm -rf {} +
  find "$PREFIX/src/codex_gamepad" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
  install -m 600 "$ROOT/scripts/install-marker" "$PREFIX/.codex-gamepad-install"
  install -m 755 "$ROOT/scripts/uninstall-local.sh" "$PREFIX/scripts/uninstall-local.sh"
  install -m 755 \
    "$ROOT/scripts/configure_gamepad_profiles.py" \
    "$PREFIX/scripts/configure_gamepad_profiles.py"
  install -m 755 \
    "$ROOT/scripts/manage_install_ownership.py" \
    "$PREFIX/scripts/manage_install_ownership.py"
  install -m 644 "$ROOT/LICENSE" "$PREFIX/LICENSE"
  install -m 644 "$ROOT/THIRD_PARTY_NOTICES.md" "$PREFIX/THIRD_PARTY_NOTICES.md"
fi

if [[ $SKIP_RECEIVER -eq 0 ]]; then
  echo "Receiver: $PREFIX/bin/codex-gamepad-receiver"
  if [[ $DRY_RUN -eq 0 ]]; then
    install -m 755 \
      "$RECEIVER_BINARY" \
      "$PREFIX/bin/codex-gamepad-receiver"
  fi
fi

if [[ $DRY_RUN -eq 0 && ( $SKIP_KARABINER -eq 0 || $INSTALL_LAUNCH_AGENT -eq 1 ) ]]; then
  if [[ -L "$RUNTIME_DIR" || ( -e "$RUNTIME_DIR" && ! -d "$RUNTIME_DIR" ) ]]; then
    echo "Unsafe Codex Gamepad runtime directory: $RUNTIME_DIR" >&2
    exit 1
  fi
  mkdir -p "$RUNTIME_DIR"
  chmod 700 "$RUNTIME_DIR"
  if [[ $SKIP_KARABINER -eq 0 && $MODE_SWITCHING -eq 1 ]]; then
    PROFILE_CONFIGURE_ARGS=(
      --config "$KARABINER_CONFIG" \
      --state "$PROFILE_STATE" \
      --rules-file "$INSTALL_TEMP/codex-gamepad.json"
    )
    if [[ $ENABLE_MANAGED_RULES -eq 1 ]]; then
      PROFILE_CONFIGURE_ARGS+=(--enable-managed-rules)
    fi
    "$PYTHON" "$ROOT/scripts/configure_gamepad_profiles.py" "${PROFILE_CONFIGURE_ARGS[@]}"
  fi
fi

if [[ $DRY_RUN -eq 0 ]]; then
  "$UTILITY_PYTHON" "$OWNERSHIP_HELPER" install \
    --prefix "$OWNERSHIP_LEGACY_PREFIX" \
    --manifest "$OWNERSHIP_MANIFEST" \
    --home "$HOME" \
    --profiles-expected "$MODE_SWITCHING" \
    "${OWNERSHIP_ARTIFACTS[@]}"

  if [[ $MODE_SWITCHING -eq 1 ]]; then
    "$KARABINER_CLI" --select-profile "$CODEX_PROFILE_NAME"
  fi

  if [[ $INSTALL_LAUNCH_AGENT -eq 1 ]]; then
    launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
  elif [[ $SKIP_RECEIVER -eq 0 ]]; then
    echo "Karabiner is not installed; receiver activation was skipped."
  fi
fi

if [[ $DRY_RUN -eq 0 ]]; then
  if ! "$BIN_DIR/codex-speak-last" --dry-run; then
    echo "Install succeeded, but no completed Codex Desktop response was available for postflight." >&2
  fi
fi

if [[ $DRY_RUN -eq 1 ]]; then
  echo "Dry run complete. No installation files or settings were changed."
else
  if [[ $ENABLE_MANAGED_RULES -eq 1 ]]; then
    echo "Install complete. Controller rules are enabled in the Codex Controller profile."
  else
    echo "Install complete. Enable the navigation and speak/stop receiver rules in Karabiner."
  fi
fi
