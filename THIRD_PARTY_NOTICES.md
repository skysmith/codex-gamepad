# Third-party notices

Codex Gamepad's setup app bundles uv. The optional speech path interoperates with the other dependencies and model files below without bundling them.

## uv (bundled in the Apple Silicon setup app)

The setup app bundles the arm64 `uv` executable to create an isolated Python runtime. uv is distributed under the Apache License 2.0 or MIT License, at the user's option.

- Project: `astral-sh/uv`
- Version bundled by the v0.1 release workflow: 0.11.14
- Source and licenses: https://github.com/astral-sh/uv

## Kokoro model

- Project: `hexgrad/Kokoro-82M`
- License: Apache License 2.0
- Source: https://huggingface.co/hexgrad/Kokoro-82M

## kokoro-onnx

- Project: `thewh1teagle/kokoro-onnx`
- Version used by this project: 0.5.0
- License: MIT
- Source: https://github.com/thewh1teagle/kokoro-onnx

## phonemizer-fork and eSpeak NG

The current `kokoro-onnx` Python installation uses GPL-3.0-or-later phonemizer/eSpeak components. They remain separately installed runtime dependencies and are not copied into this repository.

- phonemizer-fork: https://pypi.org/project/phonemizer-fork/
- eSpeak NG: https://github.com/espeak-ng/espeak-ng

Review the applicable licenses before distributing a combined binary or app bundle. This notice is informational and is not legal advice.

## Karabiner user-command receiver

- Project: `pqrs-org/Karabiner-Elements-user-command-receiver`
- Version: 1.2.0
- License: Unlicense
- Source: https://github.com/pqrs-org/Karabiner-Elements-user-command-receiver
