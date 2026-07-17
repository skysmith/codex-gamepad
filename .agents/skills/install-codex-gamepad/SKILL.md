---
name: install-codex-gamepad
description: Safely inspect, install, configure, verify, repair, or uninstall Codex Gamepad on a Mac. Use for source-based setup of the Karabiner controller mappings, local Kokoro speak-last helper, Swift receiver, macOS permissions, 8BitDo hardware identification, button testing, or automatic game handoff.
---

# Install Codex Gamepad

Resolve and work from the repository root containing `README.md`, `scripts/install-local.sh`, and `scripts/preflight.sh`; stop if those files are absent. Treat installation as a guarded, partly interactive Mac setup: automate deterministic checks and builds, but let the user grant macOS permissions, enter passwords, and press controller buttons.

## Boundaries

- Support macOS 15 or newer, Karabiner-Elements 16 or newer, Codex Desktop, and local Kokoro speech.
- Treat 8BitDo Ultimate 2C over Bluetooth LE (`vendor_id` 11720, `product_id` 12315) as the only fully profiled controller until another device completes event calibration.
- Treat other Karabiner-recognized DirectInput gamepads as unverified. Do not assume their button numbers.
- Do not promise XInput, wired/2.4 GHz, Windows, Linux, iPhone, or remote-control support.
- Do not expose Codex response text in terminal output, logs, notifications, reports, or test fixtures.
- Do not disable macOS security, bypass permissions, overwrite unrelated Karabiner profiles, or use `--adopt-existing` without explicit user approval.

## Inspect before changing anything

1. Read `README.md`, `docs/HARDWARE_TEST.md`, and any current diff touching installation or Karabiner files.
2. Run `git status --short`. Preserve unrelated user changes.
3. Run the read-only preflight first:

   ```sh
   ./scripts/preflight.sh
   ```

4. Record only versions and status: `sw_vers`, `uname -m`, `swift --version`, available Python versions, Karabiner version, and Codex app location. Never print task contents.
5. Inspect controllers with Karabiner's CLI through the repository sanitizer. Never display or log the raw device listing:

   ```sh
   "/Library/Application Support/org.pqrs/Karabiner-Elements/bin/karabiner_cli" --list-connected-devices 2>/dev/null \
     | python3 scripts/sanitize-karabiner-devices.py --controllers-only
   ```

A missing controller is non-blocking for software installation. Report only controller product/manufacturer, transport, vendor/product IDs, and gamepad classification; omit serial numbers and Bluetooth addresses. Multiple gamepads, a device not marked `is_game_pad`, or identifiers other than the verified pair require explicit hardware calibration before claiming readiness.

## Prepare prerequisites

Install only missing prerequisites, using an existing trusted package manager when possible. Do not pipe a downloaded script into a shell:

- Official Karabiner-Elements 16+
- Current Xcode Command Line Tools with Swift 6.2 or newer
- Python 3.10–3.13
- `uv` when creating the dedicated Kokoro environment

Never ask the user to paste a password into chat. Pause while they type into a native prompt. Open Karabiner once and have the user grant its requested background-service, Driver Extension, Input Monitoring, and Accessibility permissions. Do not automate approval controls or attempt to work around denied permissions.

## Install

Preview the exact target paths before writing:

```sh
./scripts/install-local.sh --dry-run --create-venv
```

Resolve every unexpected dry-run error before continuing. Then install the local runtime and models:

```sh
./scripts/install-local.sh --create-venv
./scripts/download-models.sh
```

Reuse an already-compatible environment by passing `--python PATH` instead of creating another one. Keep Kokoro dependencies and model artifacts as install-time downloads; do not copy a developer venv or checked-out build directory to another Mac.

The installer must refuse unsafe prefix ownership or Karabiner profile-name collisions. If it refuses, explain the collision and request a decision rather than deleting, renaming, adopting, or overwriting profiles on your own.

Before the real install, disclose that automatic game handoff creates two owned profiles and selects between them while its receiver runs. If the user depends on manually switching other Karabiner profiles, stop and ask whether to continue; do not silently take over their selected profile.

## Complete Karabiner setup

In the `Codex Controller` profile, configure the connected verified controller:

1. Enable **Modify events**.
2. Under **game pad settings > Others > Mouse Flags**, enable discard for mouse X, mouse Y, vertical wheel, and horizontal wheel.
3. Enable **Codex Gamepad — navigation** under Complex Modifications.
4. Enable **Codex Gamepad — Kokoro speak/stop (Karabiner 16 receiver)**.
5. Keep the legacy shell fallback disabled.

Use GUI automation only when the environment has an authorized computer-use tool. Otherwise give the user one instruction at a time and verify the resulting configuration with preflight.

If the user's Codex keyboard shortcuts differ from the documented defaults, either restore the defaults or update the generated Karabiner mappings with the user's approval.

## Calibrate unverified hardware

Do not generalize from face-button labels. Use Karabiner-EventViewer and ask for one physical control at a time. Capture D-pad directions, face buttons, bumpers, extra buttons, and connection mode. Distinguish raw-event verification from the resulting Codex action.

Only add a device profile after all required events are identified. Keep device identifiers and mappings scoped to that controller, add regression tests, and label the transport tested. If EventViewer cannot see usable events, stop and report that the connection mode is unsupported.

## Verify

Run the complete automated tests and setup check:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
./scripts/preflight.sh
```

Require zero preflight failures. A missing-controller warning is acceptable only when the controller is intentionally unavailable.

Ask before audible playback because the last response may be private. After consent, verify the installed speech toggle:

```sh
"$HOME/.local/bin/codex-speak-last" --background --toggle --require-frontmost
```

With Codex frontmost and an empty composer, guide the user through every row in `docs/HARDWARE_TEST.md`, one control at a time. Test A/Return last so it cannot submit unintended text. Confirm speech starts and a second press stops it. If automatic game handoff is enabled, focus each configured game and Codex in turn, check the selected Karabiner profile, and confirm the game receives raw controller input without generated keystrokes.

Never mark an unpressed control or untested game as verified.

## Recover or uninstall

On failure, preserve diagnostic output that contains no response text. Prefer rerunning the idempotent installer after correcting the cause. Do not hand-edit Karabiner JSON after the ownership helper refuses a change.

Uninstall through the installed launcher when available, or from this checkout:

```sh
codex-gamepad-uninstall
# Equivalent installed path:
"$HOME/.local/share/codex-gamepad/scripts/uninstall-local.sh"
# Source-checkout fallback:
./scripts/uninstall-local.sh
```

Default uninstall preserves downloaded models and their ownership marker for a safe later reinstall. Pass `--models` only when the user explicitly asks to remove them too.

## Handoff report

Report:

- installed app, Karabiner, Swift, Python, and controller versions/identifiers;
- paths written and whether game handoff is enabled;
- automated test and preflight summaries;
- controls and games physically verified versus still pending;
- exact remediation for any blocker;
- uninstall command.

Call the result ready only within the hardware, transport, macOS, Karabiner, and Codex versions actually tested.
