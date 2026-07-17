# Agent instructions

For any request to install, configure, repair, test, upgrade, or uninstall Codex Gamepad, read `.agents/skills/install-codex-gamepad/SKILL.md` completely and follow it.

Protect existing Karabiner profiles and unrelated user files. Never expose Codex response text in command output or logs, never ask for a password in chat, and never claim a physical controller action was verified unless the user actually performed it.

For ordinary development work, run the relevant focused tests after changes and the full dependency-free suite before handoff:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
