# Ultimate 2C hardware test

The software path and raw controller calibration are complete. The numbered button events below were observed on the physical controller. Core live checks for D-pad Up and L4-triggered Kokoro playback also passed; the remaining controls and automatic game handoff still need physical verification.

## Verified test setup

- Controller: 8BitDo Ultimate 2C Wireless
- Transport: Bluetooth Low Energy
- `vendor_id`: 11720 (`0x2dc8`)
- `product_id`: 12315 (`0x301b`)
- Karabiner classification: gamepad
- Karabiner-Elements: 16.1.0, installed and configured
- Controller **Modify events**: enabled in the **Codex Controller** profile; **Game Mode** releases the controller from Karabiner
- Gamepad mouse flags: X, Y, vertical wheel, and horizontal wheel are all discarded so stick motion remains inert outside Codex
- Local installer, receiver, Kokoro assets, and permissions: configured
- `./scripts/preflight.sh`: passing with the controller connected

8BitDo does not officially list this model for macOS, but its Bluetooth gamepad interface is recognized on the tested Mac.

## Recorded events

Each numbered button was pressed and observed individually:

| Physical control | Observed Karabiner event | Verification |
| --- | --- | --- |
| A | `pointing_button: button1` | Hardware verified |
| B | `pointing_button: button2` | Hardware verified |
| X | `pointing_button: button4` | Hardware verified |
| Y | `pointing_button: button5` | Hardware verified |
| L4 / first extra | `pointing_button: button3` | Hardware verified |
| R4 / second extra | `pointing_button: button6` | Hardware verified |
| LB | `pointing_button: button7` | Hardware verified |
| RB | `pointing_button: button8` | Hardware verified |
| Physical D-pad | `generic_desktop: dpad_up/down/left/right` | Hat-switch translation observed; Up emitted `up_arrow` in Codex |

The physical D-pad is HID usage `0x39` (hat switch), which Karabiner-EventViewer does not expose as a normal raw button event. With **Modify events** enabled for the controller, Karabiner converts it to the four `generic_desktop` D-pad events used by the profile. The left analog stick reports axis motion instead and is not the D-pad.

The current `is_game_pad` condition remains intentionally portable; the verified device identifiers are documented here rather than required by the profile.

## Functional verification

Verified live with Codex frontmost:

- Physical D-pad Up emitted the virtual `up_arrow` event.
- L4 invoked the local Kokoro speech path and launched `afplay`.

The following checks remain:

- D-pad Down, Left, and Right emit the corresponding arrow keys and move focus/caret as expected.
- A activates the focused control or submits where Return normally does.
- B dismisses with Escape.
- X tabs focus.
- Y opens the command menu.
- LB/RB move to the previous/next task.
- R4 also starts the last completed response with Kokoro.
- Pressing the active speech button again stops speech promptly.

With an unsupported app frontmost, every Codex controller action must do nothing. Supported game experiences are the deliberate exception: they must receive the raw controller instead.

While Codex is actively responding, speech must use the preceding completed final answer and never read commentary or partial output.

## Automatic game handoff verification

The foreground watcher is designed to release the controller only for these experiences:

| Foreground experience | Detection boundary | Expected controller owner |
| --- | --- | --- |
| Codex Arcade browser shelf or cabinet | Frontmost Chrome process uses `$HOME/Library/Application Support/Codex Arcade/Chrome` | Browser Gamepad API / cabinet |
| Ordinary Chrome | Frontmost Chrome process does not use the dedicated Arcade profile | **Codex Controller**; no Codex action because Codex is not frontmost |
| ares | Bundle identifier `dev.ares.ares` | ares |
| Living Forest client | Frontmost Luanti process uses a config below `~/Library/Application Support/Living Forest/runtime/players/` | Living Forest native controller bridge |
| Codex or any other app | None of the game signatures above | **Codex Controller**; mappings fire only in Codex |

A live focus-only pass (with the controller asleep) confirmed that both ares and the dedicated Arcade Chrome process select **Game Mode**, and that returning to Codex restores **Codex Controller**.

The following live checks remain:

1. Start `Codex Arcade.app`, focus its dedicated kiosk window, and confirm a controller button or D-pad input seats/navigates Player 1 without generating Karabiner keyboard events.
2. Move focus from Arcade to Codex without quitting Arcade. Confirm the controller is recaptured and D-pad Up again emits `up_arrow`; return to Arcade and confirm raw controller input resumes without reconnecting it.
3. Focus an ordinary Chrome window and confirm it does **not** trigger Game Mode. Switch between ordinary Chrome and the dedicated Arcade Chrome instance to verify the process-level distinction.
4. Open a Nintendo 64 game in ares and confirm the physical controller is visible and playable. Move focus to Codex and back to confirm ownership follows focus rather than whether ares remains running.
5. Launch The Living Forest from Arcade and confirm its frontmost Luanti player window keeps Game Mode active and receives the native controller bridge. An unrelated Luanti window must not match the Living Forest signature.
6. Repeat rapid Arcade/Codex and ares/Codex focus changes, including after the controller sleeps and reconnects and after the Mac wakes, and confirm startup/activation/wake reconciliation leaves the intended mode selected. Also verify the two-second retry after Karabiner is temporarily unavailable.

## Finalize the profile

1. Complete the remaining functional and automatic handoff checks above; the checked-in button numbers already match the observed hardware events.
2. Keep only the preferred extra button for speech; release the other for a future action.
3. Run the test and validation commands from the README.
4. Treat 2.4 GHz/wired support as an experiment: those Windows modes are likely XInput, which Karabiner does not support. Only add a transport after EventViewer recognizes it and the full pass succeeds.
