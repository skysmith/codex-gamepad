#!/usr/bin/env python3
"""Create or remove the Karabiner profiles used for controller handoff."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


CODEX_PROFILE_NAME = "Codex Controller"
GAME_PROFILE_NAME = "Game Mode"
MANAGED_PROFILE_NAMES = (CODEX_PROFILE_NAME, GAME_PROFILE_NAME)
STATE_VERSION = 1
CLEANUP_REMOVING = "removing"
CLEANUP_PREPARED = "profiles_removed"
DEVICE_IDENTIFIERS = {
    "is_game_pad": True,
    "product_id": 12315,
    "vendor_id": 11720,
}
MOUSE_DISCARD_KEYS = (
    "mouse_discard_horizontal_wheel",
    "mouse_discard_vertical_wheel",
    "mouse_discard_x",
    "mouse_discard_y",
)
NAVIGATION_RULE_DESCRIPTION = "Codex Gamepad — navigation (8BitDo Ultimate 2C)"
RECEIVER_RULE_DESCRIPTION = (
    "Codex Gamepad — speak/stop (Karabiner 16 receiver)"
)
SHELL_FALLBACK_RULE_DESCRIPTION = (
    "Codex Gamepad — speak/stop (legacy shell fallback; do not enable with receiver rule)"
)
LEGACY_RECEIVER_RULE_DESCRIPTION = (
    "Codex Gamepad — receiver actions (dictation + Kokoro; Karabiner 16)"
)
LEGACY_KOKORO_RECEIVER_RULE_DESCRIPTION = (
    "Codex Gamepad — Kokoro speak/stop (Karabiner 16 receiver)"
)
LEGACY_KOKORO_SHELL_FALLBACK_RULE_DESCRIPTION = (
    "Codex Gamepad — Kokoro speak/stop (legacy shell fallback; do not enable with receiver rule)"
)
MANAGED_RULE_DESCRIPTIONS = (
    NAVIGATION_RULE_DESCRIPTION,
    RECEIVER_RULE_DESCRIPTION,
    SHELL_FALLBACK_RULE_DESCRIPTION,
)


class ConfigurationError(ValueError):
    """Raised when changing the Karabiner configuration would be unsafe."""


class AtomicWriteError(OSError):
    """An atomic config write failure, including whether replacement occurred."""

    def __init__(self, message: str, *, replaced: bool) -> None:
        super().__init__(message)
        self.replaced = replaced


FileMetadata = Tuple[int, int, int, int, int]


def default_state_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Codex Gamepad"
        / "karabiner-profile-state.json"
    )


def _metadata(value: os.stat_result) -> FileMetadata:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        stat.S_IMODE(value.st_mode),
    )


def _read_regular_file(path: Path, *, label: str) -> Tuple[bytes, os.stat_result]:
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise ConfigurationError(f"{label} does not exist: {path}") from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ConfigurationError(f"{label} is not a regular non-symlink file: {path}")
    contents = path.read_bytes()
    try:
        after = path.lstat()
    except FileNotFoundError as error:
        raise ConfigurationError(f"{label} changed while it was read: {path}") from error
    if _metadata(before) != _metadata(after):
        raise ConfigurationError(f"{label} changed while it was read: {path}")
    return contents, after


def _parse_json_object(contents: bytes, *, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"{label} is not valid UTF-8 JSON.") from error
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a JSON object.")
    return value


def _serialized(value: Dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=4) + "\n").encode("utf-8")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_if_unchanged(
    path: Path,
    output: bytes,
    original: bytes,
    metadata: os.stat_result,
) -> bool:
    if output == original:
        try:
            current = path.lstat()
        except FileNotFoundError as error:
            raise ConfigurationError("Karabiner config changed while profiles were prepared.") from error
        if _metadata(current) != _metadata(metadata):
            raise ConfigurationError("Karabiner config changed while profiles were prepared.")
        return False
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    replaced = False
    try:
        os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())

        try:
            current = path.lstat()
        except FileNotFoundError as error:
            raise ConfigurationError("Karabiner config changed while profiles were prepared.") from error
        if _metadata(current) != _metadata(metadata):
            raise ConfigurationError("Karabiner config changed while profiles were prepared.")
        os.replace(str(temporary), str(path))
        replaced = True
        _fsync_directory(path.parent)
    except Exception as error:
        raise AtomicWriteError(str(error), replaced=replaced) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return True


def _create_private_state(path: Path, state: Dict[str, Any]) -> Tuple[bytes, os.stat_result]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.exists():
        raise ConfigurationError(f"Ownership state already exists: {path}")

    output = _serialized(state)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(str(temporary), str(path))
        except FileExistsError as error:
            raise ConfigurationError(f"Ownership state appeared concurrently: {path}") from error
        linked = True
        _fsync_directory(path.parent)
        contents, metadata = _read_regular_file(path, label="Ownership state")
        if stat.S_IMODE(metadata.st_mode) != 0o600 or contents != output:
            raise ConfigurationError("Ownership state could not be created safely.")
        return contents, metadata
    except Exception:
        if linked:
            path.unlink(missing_ok=True)
            _fsync_directory(path.parent)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _unlink_if_unchanged(path: Path, contents: bytes, metadata: os.stat_result) -> None:
    current_contents, current_metadata = _read_regular_file(path, label="Ownership state")
    if current_contents != contents or _metadata(current_metadata) != _metadata(metadata):
        raise ConfigurationError("Ownership state changed while profiles were updated.")
    path.unlink()
    _fsync_directory(path.parent)


def _state_value(restore_profile: Optional[str]) -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "managed_profiles": list(MANAGED_PROFILE_NAMES),
        "restore_profile": restore_profile,
    }


def _validate_state(value: Dict[str, Any]) -> Optional[str]:
    if value.get("version") != STATE_VERSION:
        raise ConfigurationError("Ownership state has an unsupported version.")
    managed = value.get("managed_profiles")
    if managed != list(MANAGED_PROFILE_NAMES):
        raise ConfigurationError("Ownership state does not name the expected managed profiles.")
    restore = value.get("restore_profile")
    if restore is not None and not isinstance(restore, str):
        raise ConfigurationError("Ownership state has an invalid restore profile.")
    if restore in MANAGED_PROFILE_NAMES:
        raise ConfigurationError("Ownership state cannot restore to a managed profile.")
    cleanup = value.get("cleanup")
    if cleanup is not None:
        if not isinstance(cleanup, dict) or set(cleanup) != {"phase", "profile_digests"}:
            raise ConfigurationError("Ownership state has an invalid cleanup transition.")
        if cleanup.get("phase") not in (CLEANUP_REMOVING, CLEANUP_PREPARED):
            raise ConfigurationError("Ownership state has an invalid cleanup phase.")
        digests = cleanup.get("profile_digests")
        if not isinstance(digests, dict) or not set(digests).issubset(MANAGED_PROFILE_NAMES):
            raise ConfigurationError("Ownership state has invalid managed-profile fingerprints.")
        if any(
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in digests.values()
        ):
            raise ConfigurationError("Ownership state has invalid managed-profile fingerprints.")
    return restore


def _load_state(path: Path) -> Tuple[Dict[str, Any], bytes, os.stat_result]:
    contents, metadata = _read_regular_file(path, label="Ownership state")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ConfigurationError("Ownership state permissions must be mode 0600.")
    value = _parse_json_object(contents, label="Ownership state")
    _validate_state(value)
    return value, contents, metadata


def _cleanup_details(state: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, str]]:
    cleanup = state.get("cleanup")
    if cleanup is None:
        return None, {}
    return cleanup["phase"], cleanup["profile_digests"]


def _profile_digest(profile: Dict[str, Any]) -> str:
    encoded = json.dumps(
        profile,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _profiles(config: Dict[str, Any]) -> List[Any]:
    profiles = config.get("profiles")
    if profiles is None:
        profiles = []
        config["profiles"] = profiles
    if not isinstance(profiles, list):
        raise ConfigurationError("Karabiner config profiles must be a list.")
    return profiles


def _load_managed_rules(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load the refreshable rules from a rendered Karabiner asset."""

    contents, _ = _read_regular_file(path, label="Karabiner rules file")
    asset = _parse_json_object(contents, label="Karabiner rules file")
    rules = asset.get("rules")
    if not isinstance(rules, list):
        raise ConfigurationError("Karabiner rules file rules must be a list.")

    extracted: Dict[str, Dict[str, Any]] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            raise ConfigurationError("Karabiner rules file contains a non-object rule.")
        description = rule.get("description")
        if not isinstance(description, str):
            raise ConfigurationError(
                "Karabiner rules file contains a rule without a string description."
            )
        if description not in MANAGED_RULE_DESCRIPTIONS:
            continue
        if description in extracted:
            raise ConfigurationError(
                f"Karabiner rules file contains duplicate {description!r} rules."
            )
        manipulators = rule.get("manipulators")
        if (
            not isinstance(manipulators, list)
            or not manipulators
            or any(not isinstance(manipulator, dict) for manipulator in manipulators)
        ):
            raise ConfigurationError(
                f"Karabiner rule {description!r} must contain a non-empty manipulator list."
            )
        extracted[description] = copy.deepcopy(rule)

    missing = [
        description
        for description in MANAGED_RULE_DESCRIPTIONS
        if description not in extracted
    ]
    if missing:
        raise ConfigurationError(
            f"Karabiner rules file is missing required rule {missing[0]!r}."
        )
    return extracted


