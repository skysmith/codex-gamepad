// SPDX-License-Identifier: Unlicense
// JavaScript should be written in ECMAScript 5.1.

function conditions() {
  return [
    {
      type: 'device_if',
      identifiers: [{ is_game_pad: true }],
    },
    {
      type: 'frontmost_application_if',
      bundle_identifiers: ['^com\\.openai\\.codex$'],
    },
  ]
}

function keyManipulator(from, to) {
  from.modifiers = { optional: ['any'] }
  return {
    type: 'basic',
    from: from,
    to: [to],
    conditions: conditions(),
  }
}

function main() {
  var manipulators = [
    keyManipulator({ generic_desktop: 'dpad_up' }, { key_code: 'up_arrow' }),
    keyManipulator({ generic_desktop: 'dpad_down' }, { key_code: 'down_arrow' }),
    keyManipulator({ generic_desktop: 'dpad_left' }, { key_code: 'left_arrow' }),
    keyManipulator({ generic_desktop: 'dpad_right' }, { key_code: 'right_arrow' }),
    keyManipulator({ pointing_button: 'button1' }, { key_code: 'return_or_enter' }),
    keyManipulator({ pointing_button: 'button2' }, { key_code: 'escape' }),
    keyManipulator({ pointing_button: 'button4' }, { key_code: 'tab' }),
    keyManipulator(
      { pointing_button: 'button5' },
      { key_code: 'k', modifiers: ['left_command'] }
    ),
    keyManipulator(
      { pointing_button: 'button7' },
      { key_code: 'open_bracket', modifiers: ['left_command', 'left_shift'] }
    ),
    keyManipulator(
      { pointing_button: 'button8' },
      { key_code: 'close_bracket', modifiers: ['left_command', 'left_shift'] }
    ),
  ]

  console.log(
    JSON.stringify(
      {
        title: 'Codex Gamepad (DirectInput)',
        rules: [
          {
            description: 'Codex Gamepad - navigation (8BitDo Ultimate 2C)',
            manipulators: manipulators,
          },
        ],
      },
      null,
      '  '
    )
  )
}

main()
