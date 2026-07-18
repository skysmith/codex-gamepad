#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=${CODEX_GAMEPAD_VERSION:-0.1.0}
BUILD_NUMBER=${CODEX_GAMEPAD_BUILD_NUMBER:-1}
OUTPUT_DIR=${CODEX_GAMEPAD_OUTPUT_DIR:-"$ROOT/dist"}
SIGN_IDENTITY=${CODEX_GAMEPAD_SIGN_IDENTITY:--}
NOTARY_PROFILE=${CODEX_GAMEPAD_NOTARY_PROFILE:-}
UV_BIN=${CODEX_GAMEPAD_UV:-$(command -v uv 2>/dev/null || true)}
NOTARIZE=0
RUN_TESTS=1

usage() {
  echo "Usage: $0 [--version VERSION] [--build-number NUMBER] [--output DIR] [--uv PATH] [--identity NAME] [--notary-profile NAME] [--notarize] [--skip-tests]"
}

while (($#)); do
  case "$1" in
    --version)
      shift
      VERSION=${1:?--version requires a value}
      ;;
    --build-number)
      shift
      BUILD_NUMBER=${1:?--build-number requires a value}
      ;;
    --output)
      shift
      OUTPUT_DIR=${1:?--output requires a path}
      ;;
    --uv)
      shift
      UV_BIN=${1:?--uv requires a path}
      ;;
    --identity)
      shift
      SIGN_IDENTITY=${1:?--identity requires a value}
      ;;
    --notary-profile)
      shift
      NOTARY_PROFILE=${1:?--notary-profile requires a value}
      ;;
    --notarize)
      NOTARIZE=1
      ;;
    --skip-tests)
      RUN_TESTS=0
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

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The setup app must be built on macOS." >&2
  exit 1
fi
if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "An arm64 uv binary is required; pass --uv PATH." >&2
  exit 1
fi
if ! file "$UV_BIN" | grep -Eq 'arm64|universal'; then
  echo "The bundled uv binary must support Apple Silicon: $UV_BIN" >&2
  exit 1
fi
if [[ $NOTARIZE -eq 1 && ( "$SIGN_IDENTITY" == "-" || -z "$NOTARY_PROFILE" ) ]]; then
  echo "--notarize requires a Developer ID --identity and --notary-profile." >&2
  exit 2
fi

if [[ $RUN_TESTS -eq 1 ]]; then
  PYTHONPATH="$ROOT/src" python3 -m unittest discover -s "$ROOT/tests" -v
  swift test --package-path "$ROOT/control-panel"
fi

swift build -c release --arch arm64 --package-path "$ROOT/receiver"
swift build -c release --arch arm64 --package-path "$ROOT/control-panel"

BUILD_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/codex-gamepad-release.XXXXXX")
cleanup() {
  rm -rf "$BUILD_ROOT"
}
trap cleanup EXIT

APP_NAME="Codex Gamepad Setup.app"
APP="$BUILD_ROOT/$APP_NAME"
CONTENTS="$APP/Contents"
PAYLOAD="$CONTENTS/Resources/Payload"
mkdir -p "$CONTENTS/MacOS" "$PAYLOAD/bin" "$PAYLOAD/scripts"

install -m 755 \
  "$ROOT/control-panel/.build/arm64-apple-macosx/release/CodexGamepadSetup" \
  "$CONTENTS/MacOS/CodexGamepadSetup"
install -m 644 "$ROOT/control-panel/Info.plist" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD_NUMBER" "$CONTENTS/Info.plist"

cp -R "$ROOT/src" "$PAYLOAD/src"
cp -R "$ROOT/karabiner" "$PAYLOAD/karabiner"
cp -R "$ROOT/launchd" "$PAYLOAD/launchd"
install -m 755 "$ROOT/scripts/install-local.sh" "$PAYLOAD/scripts/install-local.sh"
install -m 755 "$ROOT/scripts/uninstall-local.sh" "$PAYLOAD/scripts/uninstall-local.sh"
install -m 755 "$ROOT/scripts/configure_gamepad_profiles.py" "$PAYLOAD/scripts/configure_gamepad_profiles.py"
install -m 755 "$ROOT/scripts/manage_install_ownership.py" "$PAYLOAD/scripts/manage_install_ownership.py"
install -m 755 "$ROOT/scripts/render_profile.py" "$PAYLOAD/scripts/render_profile.py"
install -m 755 "$ROOT/scripts/render_template.py" "$PAYLOAD/scripts/render_template.py"
install -m 755 "$ROOT/scripts/download-models.sh" "$PAYLOAD/scripts/download-models.sh"
install -m 755 "$ROOT/scripts/preflight.sh" "$PAYLOAD/scripts/preflight.sh"
install -m 755 "$ROOT/scripts/sanitize-karabiner-devices.py" "$PAYLOAD/scripts/sanitize-karabiner-devices.py"
install -m 644 "$ROOT/scripts/codex-speak-last.in" "$PAYLOAD/scripts/codex-speak-last.in"
install -m 600 "$ROOT/scripts/install-marker" "$PAYLOAD/scripts/install-marker"
install -m 755 \
  "$ROOT/receiver/.build/arm64-apple-macosx/release/codex-gamepad-receiver" \
  "$PAYLOAD/bin/codex-gamepad-receiver"
