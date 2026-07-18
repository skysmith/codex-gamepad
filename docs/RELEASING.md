# Apple Silicon release runbook

The v0.1 distribution target is a hardened-runtime, Developer ID-signed, notarized, and stapled macOS app inside a notarized and stapled DMG. Both the UI and embedded executables are thin `arm64` binaries. The setup app supports macOS 15 and newer.

## Local unnotarized beta

Before Apple Developer Program enrollment, build a clearly labeled Apple Silicon test bundle with:

```sh
scripts/build-setup-app.sh --version 0.1.0
```

The shareable artifact is `dist/Codex-Gamepad-Setup-0.1.0-arm64-UNNOTARIZED-BETA.zip`. It contains the DMG, the DMG checksum, and the same first-launch guide embedded in the DMG. Publish the ZIP checksum separately so testers can compare it before opening the bundle.

Testers must use macOS's per-app System Settings > Privacy & Security > **Open Anyway** flow. Never tell testers to disable Gatekeeper or strip quarantine attributes. Apple has not scanned this build and macOS cannot verify its developer; share it only with informed testers who trust the source.

## One-time Apple setup

The release operator needs:

1. An active Apple Developer Program team.
2. A **Developer ID Application** certificate with its private key in the signing keychain.
3. App notarization credentials stored by `notarytool`. An app-specific password or App Store Connect API key can be used; the checked-in script consumes a keychain profile.

Store an app-password profile locally:

```sh
xcrun notarytool store-credentials codex-gamepad-notary \
  --apple-id "APPLE_ID" \
  --team-id "TEAM_ID" \
  --password "APP_SPECIFIC_PASSWORD"
```

Do not commit certificates, private keys, Apple IDs, passwords, API keys, or exported keychains.

## Local notarized build

Confirm the identity name:

```sh
security find-identity -v -p codesigning
```

Then build, sign, submit, wait, and staple:

```sh
scripts/build-setup-app.sh \
  --version 0.1.0 \
  --identity "Developer ID Application: NAME (TEAM_ID)" \
  --notary-profile codex-gamepad-notary \
  --notarize
```

The script:

1. Runs the Python and control-panel test suites.
2. Builds the receiver and setup UI for arm64.
3. Assembles the app and embeds the source runtime, prebuilt receiver, and pinned arm64 uv.
4. Signs nested executables and the app with hardened runtime.
5. Submits the app archive, waits for acceptance, and staples the app.
6. Creates and signs the DMG, submits it, waits for acceptance, and staples it.
7. Validates the tickets and Gatekeeper assessment, then writes a SHA-256 file.

Never rename an `UNNOTARIZED-BETA` artifact to remove that marker. A real release must be generated with `--notarize` and complete successfully.

## GitHub Actions secrets

`.github/workflows/release.yml` expects:

- `APPLE_DEVELOPER_ID_CERTIFICATE_BASE64`: exported Developer ID Application `.p12`, base64 encoded
- `APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD`: export password for that `.p12`
- `APPLE_DEVELOPER_ID_NAME`: certificate holder name, without the `Developer ID Application:` prefix or team suffix
- `APPLE_TEAM_ID`: Apple team ID
- `APPLE_NOTARY_APPLE_ID`: notarization Apple ID
- `APPLE_NOTARY_APP_PASSWORD`: app-specific password

A manual dispatch builds and uploads a notarized artifact. Pushing a signed `v*` tag also publishes the resulting DMG and checksum as a GitHub release. The job fails closed when release credentials are absent.

## Release verification

Before publishing, verify on a clean Apple Silicon Mac:

```sh
codesign --verify --deep --strict --verbose=2 "/Applications/Codex Gamepad Setup.app"
spctl --assess --type execute --verbose=2 "/Applications/Codex Gamepad Setup.app"
xcrun stapler validate "/Applications/Codex Gamepad Setup.app"
```

Complete the software preflight and the physical checks in [HARDWARE_TEST.md](HARDWARE_TEST.md). A passing automated build does not substitute for pressing the real controller buttons or verifying game handoff on release hardware.