def _refresh_enabled_managed_rules(
    profile: Dict[str, Any],
    managed_rules: Dict[str, Dict[str, Any]],
) -> None:
    """Refresh already-enabled managed rules without enabling absent rules."""

    complex_modifications = profile.get("complex_modifications")
    if complex_modifications is None:
        return
    if not isinstance(complex_modifications, dict):
        raise ConfigurationError(
            f"Profile {profile.get('name')!r} has invalid complex modifications."
        )
    rules = complex_modifications.get("rules")
    if rules is None:
        return
    if not isinstance(rules, list):
        raise ConfigurationError(
            f"Profile {profile.get('name')!r} has a non-list complex-modification rules value."
        )
    if any(not isinstance(rule, dict) for rule in rules):
        raise ConfigurationError(
            f"Profile {profile.get('name')!r} has a non-object complex-modification rule."
        )

    navigation_indices = [
        index
        for index, rule in enumerate(rules)
        if rule.get("description") == NAVIGATION_RULE_DESCRIPTION
    ]
    if len(navigation_indices) > 1:
        raise ConfigurationError(
            "Codex Controller contains duplicate enabled navigation rules; refusing an ambiguous refresh."
        )
    if navigation_indices:
        rules[navigation_indices[0]] = copy.deepcopy(
            managed_rules[NAVIGATION_RULE_DESCRIPTION]
        )

    receiver_descriptions = {
        LEGACY_RECEIVER_RULE_DESCRIPTION,
        LEGACY_KOKORO_RECEIVER_RULE_DESCRIPTION,
        RECEIVER_RULE_DESCRIPTION,
    }
    receiver_indices = [
        index
        for index, rule in enumerate(rules)
        if isinstance(rule.get("description"), str)
        and rule.get("description") in receiver_descriptions
    ]
    if receiver_indices:
        first_receiver_index = receiver_indices[0]
        refreshed_rules: List[Any] = []
        for index, rule in enumerate(rules):
            if index == first_receiver_index:
                refreshed_rules.append(
                    copy.deepcopy(managed_rules[RECEIVER_RULE_DESCRIPTION])
                )
            elif index not in receiver_indices:
                refreshed_rules.append(rule)
        complex_modifications["rules"] = refreshed_rules

    rules = complex_modifications["rules"]
    fallback_descriptions = {
        LEGACY_KOKORO_SHELL_FALLBACK_RULE_DESCRIPTION,
        SHELL_FALLBACK_RULE_DESCRIPTION,
    }
    fallback_indices = [
        index
        for index, rule in enumerate(rules)
        if rule.get("description") in fallback_descriptions
    ]
    if len(fallback_indices) > 1:
        raise ConfigurationError(
            "Codex Controller contains duplicate enabled shell fallback rules; refusing an ambiguous refresh."
        )
    if fallback_indices:
        rules[fallback_indices[0]] = copy.deepcopy(
            managed_rules[SHELL_FALLBACK_RULE_DESCRIPTION]
        )


