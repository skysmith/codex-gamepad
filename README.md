# Codex Gamepad

Codex Gamepad turns a DirectInput controller into a focused keyboard for Codex Desktop on macOS. It also adds the missing **speak last response** action using local [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) speech.

**License:** MIT. This is an unofficial community project and is not affiliated with OpenAI, Karabiner-Elements, 8BitDo, or Kokoro.

**Distribution status:** source alpha. Clone or download the complete repository and use the guarded local installer; the Python wheel by itself does not include the Swift receiver, Karabiner profile, installer, or agent skill.

## Let your coding agent install it

Open this repository as a local project in Codex or Claude Code, connect the controller when available, and give the agent one of these prompts.

**Codex:**

> Use `$install-codex-gamepad` to inspect this Mac and finish installing, configuring, and testing Codex Gamepad. Preserve my existing Karabiner setup and pause whenever I need to grant a permission or press a controller button.

**Claude Code or another coding agent:**

> Read `CLAUDE.md` and `.agents/skills/install-codex-gamepad/SKILL.md`, then inspect this Mac and finish installing, configuring, and testing Codex Gamepad. Preserve my existing Karabiner setup and pause whenever I need to grant a permission or press a controller button.

The agent can install dependencies, build the receiver, configure owned Karabiner profiles, run diagnostics, and guide the live hardware pass. The user must personally approve macOS permissions, enter any password into the native system prompt, and perform the requested controller presses. The current reference profile is for an 8BitDo Ultimate 2C over Bluetooth LE; other DirectInput controllers require event calibration before the agent should call them supported.

The automated software paths are implemented and tested, and the 8BitDo button numbers used by the profile have been captured from a physical controller over Bluetooth LE. A live Codex pass also confirmed D-pad Up and the Kokoro playback path; the current remapped controls and automatic game handoff still need end-to-end checks.

The current reference target is macOS 26.5 on Apple silicon, Karabiner-Elements 16.1.0, Swift 6.3.3, Python 3.13.13, and Codex Desktop 26.707.30751 (build 5018). Hardware calibration is for the 8BitDo Ultimate 2C Wireless over Bluetooth LE (`11720:12315`).

## Current status

- Codex response selection uses the documented `thread/list` and `thread/read` methods. The enclosing `codex app-server` command is still experimental, so public releases declare the Codex versions they were tested against.
- Only the newest completed turn's `final_answer` is used (with a narrowly scoped unphased assistant-message fallback for older Codex builds). Plans, commentary, tools, interrupted turns, in-progress output, and subagents are ignored.
- Kokoro ONNX has rendered a real 24 kHz WAV successfully on the target Mac.
- The Karabiner 16 user-command receiver builds against the official receiver package.
- The local profile and upstream navigation generator pass Karabiner's own linter/build.
- An 8BitDo Ultimate 2C Wireless is recognized as a gamepad over Bluetooth LE (`vendor_id` 11720 / `0x2dc8`, `product_id` 12315 / `0x301b`).
- A, B, X, Y, LB, RB, L4, R4, and RT have hardware-verified Karabiner button numbers.
- The physical D-pad reports HID hat-switch usage `0x39`; after controller event modification is enabled, Karabiner translates it to `generic_desktop` D-pad events. A live test confirmed that D-pad Up emits `up_arrow` in Codex; the other directions remain untested end to end.
- A live L4 press invoked the local Kokoro path and launched `afplay` under the earlier calibration mapping. Speech now lives on X; X start/stop remains to be checked end to end.
- A live focus pass confirmed automatic `Codex Controller` → `Game Mode` → `Codex Controller` switching for both the dedicated Arcade Chrome process and ares. Living Forest classification passes the receiver self-test; raw controller delivery in each game remains to be checked physically.
- No response text enters a shell command, log, notification, or persistent audio cache.
- iPhone/remote-control support is intentionally out of scope.

## Controller profile

![Labeled Codex controls for the 8BitDo Ultimate 2C](docs/assets/codex-controls-8bitdo-ultimate-2c.png)

| Controller input | Karabiner event | Codex action | Status |
| --- | --- | --- | --- |
| Physical D-pad | `dpad_up/down/left/right` | Arrow keys | Up emitted `up_arrow` in Codex; other directions pending |
| A | `button1` | Hold to dictate; release to insert for review (`Ctrl-Shift-D`) | Event verified; remapped action pending |
| B | `button2` | Escape | Event verified |
| X | `button4` | Speak last response; press again to stop | Event verified; remapped action pending |
| Y | `button5` | Next field (`Tab`) | Event verified; remapped action pending |
| LB | `button7` | Previous task (`Cmd-Shift-[`) | Event verified |
| RB | `button8` | Next task (`Cmd-Shift-]`) | Event verified |
| L4 | `button3` | Command menu (`Cmd-K`) | Event verified; remapped action pending |
| R4 | `button6` | Reserved / unmapped | Event verified |
| RT | `button10` | Return / send (press duration does not matter) | Event verified; remapped action pending |