install -m 755 "$UV_BIN" "$PAYLOAD/bin/uv"
install -m 644 "$ROOT/LICENSE" "$PAYLOAD/LICENSE"
install -m 644 "$ROOT/THIRD_PARTY_NOTICES.md" "$PAYLOAD/THIRD_PARTY_NOTICES.md"
find "$PAYLOAD" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$PAYLOAD" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

SIGN_ARGS=(--force --sign "$SIGN_IDENTITY")
if [[ "$SIGN_IDENTITY" != "-" ]]; then
  SIGN_ARGS+=(--options runtime --timestamp)
fi
codesign "${SIGN_ARGS[@]}" "$PAYLOAD/bin/uv"
codesign "${SIGN_ARGS[@]}" "$PAYLOAD/bin/codex-gamepad-receiver"
codesign "${SIGN_ARGS[@]}" "$CONTENTS/MacOS/CodexGamepadSetup"
codesign "${SIGN_ARGS[@]}" \
  --entitlements "$ROOT/control-panel/CodexGamepadSetup.entitlements" \
  "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

mkdir -p "$OUTPUT_DIR"
ARTIFACT_STEM="Codex-Gamepad-Setup-$VERSION-arm64"
if [[ "$SIGN_IDENTITY" == "-" ]]; then
  ARTIFACT_STEM="$ARTIFACT_STEM-UNNOTARIZED-BETA"
fi

if [[ $NOTARIZE -eq 1 ]]; then
  ZIP="$BUILD_ROOT/$ARTIFACT_STEM.zip"
  ditto -c -k --keepParent "$APP" "$ZIP"
  xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP"
  xcrun stapler validate "$APP"
fi

DMG_ROOT="$BUILD_ROOT/dmg"
mkdir -p "$DMG_ROOT"
cp -R "$APP" "$DMG_ROOT/$APP_NAME"
ln -s /Applications "$DMG_ROOT/Applications"
if [[ "$SIGN_IDENTITY" == "-" ]]; then
  install -m 644 \
    "$ROOT/docs/UNNOTARIZED_BETA_INSTALL.txt" \
    "$DMG_ROOT/READ ME FIRST - UNNOTARIZED BETA.txt"
fi
DMG="$OUTPUT_DIR/$ARTIFACT_STEM.dmg"
rm -f "$DMG" "$DMG.sha256"
hdiutil create -quiet -volname "Codex Gamepad Setup" -srcfolder "$DMG_ROOT" -format UDZO "$DMG"
if [[ "$SIGN_IDENTITY" != "-" ]]; then
  codesign --force --sign "$SIGN_IDENTITY" --timestamp "$DMG"
fi

if [[ $NOTARIZE -eq 1 ]]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
  spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"
fi

APP_OUTPUT="$OUTPUT_DIR/$APP_NAME"
rm -rf "$APP_OUTPUT"
cp -R "$APP" "$APP_OUTPUT"
(
  cd "$OUTPUT_DIR"
  shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256"
)

if [[ "$SIGN_IDENTITY" == "-" ]]; then
  BETA_BUNDLE="$BUILD_ROOT/$ARTIFACT_STEM"
  mkdir -p "$BETA_BUNDLE"
  cp "$DMG" "$DMG.sha256" "$BETA_BUNDLE/"
  install -m 644 \
    "$ROOT/docs/UNNOTARIZED_BETA_INSTALL.txt" \
    "$BETA_BUNDLE/READ ME FIRST - UNNOTARIZED BETA.txt"
  BETA_ZIP="$OUTPUT_DIR/$ARTIFACT_STEM.zip"
  rm -f "$BETA_ZIP" "$BETA_ZIP.sha256"
  (
    cd "$BUILD_ROOT"
    /usr/bin/zip -q -r -X "$BETA_ZIP" "$(basename "$BETA_BUNDLE")"
  )
  (
    cd "$OUTPUT_DIR"
    shasum -a 256 "$(basename "$BETA_ZIP")" > "$(basename "$BETA_ZIP").sha256"
  )
fi

echo "Built: $APP_OUTPUT"
echo "Built: $DMG"
if [[ $NOTARIZE -eq 1 ]]; then
  echo "Notarization: accepted and stapled"
else
  echo "Notarization: not performed"
  if [[ "$SIGN_IDENTITY" == "-" ]]; then
    echo "Built: $BETA_ZIP"
  fi
fi