def _enable_managed_rules(
    profile: Dict[str, Any],
    managed_rules: Dict[str, Dict[str, Any]],
) -> None:
    """Enable the supported rule pair and remove obsolete Codex Gamepad variants."""
    complex_modifications = profile.setdefault("complex_modifications", {})
    if not isinstance(complex_modifications, dict):
        raise ConfigurationError(
            f"Profile {profile.get('name')!r} has invalid complex modifications."
        )
    rules = complex_modifications.setdefault("rules", [])
    if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
        raise ConfigurationError(
            f"Profile {profile.get('name')!r} has invalid complex-modification rules."
        )
    obsolete_descriptions = {
        *MANAGED_RULE_DESCRIPTIONS,
        LEGACY_RECEIVER_RULE_DESCRIPTION,
        LEGACY_KOKORO_RECEIVER_RULE_DESCRIPTION,
        LEGACY_KOKORO_SHELL_FALLBACK_RULE_DESCRIPTION,
    }
    unrelated = [
        rule for rule in rules if rule.get("description") not in obsolete_descriptions
    ]
    complex_modifications["rules"] = [
        *unrelated,
        copy.deepcopy(managed_rules[NAVIGATION_RULE_DESCRIPTION]),
        copy.deepcopy(managed_rules[RECEIVER_RULE_DESCRIPTION]),
    ]