The status above distinguishes raw controller events from resulting Codex actions. Only D-pad Up and the Kokoro launch path (using the earlier L4 mapping) have been verified end to end so far. The current layout keeps the face buttons focused on the speak/write loop: hold A to dictate, release it to review the transcription, then press RT to send. X reads the last answer, Y moves focus, and B cancels.

An experimental RT tap/hold split was rejected after live testing: a natural trigger squeeze can exceed a short timing threshold and be mistaken for a hold, making Send unreliable. The reference layout deliberately gives RT one unconditional action instead.

8BitDo officially lists this model for Windows/Android rather than macOS. Bluetooth may expose a usable Android/DirectInput device, which is consistent with the controller pairing successfully; the 2.4 GHz and wired Windows modes are likely XInput and therefore unsupported by Karabiner unless EventViewer proves otherwise.

The profile is restricted twice: input must come from a gamepad, and Codex (`com.openai.codex`) must be frontmost. With the four gamepad mouse-discard flags below enabled, it does nothing in unsupported apps.

## Automatic game handoff

The existing `com.codex-gamepad.receiver` LaunchAgent also watches foreground ownership; no second background service is installed. It switches Karabiner between two controller-ownership profiles created by the installer:

- **Codex Controller** lets Karabiner modify the controller. The mappings above still fire only while Codex is frontmost, so an unsupported foreground app receives neither accidental controller-generated keystrokes nor Codex speech actions.
- **Game Mode** tells Karabiner to ignore the controller, releasing its raw HID/gamepad events to the active game.

The paired profiles change ownership only for the hardware-verified Ultimate 2C entry (`vendor_id` 11720, `product_id` 12315); other controller and keyboard device settings are preserved.

Karabiner switches the whole profile, so **Game Mode** is a managed snapshot of **Codex Controller** with only that 8BitDo ownership flag changed. After changing unrelated keyboard/device settings in Karabiner, rerun the installer to resynchronize the pair. The installer records ownership separately, refuses to overwrite pre-existing profiles with either managed name, and uninstall restores the profile that was selected before the pair was created.

The switch follows the foreground experience, not whether an application or local server is merely running. Leaving Arcade or ares open in the background therefore returns the controller to **Codex Controller**; focusing the game again releases it without requiring a manual Karabiner toggle. The receiver reconciles the mode at startup, after each app activation, and after Mac wake; if Karabiner is temporarily unavailable, it retries every two seconds until switching succeeds.

Supported foreground detections are intentionally narrow:

- **Codex Arcade:** a dedicated Chrome instance using `--user-data-dir=$HOME/Library/Application Support/Codex Arcade/Chrome`. An ordinary Chrome window does not activate Game Mode. Detection survives navigation from the shelf to any browser cabinet.
- **ares / Nintendo 64:** the frontmost ares application (`dev.ares.ares`). ares supports other systems too; foreground ares is treated as a game throughout its library, setup, and play screens so controller configuration remains possible.
- **The Living Forest:** the native Luanti client launched by the Arcade cabinet. It is distinguished from an unrelated Luanti session by its Living Forest player configuration path under `~/Library/Application Support/Living Forest/runtime/players/`; ordinary Luanti therefore remains in **Codex Controller**.

The installed `Codex Arcade.app` is only a short-lived launcher, and Arcade's loopback ports (`8791` for the shelf and `8792` for the native launcher by default) can remain open in the background without holding Game Mode. See the [hardware checklist](docs/HARDWARE_TEST.md) for the remaining physical handoff tests.

## How speech works

```text
controller
  -> Karabiner send_user_command (fixed payload, dedicated local socket)
  -> tiny Swift receiver (rechecks frontmost app)
  -> codex-speak-last
  -> Codex app-server thread/list + thread/read
  -> Markdown cleanup and sentence chunks
  -> local Kokoro ONNX
  -> mode-0600 temporary WAV -> afplay -> immediate deletion
```

A second press terminates the speech worker and its active `afplay` process group. The default voice is `af_heart` at `1.05x`; both are configurable.

### Task-selection limitation

Codex app-server exposes task recency, but not the task currently visible in the window. Automatic mode therefore speaks the most recently **prompted** Desktop task. Merely navigating to an older task without sending a new prompt does not change that selection. Use `--thread THREAD_ID` when an exact task must be pinned.

This is still safer than scraping Codex's private rollout format. Rollout parsing exists only as explicit compatibility mode (`--rollout` or `--compat-rollout-fallback`).

Persistent non-secret defaults live in `~/.config/codex-gamepad/config.json`. Copy `config.example.json` and optionally add `"thread": "..."` to pin the controller to one task. The config allowlists operational settings only; response text is never stored there.

## Install

Requirements:

