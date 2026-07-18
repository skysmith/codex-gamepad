#!/bin/bash

# Read-only readiness check for the first Codex Gamepad hardware pass.
# This script intentionally suppresses all codex-speak-last output: even a
# future launcher regression must not put response text in preflight output.

set -uo pipefail

FAILURES=0
WARNINGS=0

pass() {
  printf 'PASS  %s\n' "$1"
}

warn() {
  WARNINGS=$((WARNINGS + 1))
  printf 'WARN  %s\n' "$1"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf 'FAIL  %s\n' "$1"
}

info() {
  printf '      %s\n' "$1"
}

version_at_least_16() {
  local version=$1
  if [[ "$version" =~ ^([0-9]+)(\.[0-9]+)*$ ]]; then
    ((BASH_REMATCH[1] >= 16))
    return
  fi
  return 1
}

find_python() {
  local name candidate
  if [[ -n "${CODEX_GAMEPAD_PREFLIGHT_PYTHON:-}" ]]; then
    printf '%s\n' "$CODEX_GAMEPAD_PREFLIGHT_PYTHON"
    return
  fi
  for name in python3.13 python3.12 python3.11 python3.10 python3; do
    if candidate=$(command -v "$name" 2>/dev/null); then
      printf '%s\n' "$candidate"
      return
    fi
  done
  return 1
}

plist_value() {
  local plist=$1
  local key_path=$2
  "$PYTHON_BIN" - "$plist" "$key_path" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "rb") as handle:
    value = plistlib.load(handle)
for part in sys.argv[2].split("."):
    value = value[int(part)] if isinstance(value, list) else value[part]
if not isinstance(value, (str, int, float)):
    raise TypeError("plist value is not scalar")
print(value)
PY
}

printf 'Codex Gamepad preflight (read-only)\n\n'

PYTHON_BIN=$(find_python 2>/dev/null || true)
if [[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]]; then
  pass "Python is available for safe plist/JSON inspection."
else
  fail "Python 3 is unavailable; Codex Gamepad requires it for safe local inspection."
  PYTHON_BIN=
fi

KARABINER_APP=${CODEX_GAMEPAD_KARABINER_APP:-/Applications/Karabiner-Elements.app}
KARABINER_CLI=${CODEX_GAMEPAD_KARABINER_CLI:-/Library/Application Support/org.pqrs/Karabiner-Elements/bin/karabiner_cli}
KARABINER_RULE=${CODEX_GAMEPAD_KARABINER_RULE:-"$HOME/.config/karabiner/assets/complex_modifications/codex-gamepad.json"}
KARABINER_CONFIG=${CODEX_GAMEPAD_KARABINER_CONFIG:-"$HOME/.config/karabiner/karabiner.json"}
PROFILE_STATE="$HOME/Library/Application Support/Codex Gamepad/karabiner-profile-state.json"
LAUNCH_AGENT=${CODEX_GAMEPAD_LAUNCH_AGENT:-"$HOME/Library/LaunchAgents/com.codex-gamepad.receiver.plist"}
DEFAULT_ENDPOINT=${CODEX_GAMEPAD_ENDPOINT:-"$HOME/Library/Application Support/Codex Gamepad/user-command.sock"}
LAUNCHER=${CODEX_GAMEPAD_LAUNCHER:-"${CODEX_GAMEPAD_BIN_DIR:-$HOME/.local/bin}/codex-speak-last"}
LAUNCHCTL=${CODEX_GAMEPAD_LAUNCHCTL:-/bin/launchctl}
SCRIPT_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEVICE_SANITIZER=${CODEX_GAMEPAD_DEVICE_SANITIZER:-"$SCRIPT_DIRECTORY/sanitize-karabiner-devices.py"}
CODEX_PROFILE_NAME="Codex Controller"
GAME_PROFILE_NAME="Game Mode"

KARABINER_VERSION=
if [[ ! -d "$KARABINER_APP" ]]; then
  fail "Karabiner-Elements is not installed. Version 16 or newer is required."
elif [[ -z "$PYTHON_BIN" ]]; then
  fail "Karabiner-Elements is present, but its version could not be checked."