def _owned_profile_index(profiles: List[Any], name: str) -> Optional[int]:
    matches = [
        index
        for index, profile in enumerate(profiles)
        if isinstance(profile, dict) and profile.get("name") == name
    ]
    if len(matches) > 1:
        raise ConfigurationError(f"Karabiner config contains duplicate {name!r} profiles.")
    return matches[0] if matches else None


def _first_non_managed_name(profiles: List[Any]) -> Optional[str]:
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        name = profile.get("name")
        if isinstance(name, str) and name not in MANAGED_PROFILE_NAMES:
            return name
    return None


def _restore_profile_name(profiles: List[Any], *, adopting: bool) -> Optional[str]:
    selected = next(
        (profile for profile in profiles if isinstance(profile, dict) and profile.get("selected") is True),
        None,
    )
    if selected is not None:
        name = selected.get("name")
        if isinstance(name, str) and name not in MANAGED_PROFILE_NAMES:
            return name
        if name in MANAGED_PROFILE_NAMES and not adopting:
            raise ConfigurationError("A managed profile already exists without ownership state.")
    return _first_non_managed_name(profiles)


def _base_profile(profiles: List[Any]) -> Dict[str, Any]:
    adopted_game = next(
        (
            profile
            for profile in profiles
            if isinstance(profile, dict) and profile.get("name") == GAME_PROFILE_NAME
        ),
        None,
    )
    if adopted_game is not None:
        return copy.deepcopy(adopted_game)
    candidates = [
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile.get("name") not in MANAGED_PROFILE_NAMES
    ]
    selected = next((profile for profile in candidates if profile.get("selected") is True), None)
    if selected is not None:
        return copy.deepcopy(selected)
    if candidates:
        return copy.deepcopy(candidates[0])
    return {}


