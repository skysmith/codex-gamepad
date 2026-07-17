from __future__ import annotations

import copy
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.configure_gamepad_profiles as profile_helper
from scripts.configure_gamepad_profiles import (
    AtomicWriteError,
    CLEANUP_PREPARED,
    CLEANUP_REMOVING,
    CODEX_PROFILE_NAME,
    DEVICE_IDENTIFIERS,
    GAME_PROFILE_NAME,
    LEGACY_RECEIVER_RULE_DESCRIPTION,
    MANAGED_PROFILE_NAMES,
    NAVIGATION_RULE_DESCRIPTION,
    RECEIVER_RULE_DESCRIPTION,
    SHELL_FALLBACK_RULE_DESCRIPTION,
    STATE_VERSION,
    ConfigurationError,
    check_configure_path,
    check_finalize_remove_path,
    check_remove_path,
    configure_path,
    configure_profiles,
    finalize_remove_path,
    prepare_remove_path,
    remove_path,
)


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "configure_gamepad_profiles.py"


def profile_named(config: dict, name: str) -> dict:
    return next(profile for profile in config["profiles"] if profile.get("name") == name)


def target_device(profile: dict) -> dict:
    return next(
        device
        for device in profile["devices"]
        if device.get("identifiers") == DEVICE_IDENTIFIERS
    )


def write_config(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config), encoding="utf-8")


def managed_rule(description: str, marker: str) -> dict:
    return {
        "description": description,
        "manipulators": [
            {
                "type": "basic",
                "from": {"key_code": "f1"},
                "to": [{"key_code": "f2", "test_marker": marker}],
            }
        ],
    }


def write_rules_file(path: Path) -> dict:
    navigation = managed_rule(NAVIGATION_RULE_DESCRIPTION, "fresh-navigation")
    receiver = managed_rule(RECEIVER_RULE_DESCRIPTION, "fresh-receiver")
    shell_fallback = managed_rule(
        SHELL_FALLBACK_RULE_DESCRIPTION,
        "fresh-shell-fallback",
    )
    asset = {
        "title": "Codex Gamepad",
        "rules": [
            navigation,
            receiver,
            shell_fallback,
            managed_rule("Unmanaged asset rule", "ignore-me"),
        ],
    }
    write_config(path, asset)
    return {
        NAVIGATION_RULE_DESCRIPTION: navigation,
        RECEIVER_RULE_DESCRIPTION: receiver,
        SHELL_FALLBACK_RULE_DESCRIPTION: shell_fallback,
    }