- macOS 15 or newer for the Karabiner user-command receiver
- [Karabiner-Elements 16 or newer](https://karabiner-elements.pqrs.org/)
- Swift 6.2 or newer / current Xcode Command Line Tools to build the small receiver
- Python 3.10–3.13 with `kokoro-onnx==0.5.0` and `soundfile`
- [`uv`](https://docs.astral.sh/uv/) only when using `--create-venv` instead of an existing compatible Python
- Kokoro v1.0 model and voices files

The controller does not need to be connected for software installation. Connect it in its Karabiner-compatible DirectInput/Bluetooth LE mode for calibration and the live hardware pass.

Preview installation without changing the machine:

```sh
./scripts/install-local.sh --dry-run --python /path/to/kokoro-python
```

After Karabiner is installed and opened once:

```sh
./scripts/install-local.sh --python /path/to/kokoro-python
```

The installer reuses a compatible Kokoro Python on `PATH` or one passed explicitly. On a new Mac, create a dedicated environment with:

```sh
./scripts/install-local.sh --create-venv
./scripts/download-models.sh
```

The model download is about 337 MB and is checksum-verified. No network is used during speech.

Then in Karabiner-Elements:

1. Enable the controller under **Devices** and confirm it is recognized as a gamepad.
2. Open its **game pad settings > Others > Mouse Flags** and enable **Discard mouse X**, **Discard mouse Y**, **Discard vertical wheel**, and **Discard horizontal wheel**. Karabiner's built-in stick converter is otherwise global; these flags keep both sticks inert outside Codex while preserving buttons and the D-pad.
3. Under **Complex Modifications**, enable **Codex Gamepad — navigation**.
4. Enable **Codex Gamepad — Kokoro speak/stop (Karabiner 16 receiver)**.
5. Do not also enable the legacy shell fallback rule.

The receiver uses a Codex Gamepad-specific Unix socket, so it does not occupy Karabiner's shared default receiver endpoint. The legacy shell rule is available if the Swift receiver is intentionally skipped; its extra frontmost-app check uses System Events and may require macOS Automation permission.

Navigation actions assume Codex's documented default keyboard shortcuts, including `Ctrl-Shift-D` for A's review-first composer dictation. If those shortcuts were customized under **Settings > Keyboard Shortcuts**, update the corresponding `to` events in the profile.

Use the [hardware checklist](docs/HARDWARE_TEST.md) to complete the remaining functional checks.

## Command-line checks

Check the full Mac-side setup before connecting the controller:

```sh
./scripts/preflight.sh
```

The preflight is read-only and suppresses all response text. A missing controller
is only a warning; software blockers such as an unavailable receiver socket or
invalid Karabiner rule produce a failure.

The dry run reveals metadata and counts, never response text:

```sh
codex-speak-last --dry-run
```

Speak in the foreground:

```sh
codex-speak-last
```

Exercise the same toggle path used by the controller:

```sh
codex-speak-last --background --toggle --require-frontmost
```

Render an explicitly requested mode-0600 persistent file instead of playing it:

```sh
codex-speak-last --output /tmp/codex-response.wav
```

No system `say` fallback is used: if Kokoro is unavailable, the action fails clearly.

## Uninstall

Installation adds a checkout-independent uninstaller to the application directory and a launcher at `$HOME/.local/bin/codex-gamepad-uninstall` (also available by name when that directory is on `PATH`). It uses the managed environment when present, or another Python 3.10–3.13 interpreter:

```sh
"$HOME/.local/bin/codex-gamepad-uninstall"
```

The default removal restores the previously selected Karabiner profile and preserves the downloaded Kokoro models for a safe later reinstall. It also preserves `~/.config/codex-gamepad/config.json`, which can contain a pinned task ID and local asset paths; remove that file separately only when intentionally clearing those local preferences. Remove the models as well only when intentionally reclaiming that space:

```sh
"$HOME/.local/bin/codex-gamepad-uninstall" --models
```

## Development

Run the dependency-free tests:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Other verification:

```sh
python3 -m json.tool karabiner/codex-gamepad.json >/dev/null
for script in scripts/*.sh; do bash -n "$script"; done
swift build -c release --package-path receiver
receiver/.build/release/codex-gamepad-receiver --self-test
node karabiner/upstream/codex_gamepad.json.js | python3 -m json.tool >/dev/null
```

## Upstream path

The main Karabiner application does not need a fork. The contribution target is [pqrs-org/KE-complex_modifications](https://github.com/pqrs-org/KE-complex_modifications), which already accepts gamepad profiles.

`karabiner/upstream/codex_gamepad.json.js` is the navigation-only, dependency-free contribution candidate. It is separately dedicated under the Unlicense/public-domain terms used by that upstream repository. After the remaining functional pass:

1. Fork `KE-complex_modifications`.
2. Copy the generator to `src/json/codex_gamepad.json.js`.
3. Add the maintainer handle and confirmed device notes.
4. Run `make all` and test the generated profile.
5. Submit the profile PR.

The Kokoro rule stays in this repository because it depends on a separately installed helper.

## License and dependencies

Project code is MIT licensed. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing a bundled app or binary; the optional Python speech stack includes GPL-licensed phonemizer/eSpeak components, while `kokoro-onnx` is MIT and Kokoro weights are Apache-2.0.