def _configure_device(profile: Dict[str, Any], *, ignored: bool) -> None:
    devices = profile.get("devices")
    if devices is None:
        devices = []
        profile["devices"] = devices
    if not isinstance(devices, list):
        raise ConfigurationError(f"Profile {profile.get('name')!r} has a non-list devices value.")

    matching_devices = [
        device
        for device in devices
        if isinstance(device, dict) and device.get("identifiers") == DEVICE_IDENTIFIERS
    ]
    if not matching_devices:
        matching_devices = [{"identifiers": copy.deepcopy(DEVICE_IDENTIFIERS)}]
        devices.append(matching_devices[0])

    for device in matching_devices:
        device["ignore"] = ignored
        for key in MOUSE_DISCARD_KEYS:
            device[key] = True


def configure_profiles(
    config: Dict[str, Any],
    managed_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    enable_managed_rules: bool = False,
) -> Dict[str, Any]:
    """Return a configured deep copy; ownership must be checked by ``configure_path``."""

    if not isinstance(config, dict):
        raise ConfigurationError("Karabiner config must be a JSON object.")
    result = copy.deepcopy(config)
    profiles = _profiles(result)
    codex_index = _owned_profile_index(profiles, CODEX_PROFILE_NAME)
    game_index = _owned_profile_index(profiles, GAME_PROFILE_NAME)

    if codex_index is None:
        codex_profile = _base_profile(profiles)
        profiles.append(codex_profile)
    else:
        codex_profile = profiles[codex_index]
        if not isinstance(codex_profile, dict):
            raise ConfigurationError(f"Profile {CODEX_PROFILE_NAME!r} is invalid.")

    codex_profile["name"] = CODEX_PROFILE_NAME
    _configure_device(codex_profile, ignored=False)
    if managed_rules is not None:
        if enable_managed_rules:
            _enable_managed_rules(codex_profile, managed_rules)
        else:
            _refresh_enabled_managed_rules(codex_profile, managed_rules)

    game_profile = copy.deepcopy(codex_profile)
    game_profile["name"] = GAME_PROFILE_NAME
    _configure_device(game_profile, ignored=True)
    if game_index is None:
        profiles.append(game_profile)
    else:
        profiles[game_index] = game_profile

    for profile in profiles:
        if isinstance(profile, dict):
            profile["selected"] = profile.get("name") == CODEX_PROFILE_NAME
    return result


def remove_profiles(config: Dict[str, Any], restore_profile: Optional[str]) -> Dict[str, Any]:
    """Remove managed profiles and restore the recorded or first remaining profile."""

    if not isinstance(config, dict):
        raise ConfigurationError("Karabiner config must be a JSON object.")
    result = copy.deepcopy(config)
    profiles = _profiles(result)
    remaining = [
        profile
        for profile in profiles
        if not (isinstance(profile, dict) and profile.get("name") in MANAGED_PROFILE_NAMES)
    ]
    result["profiles"] = remaining

    selected_profile: Optional[Dict[str, Any]] = None
    if restore_profile is not None:
        selected_profile = next(
            (
                profile
                for profile in remaining
                if isinstance(profile, dict) and profile.get("name") == restore_profile
            ),
            None,
        )
    if selected_profile is None:
        selected_profile = next((profile for profile in remaining if isinstance(profile, dict)), None)
    for profile in remaining:
        if isinstance(profile, dict):
            profile["selected"] = profile is selected_profile
    return result


def _read_config(path: Path) -> Tuple[Dict[str, Any], bytes, os.stat_result]:
    contents, metadata = _read_regular_file(path, label="Karabiner config")
    return _parse_json_object(contents, label="Karabiner config"), contents, metadata


def _state_exists(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"Ownership state is not a regular non-symlink file: {path}")
    return True