else
  KARABINER_VERSION=$(plist_value "$KARABINER_APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || true)
  if version_at_least_16 "$KARABINER_VERSION"; then
    pass "Karabiner-Elements $KARABINER_VERSION is installed (minimum: 16)."
  elif [[ -n "$KARABINER_VERSION" ]]; then
    fail "Karabiner-Elements $KARABINER_VERSION is too old; version 16 or newer is required."
  else
    fail "Karabiner-Elements is present, but its version could not be read."
  fi
fi

CLI_READY=0
if [[ ! -x "$KARABINER_CLI" ]]; then
  fail "Karabiner's command-line tool is missing or not executable."
elif "$KARABINER_CLI" --version-number >/dev/null 2>&1; then
  CLI_READY=1
  pass "Karabiner's command-line tool is available."
else
  fail "Karabiner's command-line tool did not run successfully."
fi

RULE_READY=0
if [[ ! -f "$KARABINER_RULE" ]]; then
  fail "The installed Codex Gamepad complex-modification rule is missing."
elif [[ ! -r "$KARABINER_RULE" ]]; then
  fail "The installed Codex Gamepad rule is not readable."
elif ((CLI_READY)) && "$KARABINER_CLI" --lint-complex-modifications "$KARABINER_RULE" >/dev/null 2>&1; then
  RULE_READY=1
  pass "The installed Codex Gamepad rule passes Karabiner's linter."
elif ((CLI_READY)); then
  fail "The installed Codex Gamepad rule failed Karabiner's linter."
elif [[ -n "$PYTHON_BIN" ]] && "$PYTHON_BIN" -m json.tool "$KARABINER_RULE" >/dev/null 2>&1; then
  RULE_READY=1
  warn "The installed rule is valid JSON, but Karabiner linting was unavailable."
else
  fail "The installed Codex Gamepad rule could not be validated."
fi

NAVIGATION_DESCRIPTION='Codex Gamepad — navigation (8BitDo Ultimate 2C)'
RECEIVER_DESCRIPTION='Codex Gamepad — speak/stop (Karabiner 16 receiver)'
LEGACY_DESCRIPTION='Codex Gamepad — speak/stop (legacy shell fallback; do not enable with receiver rule)'

if [[ ! -e "$KARABINER_CONFIG" ]]; then
  warn "Karabiner's user configuration is not present yet; open the app once, then enable both Codex Gamepad rules."
elif [[ ! -r "$KARABINER_CONFIG" ]]; then
  warn "Karabiner's user configuration could not be read (permissions may still be pending)."
elif [[ -z "$PYTHON_BIN" ]]; then
  warn "Enabled Codex Gamepad rules could not be inspected without Python."
else
  ENABLED_PROBE=$("$PYTHON_BIN" - "$KARABINER_CONFIG" "$NAVIGATION_DESCRIPTION" "$RECEIVER_DESCRIPTION" "$LEGACY_DESCRIPTION" "$CODEX_PROFILE_NAME" <<'PY' 2>/dev/null || true
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
profiles = config.get("profiles")
if not isinstance(profiles, list):
    raise TypeError("profiles is not a list")
codex_profile = next(
    (
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile.get("name") == sys.argv[5]
    ),
    None,
)
if codex_profile is None:
    print("profile_missing")
    raise SystemExit(0)
complex_modifications = codex_profile.get("complex_modifications", {})
rules = complex_modifications.get("rules", []) if isinstance(complex_modifications, dict) else []
descriptions = {
    rule.get("description") for rule in rules if isinstance(rule, dict)
}
print(
    int(sys.argv[2] in descriptions),
    int(sys.argv[3] in descriptions),
    int(sys.argv[4] in descriptions),
)
PY
  )
  if [[ "$ENABLED_PROBE" == "profile_missing" ]]; then
    fail "The Codex Controller Karabiner profile is missing; reinstall the automatic game handoff profiles."
  elif [[ "$ENABLED_PROBE" =~ ^([01])[[:space:]]+([01])[[:space:]]+([01])$ ]]; then
    NAVIGATION_ENABLED=${BASH_REMATCH[1]}
    RECEIVER_ENABLED=${BASH_REMATCH[2]}
    LEGACY_ENABLED=${BASH_REMATCH[3]}
    if ((NAVIGATION_ENABLED)); then
      pass "The navigation rule is enabled in the Codex controller profile."
    else
      fail "The navigation rule is not enabled in the Codex controller profile."
    fi
    if ((RECEIVER_ENABLED)); then
      pass "The Karabiner 16 speech receiver rule is enabled in the Codex controller profile."
    else
      fail "The Karabiner 16 speech receiver rule is not enabled in the Codex controller profile."
    fi
    if ((LEGACY_ENABLED)); then
      fail "The legacy shell rule is also enabled; disable it to avoid duplicate speech triggers."
    else
      pass "The conflicting legacy shell rule is disabled."
    fi
  else
    fail "Karabiner's configuration is invalid and enabled rules could not be inspected."
  fi
fi

ENDPOINT=$DEFAULT_ENDPOINT
RECEIVER_PATH=
MODE_SWITCHING=
INSTALLED_CODEX_PROFILE=
INSTALLED_GAME_PROFILE=
INSTALLED_KARABINER_CLI=
if [[ ! -f "$LAUNCH_AGENT" ]]; then
  fail "The Codex Gamepad receiver LaunchAgent is not installed."
elif [[ ! -r "$LAUNCH_AGENT" ]]; then
  warn "The receiver LaunchAgent exists but could not be read (permissions may still be pending)."
elif [[ -z "$PYTHON_BIN" ]]; then
  warn "The receiver LaunchAgent could not be inspected without Python."
else
  RECEIVER_PATH=$(plist_value "$LAUNCH_AGENT" ProgramArguments.0 2>/dev/null || true)
  DISCOVERED_ENDPOINT=$(plist_value "$LAUNCH_AGENT" EnvironmentVariables.CODEX_GAMEPAD_ENDPOINT 2>/dev/null || true)
  MODE_SWITCHING=$(plist_value "$LAUNCH_AGENT" EnvironmentVariables.CODEX_GAMEPAD_MODE_SWITCHING 2>/dev/null || true)
  INSTALLED_CODEX_PROFILE=$(plist_value "$LAUNCH_AGENT" EnvironmentVariables.CODEX_GAMEPAD_CODEX_PROFILE 2>/dev/null || true)
  INSTALLED_GAME_PROFILE=$(plist_value "$LAUNCH_AGENT" EnvironmentVariables.CODEX_GAMEPAD_GAME_PROFILE 2>/dev/null || true)
  INSTALLED_KARABINER_CLI=$(plist_value "$LAUNCH_AGENT" EnvironmentVariables.CODEX_GAMEPAD_KARABINER_CLI 2>/dev/null || true)
  if [[ "$DISCOVERED_ENDPOINT" == /* ]]; then
    ENDPOINT=$DISCOVERED_ENDPOINT
  fi
  if [[ "$RECEIVER_PATH" == /* && -x "$RECEIVER_PATH" ]]; then
    pass "The receiver LaunchAgent points to an executable receiver."
    if "$RECEIVER_PATH" --self-test >/dev/null 2>&1; then
      pass "The installed receiver passes its command and game-classifier self-test."
    else
      fail "The installed receiver failed its command or game-classifier self-test."
    fi
  else
    fail "The receiver LaunchAgent does not point to an executable receiver."
  fi
  if [[ "$MODE_SWITCHING" == "1" && "$INSTALLED_CODEX_PROFILE" == "$CODEX_PROFILE_NAME" && "$INSTALLED_GAME_PROFILE" == "$GAME_PROFILE_NAME" && "$INSTALLED_KARABINER_CLI" == "$KARABINER_CLI" ]]; then
    pass "The receiver is configured for automatic foreground game handoff."
  else
    fail "Automatic foreground game handoff is not enabled in the installed receiver."
  fi
fi

if [[ "$MODE_SWITCHING" == "1" && -r "$KARABINER_CONFIG" && -n "$PYTHON_BIN" ]]; then
  PROFILE_PAIR_PROBE=$("$PYTHON_BIN" - "$KARABINER_CONFIG" "$CODEX_PROFILE_NAME" "$GAME_PROFILE_NAME" <<'PY' 2>/dev/null || true
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
profiles = config.get("profiles")
if not isinstance(profiles, list):
    raise TypeError("profiles is not a list")

def named(name):
    matches = [
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile.get("name") == name
    ]
    return matches[0] if len(matches) == 1 else None

codex = named(sys.argv[2])
game = named(sys.argv[3])
if codex is None or game is None:
    print("missing")
    raise SystemExit(0)

target = {"is_game_pad": True, "product_id": 12315, "vendor_id": 11720}
discard_keys = (
    "mouse_discard_x",
    "mouse_discard_y",
    "mouse_discard_vertical_wheel",
    "mouse_discard_horizontal_wheel",
)

def target_entries(profile):
    devices = profile.get("devices", [])
    if not isinstance(devices, list):
        raise TypeError("profile devices is not a list")
    return [
        device
        for device in devices
        if isinstance(device, dict) and device.get("identifiers") == target
    ]

codex_entries = target_entries(codex)
game_entries = target_entries(game)
codex_safe = (
    len(codex_entries) == 1
    and codex_entries[0].get("ignore") is False
    and all(codex_entries[0].get(key) is True for key in discard_keys)
)
# Karabiner canonicalizes ignore:true by omitting the key, so anything other
# than the explicit capture value false is a released device.
game_safe = (
    len(game_entries) == 1
    and game_entries[0].get("ignore") is not False
    and all(game_entries[0].get(key) is True for key in discard_keys)
)
print("safe" if codex_safe and game_safe else "unsafe")
PY
  )
  case "$PROFILE_PAIR_PROBE" in
    safe)
      pass "The paired profiles capture and release the verified 8BitDo safely."
      ;;
    missing)
      fail "The automatic handoff requires exactly one Codex Controller profile and one Game Mode profile."
      ;;
    *)
      fail "The paired profiles do not safely capture and release the verified 8BitDo."
      ;;
  esac
fi

if [[ "$MODE_SWITCHING" == "1" && -n "$PYTHON_BIN" ]]; then
  PROFILE_STATE_PROBE=$("$PYTHON_BIN" - "$PROFILE_STATE" "$CODEX_PROFILE_NAME" "$GAME_PROFILE_NAME" <<'PY' 2>/dev/null || true
import json
import os
import stat
import sys

path = sys.argv[1]
metadata = os.lstat(path)
if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
    print("unsafe")
    raise SystemExit(0)
if stat.S_IMODE(metadata.st_mode) != 0o600:
    print("unsafe")
    raise SystemExit(0)
with open(path, encoding="utf-8") as handle:
    state = json.load(handle)
expected = [sys.argv[2], sys.argv[3]]
restore = state.get("restore_profile")
safe = (
    state.get("version") == 1
    and state.get("managed_profiles") == expected
    and (restore is None or isinstance(restore, str))
    and restore not in expected
)
print("safe" if safe else "unsafe")
PY
  )
  if [[ "$PROFILE_STATE_PROBE" == "safe" ]]; then
    pass "Profile ownership state is private and supports reversible uninstall."
  else
    fail "Profile ownership state is missing or unsafe; reinstall before using automatic handoff."
  fi
fi

if [[ -x "$LAUNCHCTL" ]]; then
  if "$LAUNCHCTL" print "gui/$(id -u)/com.codex-gamepad.receiver" >/dev/null 2>&1; then
    pass "The receiver LaunchAgent is loaded."
  else
    warn "The receiver LaunchAgent's loaded state could not be confirmed; login-session permissions may still be pending."
  fi
else
  warn "launchctl was unavailable, so the receiver's loaded state could not be checked."
fi

if [[ -S "$ENDPOINT" ]]; then
  pass "The dedicated Karabiner user-command socket is listening."
elif [[ -d "${ENDPOINT%/*}" && ! -x "${ENDPOINT%/*}" ]]; then
  warn "The receiver socket directory could not be inspected due to permissions."
else
  fail "The dedicated Karabiner user-command socket is not available."
fi

CODEX_APP=
if [[ -n "${CODEX_GAMEPAD_CODEX_APP:-}" ]]; then
  CODEX_CANDIDATES=("$CODEX_GAMEPAD_CODEX_APP")
else
  CODEX_CANDIDATES=(
    "/Applications/ChatGPT.app"
    "/Applications/Codex.app"
    "$HOME/Applications/ChatGPT.app"
    "$HOME/Applications/Codex.app"
  )
fi
if [[ -n "$PYTHON_BIN" ]]; then
  for candidate in "${CODEX_CANDIDATES[@]}"; do
    [[ -d "$candidate" ]] || continue
    bundle_id=$(plist_value "$candidate/Contents/Info.plist" CFBundleIdentifier 2>/dev/null || true)
    if [[ "$bundle_id" == "com.openai.codex" ]]; then
      CODEX_APP=$candidate
      break
    fi
  done
fi

if [[ -z "$CODEX_APP" ]]; then
  fail "The Codex Desktop bundle (com.openai.codex) was not found."
else
  pass "The Codex Desktop bundle (com.openai.codex) is installed."
  if [[ -x "$CODEX_APP/Contents/Resources/codex" ]]; then
    pass "Codex Desktop includes the app-server executable used by speech."
  else
    fail "Codex Desktop's app-server executable is missing or not executable."
  fi
fi

if [[ ! -x "$LAUNCHER" ]]; then
  fail "The codex-speak-last launcher is missing or not executable."
else
  pass "The codex-speak-last launcher is installed."
  # This path returns before Codex task selection and never initializes the
  # model, synthesizes speech, or launches an audio player.
  if "$LAUNCHER" --check-speech-runtime >/dev/null 2>&1; then
    pass "The configured local speech backend is ready."
  else
    fail "The configured local speech backend is incomplete; repair it in Codex Gamepad Setup."
  fi
  # Do not capture, parse, or repeat this output. The launcher promises a
  # metadata-only dry run, and redirecting both streams also protects against
  # accidental response-text output in a future version.
  if "$LAUNCHER" --dry-run >/dev/null 2>&1; then
    pass "Speech dry-run found a completed response (all output suppressed)."
  else
    warn "Speech dry-run did not complete; open Codex with a completed response and retry."
  fi
fi

if ((CLI_READY)); then
  RAW_DEVICE_OUTPUT=$("$KARABINER_CLI" --list-connected-devices 2>/dev/null)
  DEVICE_STATUS=$?
  DEVICE_SANITIZER_STATUS=0
  DEVICE_OUTPUT=
  if ((DEVICE_STATUS == 0)); then
    if [[ -z "$PYTHON_BIN" || ! -r "$DEVICE_SANITIZER" ]]; then
      DEVICE_SANITIZER_STATUS=1
    elif ! DEVICE_OUTPUT=$(printf '%s\n' "$RAW_DEVICE_OUTPUT" | "$PYTHON_BIN" "$DEVICE_SANITIZER" --controllers-only 2>/dev/null); then
      DEVICE_SANITIZER_STATUS=1
    fi
  fi
  unset RAW_DEVICE_OUTPUT
  if ((DEVICE_STATUS != 0)); then
    warn "Connected devices could not be listed; Karabiner permissions may still be pending."
  elif ((DEVICE_SANITIZER_STATUS != 0)); then
    warn "Connected devices were listed, but their data could not be safely sanitized."
  elif printf '%s\n' "$DEVICE_OUTPUT" | grep -Eiq 'is_game_pad["[:space:]]*[:=][[:space:]]*(true|1)'; then
    pass "Karabiner currently lists at least one connected gamepad."
    GAMEPAD_LINE=$(printf '%s\n' "$DEVICE_OUTPUT" | grep -Ei 'is_game_pad["[:space:]]*[:=][[:space:]]*(true|1)' | head -n 1 | LC_ALL=C tr -cd '\11\40-\176' | cut -c 1-240)
    [[ -n "$GAMEPAD_LINE" ]] && info "$GAMEPAD_LINE"
    if [[ ! -r "$KARABINER_CONFIG" ]]; then
      fail "The connected gamepad's Karabiner enablement could not be verified because the user configuration is not readable."
    elif [[ -z "$PYTHON_BIN" ]]; then
      fail "The connected gamepad's Karabiner enablement could not be inspected without Python."
    else
      GAMEPAD_ENABLEMENT_PROBE=$("$PYTHON_BIN" - "$KARABINER_CONFIG" "$DEVICE_OUTPUT" "$CODEX_PROFILE_NAME" "$GAME_PROFILE_NAME" <<'PY' 2>/dev/null || true
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
connected_devices = json.loads(sys.argv[2])
if not isinstance(connected_devices, list):
    raise TypeError("connected devices is not a list")
profiles = config.get("profiles")
if not isinstance(profiles, list):
    raise TypeError("profiles is not a list")
codex_profile = next(
    (
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile.get("name") == sys.argv[3]
    ),
    None,
)
game_profile = next(
    (
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile.get("name") == sys.argv[4]
    ),
    None,
)
if codex_profile is None:
    print("profile_missing")
    raise SystemExit(0)
if game_profile is None:
    print("game_profile_missing")
    raise SystemExit(0)
gamepads = []
for device in connected_devices:
    if not isinstance(device, dict):
        continue
    if device.get("is_game_pad") is True:
        gamepads.append(
            {
                "is_game_pad": True,
                "product_id": device.get("product_id"),
                "vendor_id": device.get("vendor_id"),
            }
        )
if not gamepads:
    print("missing")
    raise SystemExit(0)
def matches(configured, connected):
    return (
        isinstance(configured, dict)
        and bool(configured)
        and all(connected.get(key) == value for key, value in configured.items())
    )

discard_keys = (
    "mouse_discard_x",
    "mouse_discard_y",
    "mouse_discard_vertical_wheel",
    "mouse_discard_horizontal_wheel",
)

def state(profile):
    configured_devices = profile.get("devices", [])
    if not isinstance(configured_devices, list):
        raise TypeError("profile devices is not a list")
    matching_entries = [
        entry
        for entry in configured_devices
        if isinstance(entry, dict)
        and any(matches(entry.get("identifiers"), gamepad) for gamepad in gamepads)
    ]
    enabled_entries = [entry for entry in matching_entries if entry.get("ignore") is False]
    if enabled_entries and all(
        entry.get(key) is True for entry in enabled_entries for key in discard_keys
    ):
        return "enabled_safe"
    if enabled_entries:
        return "enabled_unsafe"
    if matching_entries:
        return "ignored"
    return "unconfigured"

codex_state = state(codex_profile)
if game_profile is None:
    print(codex_state)
elif codex_state == "enabled_safe" and state(game_profile) == "ignored":
    print("automatic_safe")
elif codex_state == "enabled_safe":
    print("game_unsafe")
else:
    print(codex_state)
PY
      )
      case "$GAMEPAD_ENABLEMENT_PROBE" in
        automatic_safe)
          pass "The Codex Controller profile safely captures the connected gamepad."
          pass "Game Mode releases the connected gamepad to foreground games."
          pass "Gamepad stick pointer and scroll output are disabled in Codex mode."
          ;;
        enabled_safe)
          pass "A connected gamepad is enabled for modification in the selected Karabiner profile."
          pass "Gamepad stick pointer and scroll output are disabled."
          ;;
        game_unsafe)
          fail "Game Mode does not release the connected gamepad; reinstall the paired Karabiner profiles."
          ;;
        enabled_unsafe)
          fail "The connected gamepad can emit stick pointer or scroll output; in Karabiner Devices, enable Discard X, Discard Y, Discard vertical wheel, and Discard horizontal wheel for this gamepad."
          ;;
        ignored)
          fail "The connected gamepad is ignored in the selected Karabiner profile; enable Modify events for this device."
          ;;
        unconfigured)
          fail "The connected gamepad has no matching device entry with ignore:false in the selected Karabiner profile."
          ;;
        profile_missing)
          fail "The connected gamepad's enablement could not be verified because the Codex Controller profile is missing."
          ;;
        game_profile_missing)
          fail "The connected gamepad's release could not be verified because Game Mode is missing."
          ;;
        *)
          fail "The connected gamepad's Karabiner enablement could not be verified from Karabiner's device data."
          ;;
      esac
    fi
  elif printf '%s\n' "$DEVICE_OUTPUT" | grep -Eiq '8bitdo|game[ _-]?pad|controller'; then
    warn "A controller-like device is listed, but Karabiner does not mark it as a gamepad."
    CONTROLLER_LINE=$(printf '%s\n' "$DEVICE_OUTPUT" | grep -Ei '8bitdo|game[ _-]?pad|controller' | head -n 1 | LC_ALL=C tr -cd '\11\40-\176' | cut -c 1-240)
    [[ -n "$CONTROLLER_LINE" ]] && info "$CONTROLLER_LINE"
  else
    warn "No connected gamepad is listed; this is expected until the controller test."
  fi
fi

printf '\nSummary: %d failure(s), %d warning(s).\n' "$FAILURES" "$WARNINGS"
if ((FAILURES)); then
  exit 1
fi
exit 0