class GamepadProfileConfigurationTests(unittest.TestCase):
    def test_receiver_rule_descriptions_keep_the_public_name_and_migrate_the_preview_name(
        self,
    ) -> None:
        self.assertEqual(
            RECEIVER_RULE_DESCRIPTION,
            "Codex Gamepad — Kokoro speak/stop (Karabiner 16 receiver)",
        )
        self.assertEqual(
            LEGACY_RECEIVER_RULE_DESCRIPTION,
            "Codex Gamepad — receiver actions (dictation + Kokoro; Karabiner 16)",
        )
        self.assertEqual(
            SHELL_FALLBACK_RULE_DESCRIPTION,
            "Codex Gamepad — Kokoro speak/stop "
            "(legacy shell fallback; do not enable with receiver rule)",
        )

    def test_creates_profiles_from_selected_profile_and_preserves_unrelated_data(self) -> None:
        keyboard = {
            "identifiers": {"is_keyboard": True, "product_id": 22, "vendor_id": 11},
            "ignore": False,
            "disable_built_in_keyboard_if_exists": True,
        }
        source_profile = {
            "name": "Default profile",
            "selected": True,
            "devices": [keyboard],
            "complex_modifications": {"rules": [{"description": "Keep this rule"}]},
            "virtual_hid_keyboard": {"keyboard_type_v2": "ansi"},
        }
        other_profile = {
            "name": "Work",
            "selected": False,
            "parameters": {"delay_milliseconds_before_open_device": 750},
        }
        original = {
            "global": {"show_in_menu_bar": False},
            "profiles": [source_profile, other_profile],
        }
        original_snapshot = copy.deepcopy(original)

        configured = configure_profiles(original)

        self.assertEqual(original, original_snapshot)
        self.assertEqual(configured["global"], original["global"])
        self.assertEqual(profile_named(configured, "Work"), other_profile)
        self.assertFalse(profile_named(configured, "Default profile")["selected"])

        codex = profile_named(configured, CODEX_PROFILE_NAME)
        game = profile_named(configured, GAME_PROFILE_NAME)
        self.assertTrue(codex["selected"])
        self.assertFalse(game["selected"])
        self.assertEqual(codex["complex_modifications"], source_profile["complex_modifications"])
        self.assertEqual(codex["devices"][0], keyboard)

        codex_device = target_device(codex)
        game_device = target_device(game)
        self.assertFalse(codex_device["ignore"])
        self.assertTrue(game_device["ignore"])
        for key in (
            "mouse_discard_horizontal_wheel",
            "mouse_discard_vertical_wheel",
            "mouse_discard_x",
            "mouse_discard_y",
        ):
            self.assertTrue(codex_device[key])
            self.assertTrue(game_device[key])

        expected_game = copy.deepcopy(codex)
        expected_game["name"] = GAME_PROFILE_NAME
        expected_game["selected"] = False
        target_device(expected_game)["ignore"] = True
        self.assertEqual(game, expected_game)

    def test_name_collision_without_state_is_refused_without_writes(self) -> None:
        for managed_name in MANAGED_PROFILE_NAMES:
            with self.subTest(managed_name=managed_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = root / "karabiner.json"
                state_path = root / "ownership.json"
                original = {
                    "profiles": [
                        {"name": "Personal", "selected": True, "custom": "keep"},
                        {"name": managed_name, "selected": False, "custom": "not ours"},
                    ]
                }
                write_config(config_path, original)
                original_bytes = config_path.read_bytes()

                with self.assertRaisesRegex(ConfigurationError, "--adopt-existing"):
                    configure_path(config_path, state_path)

                self.assertEqual(config_path.read_bytes(), original_bytes)
                self.assertFalse(state_path.exists())

    def test_check_validates_safe_config_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "private" / "ownership.json"
            write_config(
                config_path,
                {"profiles": [{"name": "Default", "selected": True}]},
            )
            original = config_path.read_bytes()

            self.assertTrue(check_configure_path(config_path, state_path))

            self.assertEqual(config_path.read_bytes(), original)
            self.assertFalse(state_path.exists())
            self.assertFalse(state_path.parent.exists())

    def test_rules_file_refreshes_enabled_rules_and_migrates_receiver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            rules_path = root / "codex-gamepad.json"
            old_navigation = managed_rule(NAVIGATION_RULE_DESCRIPTION, "old-navigation")
            preview_receiver = managed_rule(
                LEGACY_RECEIVER_RULE_DESCRIPTION,
                "preview-receiver",
            )
            stale_public_receiver = managed_rule(
                RECEIVER_RULE_DESCRIPTION,
                "stale-public-receiver",
            )
            unrelated_rule = managed_rule("Keep this rule", "unrelated")
            write_config(
                config_path,
                {
                    "global": {"show_in_menu_bar": False},
                    "profiles": [
                        {
                            "name": "Default",
                            "selected": True,
                            "custom": {"preserve": True},
                            "complex_modifications": {
                                "parameters": {"basic.to_if_alone_timeout_milliseconds": 999},
                                "rules": [
                                    old_navigation,
                                    unrelated_rule,
                                    preview_receiver,
                                    stale_public_receiver,
                                ],
                            },
                        },
                        {"name": "Work", "selected": False, "work_setting": 42},
                    ],
                },
            )
            configure_path(config_path, state_path)
            before_refresh = json.loads(config_path.read_text(encoding="utf-8"))
            expected_rules = write_rules_file(rules_path)

            self.assertTrue(
                configure_path(
                    config_path,
                    state_path,
                    rules_file=rules_path,
                )
            )

            configured = json.loads(config_path.read_text(encoding="utf-8"))
            codex = profile_named(configured, CODEX_PROFILE_NAME)
            game = profile_named(configured, GAME_PROFILE_NAME)
            codex_rules = codex["complex_modifications"]["rules"]
            self.assertEqual(
                [rule["description"] for rule in codex_rules],
                [
                    NAVIGATION_RULE_DESCRIPTION,
                    "Keep this rule",
                    RECEIVER_RULE_DESCRIPTION,
                ],
            )
            self.assertEqual(codex_rules[0], expected_rules[NAVIGATION_RULE_DESCRIPTION])
            self.assertEqual(codex_rules[1], unrelated_rule)
            self.assertEqual(codex_rules[2], expected_rules[RECEIVER_RULE_DESCRIPTION])
            self.assertEqual(
                codex["complex_modifications"]["parameters"],
                {"basic.to_if_alone_timeout_milliseconds": 999},
            )
            self.assertEqual(codex["custom"], {"preserve": True})
            self.assertEqual(
                profile_named(configured, "Work"),
                profile_named(before_refresh, "Work"),
            )
            expected_game = copy.deepcopy(codex)
            expected_game["name"] = GAME_PROFILE_NAME
            expected_game["selected"] = False
            target_device(expected_game)["ignore"] = True
            self.assertEqual(game, expected_game)

    def test_rules_file_does_not_enable_absent_managed_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            rules_path = root / "codex-gamepad.json"
            unrelated_rule = managed_rule("Keep this rule", "unrelated")
            write_config(
                config_path,
                {
                    "profiles": [
                        {
                            "name": "Default",
                            "selected": True,
                            "complex_modifications": {"rules": [unrelated_rule]},
                        }
                    ]
                },
            )
            configure_path(config_path, state_path)
            before_refresh = config_path.read_bytes()
            write_rules_file(rules_path)

            self.assertFalse(
                configure_path(
                    config_path,
                    state_path,
                    rules_file=rules_path,
                )
            )
            self.assertEqual(config_path.read_bytes(), before_refresh)
            configured = json.loads(before_refresh)
            for name in (CODEX_PROFILE_NAME, GAME_PROFILE_NAME):
                self.assertEqual(
                    profile_named(configured, name)["complex_modifications"]["rules"],
                    [unrelated_rule],
                )

    def test_rules_file_refreshes_an_enabled_shell_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            rules_path = root / "codex-gamepad.json"
            stale_fallback = managed_rule(
                SHELL_FALLBACK_RULE_DESCRIPTION,
                "old-l4-r4-fallback",
            )
            unrelated_rule = managed_rule("Keep this rule", "unrelated")
            write_config(
                config_path,
                {
                    "profiles": [
                        {
                            "name": "Default",
                            "selected": True,
                            "complex_modifications": {
                                "rules": [unrelated_rule, stale_fallback]
                            },
                        }
                    ]
                },
            )
            configure_path(config_path, state_path)
            expected_rules = write_rules_file(rules_path)

            self.assertTrue(
                configure_path(
                    config_path,
                    state_path,
                    rules_file=rules_path,
                )
            )

            configured = json.loads(config_path.read_text(encoding="utf-8"))
            for name in (CODEX_PROFILE_NAME, GAME_PROFILE_NAME):
                rules = profile_named(configured, name)["complex_modifications"]["rules"]
                self.assertEqual(rules[0], unrelated_rule)
                self.assertEqual(
                    rules[1],
                    expected_rules[SHELL_FALLBACK_RULE_DESCRIPTION],
                )

    def test_rules_file_check_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            rules_path = root / "codex-gamepad.json"
            write_config(
                config_path,
                {
                    "profiles": [
                        {
                            "name": "Default",
                            "selected": True,
                            "complex_modifications": {
                                "rules": [
                                    managed_rule(
                                        LEGACY_RECEIVER_RULE_DESCRIPTION,
                                        "old-receiver",
                                    )
                                ]
                            },
                        }
                    ]
                },
            )
            configure_path(config_path, state_path)
            write_rules_file(rules_path)
            original_config = config_path.read_bytes()
            original_state = state_path.read_bytes()

            self.assertTrue(
                check_configure_path(
                    config_path,
                    state_path,
                    rules_file=rules_path,
                )
            )
            self.assertEqual(config_path.read_bytes(), original_config)
            self.assertEqual(state_path.read_bytes(), original_state)

    def test_malformed_rules_file_is_refused_before_any_write(self) -> None:
        valid_navigation = managed_rule(NAVIGATION_RULE_DESCRIPTION, "navigation")
        valid_receiver = managed_rule(RECEIVER_RULE_DESCRIPTION, "receiver")
        malformed_assets = {
            "invalid JSON": b"{not-json",
            "non-list rules": json.dumps({"rules": {}}).encode(),
            "missing receiver": json.dumps({"rules": [valid_navigation]}).encode(),
            "duplicate receiver": json.dumps(
                {"rules": [valid_navigation, valid_receiver, valid_receiver]}
            ).encode(),
            "non-object rule": json.dumps(
                {"rules": [valid_navigation, valid_receiver, "bad"]}
            ).encode(),
            "empty manipulators": json.dumps(
                {
                    "rules": [
                        valid_navigation,
                        {
                            "description": RECEIVER_RULE_DESCRIPTION,
                            "manipulators": [],
                        },
                    ]
                }
            ).encode(),
        }
        for label, contents in malformed_assets.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = root / "karabiner.json"
                state_path = root / "ownership.json"
                rules_path = root / "codex-gamepad.json"
                write_config(
                    config_path,
                    {"profiles": [{"name": "Default", "selected": True}]},
                )
                original = config_path.read_bytes()
                rules_path.write_bytes(contents)

                with self.assertRaises(ConfigurationError):
                    configure_path(
                        config_path,
                        state_path,
                        rules_file=rules_path,
                    )
                self.assertEqual(config_path.read_bytes(), original)
                self.assertFalse(state_path.exists())

    def test_symlink_rules_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            real_rules_path = root / "real-rules.json"
            rules_path = root / "rules-link.json"
            write_config(
                config_path,
                {"profiles": [{"name": "Default", "selected": True}]},
            )
            write_rules_file(real_rules_path)
            rules_path.symlink_to(real_rules_path)
            original = config_path.read_bytes()

            with self.assertRaisesRegex(ConfigurationError, "non-symlink"):
                configure_path(
                    config_path,
                    state_path,
                    rules_file=rules_path,
                )
            self.assertEqual(config_path.read_bytes(), original)
            self.assertFalse(state_path.exists())

    def test_duplicate_enabled_navigation_rules_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            rules_path = root / "codex-gamepad.json"
            write_config(
                config_path,
                {
                    "profiles": [
                        {
                            "name": "Default",
                            "selected": True,
                            "complex_modifications": {
                                "rules": [
                                    managed_rule(
                                        NAVIGATION_RULE_DESCRIPTION,
                                        "duplicate-one",
                                    ),
                                    managed_rule(
                                        NAVIGATION_RULE_DESCRIPTION,
                                        "duplicate-two",
                                    ),
                                ]
                            },
                        }
                    ]
                },
            )
            configure_path(config_path, state_path)
            write_rules_file(rules_path)
            original = config_path.read_bytes()

            with self.assertRaisesRegex(ConfigurationError, "ambiguous refresh"):
                configure_path(
                    config_path,
                    state_path,
                    rules_file=rules_path,
                )
            self.assertEqual(config_path.read_bytes(), original)

    def test_state_creation_and_subsequent_configuration_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "private" / "ownership.json"
            write_config(
                config_path,
                {
                    "global": {"show_in_menu_bar": False},
                    "profiles": [{"name": "Default", "selected": True}],
                },
            )
            config_path.chmod(0o640)

            self.assertTrue(configure_path(config_path, state_path))
            configured_bytes = config_path.read_bytes()
            state_bytes = state_path.read_bytes()
            state_inode = state_path.stat().st_ino
            state = json.loads(state_bytes)

            self.assertEqual(state["version"], STATE_VERSION)
            self.assertEqual(state["managed_profiles"], list(MANAGED_PROFILE_NAMES))
            self.assertEqual(state["restore_profile"], "Default")
            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
            self.assertFalse(state_path.is_symlink())
            self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o640)

            self.assertFalse(configure_path(config_path, state_path))
            self.assertEqual(config_path.read_bytes(), configured_bytes)
            self.assertEqual(state_path.read_bytes(), state_bytes)
            self.assertEqual(state_path.stat().st_ino, state_inode)
            self.assertEqual(list(state_path.parent.glob(f".{state_path.name}.*.tmp")), [])

    def test_first_install_replace_failure_rolls_back_new_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            write_config(
                config_path,
                {"profiles": [{"name": "Default", "selected": True}]},
            )
            original = config_path.read_bytes()

            with mock.patch(
                "scripts.configure_gamepad_profiles.os.replace",
                side_effect=OSError("forced replacement failure"),
            ):
                with self.assertRaisesRegex(OSError, "forced replacement failure"):
                    configure_path(config_path, state_path)

            self.assertEqual(config_path.read_bytes(), original)
            self.assertFalse(state_path.exists())
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_post_replace_directory_fsync_failure_keeps_valid_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "private-state" / "ownership.json"
            write_config(
                config_path,
                {"profiles": [{"name": "Default", "selected": True}]},
            )
            real_fsync_directory = profile_helper._fsync_directory

            def fail_config_directory_fsync(path: Path) -> None:
                if path == config_path.parent:
                    raise OSError("forced config-directory fsync failure")
                real_fsync_directory(path)

            with mock.patch.object(
                profile_helper,
                "_fsync_directory",
                side_effect=fail_config_directory_fsync,
            ):
                with self.assertRaisesRegex(
                    AtomicWriteError,
                    "forced config-directory fsync failure",
                ) as raised:
                    configure_path(config_path, state_path)

            self.assertTrue(raised.exception.replaced)
            configured = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn(CODEX_PROFILE_NAME, [item.get("name") for item in configured["profiles"]])
            self.assertIn(GAME_PROFILE_NAME, [item.get("name") for item in configured["profiles"]])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["version"], STATE_VERSION)
            self.assertEqual(state["managed_profiles"], list(MANAGED_PROFILE_NAMES))
            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)

            self.assertFalse(configure_path(config_path, state_path))

    def test_adopt_existing_is_one_time_and_infers_nonmanaged_restore_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            write_config(
                config_path,
                {
                    "profiles": [
                        {"name": "Restore Me", "selected": False, "custom": "keep"},
                        {
                            "name": CODEX_PROFILE_NAME,
                            "selected": True,
                            "devices": [],
                            "migrated": True,
                        },
                        {"name": GAME_PROFILE_NAME, "selected": False, "stale": True},
                    ]
                },
            )

            self.assertTrue(
                configure_path(config_path, state_path, adopt_existing=True)
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            configured = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(state["restore_profile"], "Restore Me")
            self.assertTrue(profile_named(configured, CODEX_PROFILE_NAME)["migrated"])
            self.assertNotIn("stale", profile_named(configured, GAME_PROFILE_NAME))
            with self.assertRaisesRegex(ConfigurationError, "only valid before"):
                configure_path(config_path, state_path, adopt_existing=True)
            self.assertFalse(configure_path(config_path, state_path))

    def test_remove_is_reversible_and_preserves_unrelated_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            original = {
                "global": {"show_in_menu_bar": False},
                "profiles": [
                    {
                        "name": "Default",
                        "selected": True,
                        "devices": [{"identifiers": {"is_keyboard": True}, "ignore": False}],
                        "custom": "original",
                    },
                    {"name": "Work", "selected": False, "custom": "preserve"},
                ],
            }
            write_config(config_path, original)
            self.assertTrue(configure_path(config_path, state_path))

            configured = json.loads(config_path.read_text(encoding="utf-8"))
            profile_named(configured, "Work")["added_after_install"] = 42
            configured["top_level_added_after_install"] = True
            write_config(config_path, configured)

            self.assertTrue(remove_path(config_path, state_path))
            removed = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertFalse(state_path.exists())
            self.assertNotIn(CODEX_PROFILE_NAME, [profile.get("name") for profile in removed["profiles"]])
            self.assertNotIn(GAME_PROFILE_NAME, [profile.get("name") for profile in removed["profiles"]])
            self.assertTrue(profile_named(removed, "Default")["selected"])
            self.assertFalse(profile_named(removed, "Work")["selected"])
            self.assertEqual(profile_named(removed, "Default")["custom"], "original")
            self.assertEqual(profile_named(removed, "Work")["custom"], "preserve")
            self.assertEqual(profile_named(removed, "Work")["added_after_install"], 42)
            self.assertTrue(removed["top_level_added_after_install"])

    def test_two_phase_remove_keeps_state_until_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            write_config(
                config_path,
                {"profiles": [{"name": "Default", "selected": True}]},
            )
            configure_path(config_path, state_path)

            self.assertTrue(prepare_remove_path(config_path, state_path))

            prepared = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(prepared["cleanup"]["phase"], CLEANUP_PREPARED)
            self.assertEqual(
                set(prepared["cleanup"]["profile_digests"]),
                set(MANAGED_PROFILE_NAMES),
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["profiles"], [{"name": "Default", "selected": True}])
            self.assertFalse(check_remove_path(config_path, state_path))
            self.assertTrue(check_finalize_remove_path(config_path, state_path))
            self.assertFalse(prepare_remove_path(config_path, state_path))

            self.assertTrue(finalize_remove_path(config_path, state_path))
            self.assertFalse(state_path.exists())
            self.assertFalse(finalize_remove_path(config_path, state_path))

    def test_prepare_remove_resumes_after_each_internal_write_boundary(self) -> None:
        for failure_call in (2, 3):
            with self.subTest(failure_call=failure_call), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = root / "karabiner.json"
                state_path = root / "ownership.json"
                write_config(
                    config_path,
                    {"profiles": [{"name": "Default", "selected": True}]},
                )
                configure_path(config_path, state_path)
                real_replace = profile_helper._replace_if_unchanged
                calls = 0

                def fail_selected_replace(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == failure_call:
                        raise OSError(f"injected write failure {failure_call}")
                    return real_replace(*args, **kwargs)

                with mock.patch.object(
                    profile_helper,
                    "_replace_if_unchanged",
                    side_effect=fail_selected_replace,
                ):
                    with self.assertRaisesRegex(OSError, "injected write failure"):
                        prepare_remove_path(config_path, state_path)

                transitional = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    transitional["cleanup"]["phase"],
                    CLEANUP_REMOVING,
                )
                self.assertEqual(
                    prepare_remove_path(config_path, state_path),
                    failure_call == 2,
                )
                prepared = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(prepared["cleanup"]["phase"], CLEANUP_PREPARED)
                self.assertTrue(finalize_remove_path(config_path, state_path))

    def test_prepared_cleanup_refuses_readded_managed_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            write_config(
                config_path,
                {"profiles": [{"name": "Default", "selected": True}]},
            )
            configure_path(config_path, state_path)
            prepare_remove_path(config_path, state_path)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["profiles"].append(
                {"name": CODEX_PROFILE_NAME, "selected": False, "owner": "not-us"}
            )
            write_config(config_path, config)
            original_config = config_path.read_bytes()
            original_state = state_path.read_bytes()

            for operation in (
                check_remove_path,
                prepare_remove_path,
                check_finalize_remove_path,
                finalize_remove_path,
            ):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaisesRegex(ConfigurationError, "re-added"):
                        operation(config_path, state_path)
                    self.assertEqual(config_path.read_bytes(), original_config)
                    self.assertEqual(state_path.read_bytes(), original_state)

    def test_removing_cleanup_refuses_changed_managed_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            write_config(
                config_path,
                {"profiles": [{"name": "Default", "selected": True}]},
            )
            configure_path(config_path, state_path)
            real_replace = profile_helper._replace_if_unchanged
            calls = 0

            def fail_config_replace(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected config failure")
                return real_replace(*args, **kwargs)

            with mock.patch.object(
                profile_helper,
                "_replace_if_unchanged",
                side_effect=fail_config_replace,
            ):
                with self.assertRaisesRegex(OSError, "injected config failure"):
                    prepare_remove_path(config_path, state_path)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["cleanup"]["phase"], CLEANUP_REMOVING)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            profile_named(config, CODEX_PROFILE_NAME)["changed_during_cleanup"] = True
            write_config(config_path, config)

            with self.assertRaisesRegex(ConfigurationError, "changed or re-added"):
                prepare_remove_path(config_path, state_path)

    def test_finalize_failure_leaves_prepared_state_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            write_config(
                config_path,
                {"profiles": [{"name": "Default", "selected": True}]},
            )
            configure_path(config_path, state_path)
            prepare_remove_path(config_path, state_path)

            with mock.patch.object(
                profile_helper,
                "_unlink_if_unchanged",
                side_effect=OSError("injected finalize failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected finalize failure"):
                    finalize_remove_path(config_path, state_path)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["cleanup"]["phase"], CLEANUP_PREPARED)
            self.assertTrue(finalize_remove_path(config_path, state_path))
            self.assertFalse(state_path.exists())

    def test_remove_falls_back_to_first_remaining_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            write_config(
                config_path,
                {
                    "profiles": [
                        {"name": "Former Default", "selected": True},
                        {"name": "Fallback", "selected": False},
                    ]
                },
            )
            configure_path(config_path, state_path)
            configured = json.loads(config_path.read_text(encoding="utf-8"))
            configured["profiles"] = [
                profile
                for profile in configured["profiles"]
                if profile.get("name") != "Former Default"
            ]
            write_config(config_path, configured)

            remove_path(config_path, state_path)
            removed = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(profile_named(removed, "Fallback")["selected"])

    def test_invalid_state_is_required_before_owned_profiles_are_updated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            state_path = root / "ownership.json"
            write_config(config_path, {"profiles": [{"name": "Default", "selected": True}]})
            configure_path(config_path, state_path)
            original = config_path.read_bytes()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["version"] = 999
            write_config(state_path, state)
            state_path.chmod(0o600)

            with self.assertRaisesRegex(ConfigurationError, "unsupported version"):
                configure_path(config_path, state_path)
            self.assertEqual(config_path.read_bytes(), original)

    def test_symlink_ownership_state_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "karabiner.json"
            real_state = root / "real-state.json"
            state_path = root / "ownership.json"
            write_config(config_path, {"profiles": [{"name": "Default", "selected": True}]})
            write_config(
                real_state,
                {
                    "version": STATE_VERSION,
                    "managed_profiles": list(MANAGED_PROFILE_NAMES),
                    "restore_profile": "Default",
                },
            )
            real_state.chmod(0o600)
            state_path.symlink_to(real_state)
            original = config_path.read_bytes()

            with self.assertRaisesRegex(ConfigurationError, "non-symlink"):
                configure_path(config_path, state_path)
            self.assertEqual(config_path.read_bytes(), original)

    def test_cli_accepts_explicit_config_and_state_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "test-config.json"
            state_path = root / "test-state.json"
            rules_path = root / "codex-gamepad.json"
            write_config(config_path, {"profiles": []})
            write_rules_file(rules_path)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config_path),
                    "--state",
                    str(state_path),
                    "--rules-file",
                    str(rules_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            configured = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(profile_named(configured, CODEX_PROFILE_NAME)["selected"])
            self.assertTrue(state_path.is_file())

            remove_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config_path),
                    "--state",
                    str(state_path),
                    "--remove",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(remove_result.returncode, 0, remove_result.stderr)
            self.assertFalse(state_path.exists())
            removed = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(removed["profiles"], [])


if __name__ == "__main__":
    unittest.main()