def _prepare_configuration(
    path: Path,
    state_path: Path,
    *,
    adopt_existing: bool,
    managed_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    enable_managed_rules: bool = False,
) -> Tuple[Dict[str, Any], bytes, os.stat_result, Optional[Dict[str, Any]]]:
    """Validate ownership and return the prospective configuration and state."""

    config, original, config_metadata = _read_config(path)
    profiles = _profiles(config)
    state_to_create: Optional[Dict[str, Any]] = None

    if _state_exists(state_path):
        if adopt_existing:
            raise ConfigurationError("--adopt-existing is only valid before ownership state exists.")
        state, _, _ = _load_state(state_path)
        phase, _ = _cleanup_details(state)
        if phase is not None:
            raise ConfigurationError(
                "Profile cleanup is in progress; finish uninstall before configuring profiles."
            )
    else:
        collisions = [
            name
            for name in MANAGED_PROFILE_NAMES
            if any(
                isinstance(profile, dict) and profile.get("name") == name
                for profile in profiles
            )
        ]
        if collisions and not adopt_existing:
            raise ConfigurationError(
                f"Profile {collisions[0]!r} already exists; use --adopt-existing to claim it."
            )
        restore = _restore_profile_name(profiles, adopting=adopt_existing)
        state_to_create = _state_value(restore)

    return (
        configure_profiles(
            config,
            managed_rules=managed_rules,
            enable_managed_rules=enable_managed_rules,
        ),
        original,
        config_metadata,
        state_to_create,
    )


def check_configure_path(
    path: Path,
    state_path: Path,
    *,
    adopt_existing: bool = False,
    rules_file: Optional[Path] = None,
    enable_managed_rules: bool = False,
) -> bool:
    """Validate a profile update without changing the config, state, or directories."""

    path = path.expanduser()
    state_path = state_path.expanduser()
    managed_rules = (
        _load_managed_rules(rules_file.expanduser())
        if rules_file is not None
        else None
    )
    configured, original, _, _ = _prepare_configuration(
        path,
        state_path,
        adopt_existing=adopt_existing,
        managed_rules=managed_rules,
        enable_managed_rules=enable_managed_rules,
    )
    return _serialized(configured) != original


def configure_path(
    path: Path,
    state_path: Path,
    *,
    adopt_existing: bool = False,
    rules_file: Optional[Path] = None,
    enable_managed_rules: bool = False,
) -> bool:
    """Configure profiles under validated external ownership state."""

    path = path.expanduser()
    state_path = state_path.expanduser()
    managed_rules = (
        _load_managed_rules(rules_file.expanduser())
        if rules_file is not None
        else None
    )
    created_state: Optional[Tuple[bytes, os.stat_result]] = None
    configured, original, config_metadata, state_to_create = _prepare_configuration(
        path,
        state_path,
        adopt_existing=adopt_existing,
        managed_rules=managed_rules,
        enable_managed_rules=enable_managed_rules,
    )
    if state_to_create is not None:
        created_state = _create_private_state(state_path, state_to_create)
    try:
        return _replace_if_unchanged(
            path,
            _serialized(configured),
            original,
            config_metadata,
        )
    except Exception as error:
        replacement_completed = isinstance(error, AtomicWriteError) and error.replaced
        if created_state is not None and not replacement_completed:
            state_contents, state_metadata = created_state
            _unlink_if_unchanged(state_path, state_contents, state_metadata)
        raise


def _managed_profiles(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    profiles = _profiles(config)
    result: Dict[str, Dict[str, Any]] = {}
    for name in MANAGED_PROFILE_NAMES:
        index = _owned_profile_index(profiles, name)
        if index is not None:
            profile = profiles[index]
            if not isinstance(profile, dict):
                raise ConfigurationError(f"Profile {name!r} is invalid.")
            result[name] = profile
    return result


def _require_expected_cleanup_profiles(
    managed: Dict[str, Dict[str, Any]],
    expected_digests: Dict[str, str],
) -> None:
    if not managed:
        return
    actual_digests = {
        name: _profile_digest(profile)
        for name, profile in managed.items()
    }
    if actual_digests != expected_digests:
        raise ConfigurationError(
            "Managed profiles were changed or re-added after cleanup began; refusing to remove them."
        )


def _require_profiles_absent(config: Dict[str, Any]) -> None:
    if _managed_profiles(config):
        raise ConfigurationError(
            "Managed profiles were re-added after cleanup was prepared; refusing to finalize."
        )


def _replace_state_if_unchanged(
    path: Path,
    state: Dict[str, Any],
    original: bytes,
    metadata: os.stat_result,
) -> Tuple[Dict[str, Any], bytes, os.stat_result]:
    _replace_if_unchanged(
        path,
        _serialized(state),
        original,
        metadata,
    )
    return _load_state(path)


def check_remove_path(path: Path, state_path: Path) -> bool:
    """Validate resumable profile removal without changing config or ownership state."""

    path = path.expanduser()
    state_path = state_path.expanduser()
    if not _state_exists(state_path):
        raise ConfigurationError("Ownership state is missing; refusing to remove profiles.")
    state, _, _ = _load_state(state_path)
    restore = _validate_state(state)
    phase, expected_digests = _cleanup_details(state)
    config, original, _ = _read_config(path)
    managed = _managed_profiles(config)
    if phase == CLEANUP_PREPARED:
        _require_profiles_absent(config)
        return False
    if phase == CLEANUP_REMOVING:
        _require_expected_cleanup_profiles(managed, expected_digests)
    removed = remove_profiles(config, restore)
    return _serialized(removed) != original


def prepare_remove_path(path: Path, state_path: Path) -> bool:
    """Remove owned profiles while retaining state for the manifest commit."""

    path = path.expanduser()
    state_path = state_path.expanduser()
    if not _state_exists(state_path):
        raise ConfigurationError("Ownership state is missing; refusing to remove profiles.")

    state, state_contents, state_metadata = _load_state(state_path)
    restore = _validate_state(state)
    phase, expected_digests = _cleanup_details(state)
    config, original, config_metadata = _read_config(path)
    managed = _managed_profiles(config)

    if phase == CLEANUP_PREPARED:
        _require_profiles_absent(config)
        return False

    if phase is None:
        expected_digests = {
            name: _profile_digest(profile)
            for name, profile in managed.items()
        }
        removing_state = copy.deepcopy(state)
        removing_state["cleanup"] = {
            "phase": CLEANUP_REMOVING,
            "profile_digests": expected_digests,
        }
        state, state_contents, state_metadata = _replace_state_if_unchanged(
            state_path,
            removing_state,
            state_contents,
            state_metadata,
        )
    else:
        _require_expected_cleanup_profiles(managed, expected_digests)

    removed = remove_profiles(config, restore)
    changed = _replace_if_unchanged(
        path,
        _serialized(removed),
        original,
        config_metadata,
    )

    current_config, _, _ = _read_config(path)
    _require_profiles_absent(current_config)
    prepared_state = copy.deepcopy(state)
    prepared_state["cleanup"] = {
        "phase": CLEANUP_PREPARED,
        "profile_digests": expected_digests,
    }
    _replace_state_if_unchanged(
        state_path,
        prepared_state,
        state_contents,
        state_metadata,
    )
    return changed


def check_finalize_remove_path(path: Path, state_path: Path) -> bool:
    """Validate final ownership-state removal after the manifest commit."""

    path = path.expanduser()
    state_path = state_path.expanduser()
    if not _state_exists(state_path):
        return False
    state, _, _ = _load_state(state_path)
    phase, _ = _cleanup_details(state)
    if phase != CLEANUP_PREPARED:
        raise ConfigurationError(
            "Profile cleanup was not prepared before its manifest commit; refusing to finalize."
        )
    config, _, _ = _read_config(path)
    _require_profiles_absent(config)
    return True


def finalize_remove_path(path: Path, state_path: Path) -> bool:
    """Delete prepared ownership state after profiles_expected is committed false."""

    path = path.expanduser()
    state_path = state_path.expanduser()
    if not _state_exists(state_path):
        return False
    state, state_contents, state_metadata = _load_state(state_path)
    phase, _ = _cleanup_details(state)
    if phase != CLEANUP_PREPARED:
        raise ConfigurationError(
            "Profile cleanup was not prepared before its manifest commit; refusing to finalize."
        )
    config, _, _ = _read_config(path)
    _require_profiles_absent(config)
    _unlink_if_unchanged(state_path, state_contents, state_metadata)
    return True


def remove_path(path: Path, state_path: Path) -> bool:
    """Compatibility helper: prepare removal and immediately finalize its state."""

    changed = prepare_remove_path(path, state_path)
    finalize_remove_path(path, state_path)
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".config" / "karabiner" / "karabiner.json",
        help="Karabiner configuration to update",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=default_state_path(),
        help="Private ownership state used to make profile removal reversible",
    )
    parser.add_argument(
        "--rules-file",
        type=Path,
        help="Rendered Codex Gamepad asset used to refresh already-enabled managed rules",
    )
    parser.add_argument(
        "--enable-managed-rules",
        action="store_true",
        help="Enable navigation and receiver rules while removing obsolete variants",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--adopt-existing",
        action="store_true",
        help="Claim existing managed profile names during a one-time migration",
    )
    action.add_argument(
        "--remove",
        action="store_true",
        help="Remove state-owned profiles and restore the previous selection",
    )
    action.add_argument(
        "--prepare-remove",
        action="store_true",
        help="Remove state-owned profiles but retain state for the manifest commit",
    )
    action.add_argument(
        "--finalize-remove",
        action="store_true",
        help="Delete prepared ownership state after the manifest commit",
    )
    action.add_argument(
        "--check",
        action="store_true",
        help="Validate profile ownership and proposed changes without writing",
    )
    action.add_argument(
        "--check-remove",
        action="store_true",
        help="Validate owned-profile removal without writing",
    )
    action.add_argument(
        "--check-finalize-remove",
        action="store_true",
        help="Validate final ownership-state removal without writing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.rules_file is not None and any(
            (
                args.remove,
                args.prepare_remove,
                args.finalize_remove,
                args.check_remove,
                args.check_finalize_remove,
            )
        ):
            raise ConfigurationError(
                "--rules-file is only valid when configuring profiles or using --check."
            )
        if args.enable_managed_rules and args.rules_file is None:
            raise ConfigurationError("--enable-managed-rules requires --rules-file.")
        if args.remove:
            changed = remove_path(args.config, args.state)
            action = "Removed" if changed else "Ownership removed"
        elif args.prepare_remove:
            changed = prepare_remove_path(args.config, args.state)
            action = "Prepared removal" if changed else "Removal already prepared"
        elif args.finalize_remove:
            changed = finalize_remove_path(args.config, args.state)
            action = "Finalized removal" if changed else "Removal already finalized"
        elif args.check_remove:
            changed = check_remove_path(args.config, args.state)
            action = "Would remove" if changed else "Would remove ownership"
        elif args.check_finalize_remove:
            changed = check_finalize_remove_path(args.config, args.state)
            action = "Would finalize removal" if changed else "Removal already finalized"
        elif args.check:
            changed = check_configure_path(
                args.config,
                args.state,
                rules_file=args.rules_file,
                enable_managed_rules=args.enable_managed_rules,
            )
            action = "Would configure" if changed else "Already configured"
        else:
            changed = configure_path(
                args.config,
                args.state,
                adopt_existing=args.adopt_existing,
                rules_file=args.rules_file,
                enable_managed_rules=args.enable_managed_rules,
            )
            action = "Configured" if changed else "Already configured"
    except (ConfigurationError, OSError) as error:
        print(f"Could not configure Codex Gamepad profiles: {error}", file=sys.stderr)
        return 1
    print(f"{action}: {args.config.expanduser()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
