#!/usr/bin/env python3
"""Guard and record Codex Gamepad files installed outside its owned prefix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


MANIFEST_VERSION = 1
MARKER_TEXT = b"codex-gamepad-v1\n"
KNOWN_ARTIFACTS = {"launcher", "uninstaller", "karabiner_rule", "launch_agent"}
REMOVAL_JOURNAL_NAME = ".codex-gamepad-removal.json"


class OwnershipError(ValueError):
    """Raised when an install artifact cannot be changed safely."""


@dataclass(frozen=True)
class InstallArtifact:
    name: str
    path: Path
    kind: str
    source: Path | None = None
    target: str | None = None
    mode: int | None = None


@dataclass(frozen=True)
class AllowedArtifact:
    name: str
    path: Path
    kind: str
    target: str | None = None


@dataclass(frozen=True)
class QuarantinedArtifact:
    artifact: AllowedArtifact
    entry: dict[str, Any]
    path: Path
    directory: Path


def _safe_lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _read_regular(path: Path, *, label: str) -> tuple[bytes, os.stat_result]:
    before = _safe_lstat(path)
    if before is None:
        raise OwnershipError(f"{label} is missing: {path}")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise OwnershipError(f"{label} is not a regular non-symlink file: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise OwnershipError(f"{label} could not be opened safely: {path}") from error
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise OwnershipError(f"{label} changed while it was opened: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        stat.S_IMODE(value.st_mode),
    )
    if identity(opened) != identity(after):
        raise OwnershipError(f"{label} changed while it was read: {path}")
    return b"".join(chunks), after


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _validate_marker(prefix: Path) -> bool:
    marker = prefix / ".codex-gamepad-install"
    metadata = _safe_lstat(marker)
    if metadata is None:
        return False
    try:
        contents, _ = _read_regular(marker, label="Install marker")
    except OwnershipError:
        return False
    return contents == MARKER_TEXT


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if _safe_lstat(path) is None:
        return None
    contents, metadata = _read_regular(path, label="Ownership manifest")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise OwnershipError("Ownership manifest permissions must be mode 0600.")
    try:
        value = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OwnershipError("Ownership manifest is not valid UTF-8 JSON.") from error
    if not isinstance(value, dict) or value.get("version") != MANIFEST_VERSION:
        raise OwnershipError("Ownership manifest has an unsupported version.")
    if not isinstance(value.get("profiles_expected"), bool):
        raise OwnershipError("Ownership manifest has an invalid profile state.")
    _validate_artifact_entries(value.get("artifacts"), label="Ownership manifest")
    return value


def _validate_artifact_entries(value: Any, *, label: str) -> None:
    artifacts = value
    if not isinstance(artifacts, dict) or not set(artifacts).issubset(KNOWN_ARTIFACTS):
        raise OwnershipError(f"{label} has invalid artifacts.")
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict) or artifact.get("name") != name:
            raise OwnershipError(f"{label} has an invalid artifact entry.")
        if artifact.get("kind") not in {"regular", "symlink"}:
            raise OwnershipError(f"{label} has an invalid artifact type.")
        if not isinstance(artifact.get("path"), str) or not artifact["path"].startswith("/"):
            raise OwnershipError(f"{label} has an invalid artifact path.")
        if artifact["kind"] == "regular":
            digest = artifact.get("sha256")
            mode = artifact.get("mode")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise OwnershipError(f"{label} has an invalid artifact digest.")
            if not isinstance(mode, int) or isinstance(mode, bool) or not 0 <= mode <= 0o777:
                raise OwnershipError(f"{label} has an invalid artifact mode.")
        elif not isinstance(artifact.get("target"), str):
            raise OwnershipError(f"{label} has an invalid symlink target.")


def _manifest_entry(artifact: InstallArtifact) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": artifact.name,
        "path": str(artifact.path),
        "kind": artifact.kind,
    }
    if artifact.kind == "regular":
        if artifact.source is None:
            raise OwnershipError(f"Regular artifact {artifact.name!r} has no source.")
        contents, _ = _read_regular(artifact.source, label=f"Source for {artifact.name}")
        entry["sha256"] = _sha256(contents)
        entry["mode"] = artifact.mode
    else:
        entry["target"] = artifact.target
    return entry


def _current_matches_entry(path: Path, entry: dict[str, Any]) -> bool:
    metadata = _safe_lstat(path)
    if metadata is None:
        return False
    if entry["kind"] == "symlink":
        return stat.S_ISLNK(metadata.st_mode) and os.readlink(path) == entry["target"]
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return False
    try:
        contents, metadata = _read_regular(path, label=f"Installed artifact {entry['name']}")
    except OwnershipError:
        return False
    return (
        _sha256(contents) == entry["sha256"]
        and stat.S_IMODE(metadata.st_mode) == entry["mode"]
    )


def _is_legacy_launcher(contents: bytes, *, prefix: Path) -> bool:
    """Recognize only the two exact generated launcher layouts used pre-manifest."""

    try:
        lines = contents.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return False
    old_tail = [
        'PYTHONPATH="$APP_PATH/src${PYTHONPATH:+:$PYTHONPATH}"',
        "export PYTHONPATH",
        'exec "$PYTHON_PATH" -m codex_gamepad "$@"',
    ]
    new_tail = [
        'PYTHONPATH="$APP_PATH/src${PYTHONPATH:+:$PYTHONPATH}"',
        "PYTHONDONTWRITEBYTECODE=1",
        "export PYTHONPATH PYTHONDONTWRITEBYTECODE",
        'exec "$PYTHON_PATH" -m codex_gamepad "$@"',
    ]
    if len(lines) < 7 or lines[0:2] != ["#!/bin/sh", ""]:
        return False
    try:
        app_assignment = shlex.split(lines[2], posix=True)
        python_assignment = shlex.split(lines[3], posix=True)
    except ValueError:
        return False
    if len(app_assignment) != 1 or len(python_assignment) != 1:
        return False
    app_key, separator, app_value = app_assignment[0].partition("=")
    python_key, python_separator, python_value = python_assignment[0].partition("=")
    return (
        app_key == "APP_PATH"
        and separator == "="
        and Path(app_value) == prefix
        and python_key == "PYTHON_PATH"
        and python_separator == "="
        and python_value.startswith("/")
        and lines[4:] in (old_tail, new_tail)
    )


def _legacy_matches(artifact: InstallArtifact, candidate: dict[str, Any], prefix: Path) -> bool:
    if _current_matches_entry(artifact.path, candidate):
        return True
    if artifact.name != "launcher" or artifact.kind != "regular":
        return False
    try:
        contents, _ = _read_regular(artifact.path, label="Legacy launcher")
    except OwnershipError:
        return False
    return _is_legacy_launcher(contents, prefix=prefix)


def _validate_install(
    prefix: Path,
    manifest_path: Path,
    artifacts: Sequence[InstallArtifact],
    *,
    profiles_expected: bool,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
    names = [artifact.name for artifact in artifacts]
    paths = [artifact.path for artifact in artifacts]
    if len(names) != len(set(names)) or len(paths) != len(set(paths)):
        raise OwnershipError("Install artifact names and paths must be unique.")
    if not set(names).issubset(KNOWN_ARTIFACTS):
        raise OwnershipError("Install plan contains an unknown artifact.")
    candidates = {artifact.name: _manifest_entry(artifact) for artifact in artifacts}
    manifest = _load_manifest(manifest_path)
    if manifest is not None:
        if (
            manifest["profiles_expected"] != profiles_expected
            and (manifest["profiles_expected"] or manifest["artifacts"])
        ):
            raise OwnershipError(
                "The existing install has a different Karabiner profile mode; uninstall first."
            )
        recorded = manifest["artifacts"]
        if not set(recorded).issubset(set(candidates)):
            raise OwnershipError(
                "The existing install owns artifacts omitted by this install plan; uninstall first."
            )
        for artifact in artifacts:
            current = _safe_lstat(artifact.path)
            previous = recorded.get(artifact.name)
            if previous is not None:
                if previous.get("path") != str(artifact.path) or previous.get("kind") != artifact.kind:
                    raise OwnershipError(f"Ownership changed for {artifact.path}; refusing upgrade.")
                if current is not None and not (
                    _current_matches_entry(artifact.path, previous)
                    or _current_matches_entry(artifact.path, candidates[artifact.name])
                ):
                    raise OwnershipError(f"Owned artifact changed: {artifact.path}")
                if current is None:
                    raise OwnershipError(f"Owned artifact is missing: {artifact.path}")
            elif current is not None:
                raise OwnershipError(f"Refusing unowned external artifact: {artifact.path}")
        return manifest, candidates

    legacy = _validate_marker(prefix)
    for artifact in artifacts:
        if _safe_lstat(artifact.path) is None:
            continue
        if not legacy or not _legacy_matches(artifact, candidates[artifact.name], prefix):
            raise OwnershipError(f"Refusing unowned external artifact: {artifact.path}")
    return None, candidates


def _validate_parent_safe(path: Path, home: Path) -> None:
    if not path.is_absolute() or not home.is_absolute():
        raise OwnershipError("External artifact paths and HOME must be absolute.")
    try:
        physical_home = home.resolve(strict=True)
        physical_parent = path.parent.resolve(strict=False)
        physical_parent.relative_to(physical_home)
    except (OSError, RuntimeError, ValueError) as error:
        raise OwnershipError(f"External artifact is outside the home directory: {path}") from error

    # Reject a parent that traverses a symlink outside HOME even if a later
    # symlink happens to point back in. Existing in-HOME directory symlinks are
    # allowed because their physical targets remain inside the same HOME. Walk
    # from the filesystem root so a canonical path still works when HOME uses a
    # platform alias such as macOS /var -> /private/var.
    current = Path(path.anchor)
    inside_home = False
    for component in path.parent.parts[1:]:
        current /= component
        try:
            physical_current = current.resolve(strict=False)
            physical_current.relative_to(physical_home)
        except (OSError, RuntimeError, ValueError) as error:
            if inside_home:
                raise OwnershipError(
                    f"External artifact parent contains an unsafe symlink: {path}"
                ) from error
            continue
        inside_home = True
        metadata = _safe_lstat(current)
        if metadata is None or not stat.S_ISLNK(metadata.st_mode):
            continue
        try:
            current.resolve(strict=True).relative_to(physical_home)
        except (OSError, RuntimeError, ValueError) as error:
            raise OwnershipError(
                f"External artifact parent contains an unsafe symlink: {path}"
            ) from error

    existing_parent = physical_parent
    while not existing_parent.exists() and existing_parent != physical_home:
        existing_parent = existing_parent.parent
    if not existing_parent.is_dir():
        raise OwnershipError(f"External artifact parent is not a directory: {path}")


def _validate_artifact_parents(artifacts: Sequence[InstallArtifact], home: Path) -> None:
    for artifact in artifacts:
        _validate_parent_safe(artifact.path, home)


def _create_parent(path: Path, home: Path) -> None:
    _validate_parent_safe(path, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_parent_safe(path, home)


def _atomic_regular(path: Path, contents: bytes, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _atomic_symlink(path: Path, target: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        temporary.symlink_to(target)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_manifest(path: Path, value: dict[str, Any]) -> None:
    if _safe_lstat(path) is not None:
        _load_manifest(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_regular(path, output, 0o600)


def install_artifacts(
    prefix: Path,
    manifest_path: Path,
    artifacts: Sequence[InstallArtifact],
    *,
    profiles_expected: bool,
    home: Path,
) -> None:
    _validate_artifact_parents(artifacts, home)
    _, candidates = _validate_install(
        prefix,
        manifest_path,
        artifacts,
        profiles_expected=profiles_expected,
    )
    prepared: dict[str, bytes] = {}
    for artifact in artifacts:
        _create_parent(artifact.path, home)
        if artifact.kind == "regular":
            assert artifact.source is not None
            prepared[artifact.name], _ = _read_regular(
                artifact.source, label=f"Source for {artifact.name}"
            )
    # Revalidate after all parent creation and source reads, immediately before writes.
    # Bind the manifest to the prepared bytes rather than to a stale first read.
    _, candidates = _validate_install(
        prefix,
        manifest_path,
        artifacts,
        profiles_expected=profiles_expected,
    )
    for artifact in artifacts:
        if artifact.kind == "regular" and _sha256(prepared[artifact.name]) != candidates[
            artifact.name
        ]["sha256"]:
            raise OwnershipError(f"Source changed while preparing {artifact.name!r}.")
    for artifact in artifacts:
        if artifact.kind == "regular":
            assert artifact.mode is not None
            _atomic_regular(artifact.path, prepared[artifact.name], artifact.mode)
        else:
            assert artifact.target is not None
            _atomic_symlink(artifact.path, artifact.target)
    manifest = {
        "version": MANIFEST_VERSION,
        "profiles_expected": profiles_expected,
        "artifacts": candidates,
    }
    _write_manifest(manifest_path, manifest)


def _parse_allowed(args: argparse.Namespace) -> dict[str, AllowedArtifact]:
    artifacts: list[AllowedArtifact] = []
    for name, raw_path in args.allow_regular or []:
        artifacts.append(AllowedArtifact(name, Path(raw_path), "regular"))
    for name, raw_path, target in args.allow_symlink or []:
        artifacts.append(AllowedArtifact(name, Path(raw_path), "symlink", target=target))
    result = {artifact.name: artifact for artifact in artifacts}
    if len(result) != len(artifacts) or not set(result).issubset(KNOWN_ARTIFACTS):
        raise OwnershipError("Allowed artifact names must be unique and recognized.")
    return result


def _removal_journal_path(manifest_path: Path) -> Path:
    return manifest_path.with_name(REMOVAL_JOURNAL_NAME)


def _removal_journal_value(
    manifest_path: Path,
    manifest: dict[str, Any],
    quarantined: Sequence[QuarantinedArtifact],
) -> dict[str, Any]:
    return {
        "version": MANIFEST_VERSION,
        "manifest": str(manifest_path),
        "artifacts": manifest["artifacts"],
        "quarantines": [
            {
                "name": staged.artifact.name,
                "original": str(staged.artifact.path),
                "path": str(staged.path),
                "directory": str(staged.directory),
            }
            for staged in quarantined
        ],
    }


def _write_removal_journal(
    manifest_path: Path,
    manifest: dict[str, Any],
    quarantined: Sequence[QuarantinedArtifact],
) -> bytes:
    path = _removal_journal_path(manifest_path)
    if _safe_lstat(path) is not None:
        raise OwnershipError(
            f"A pending removal journal must be recovered before uninstall: {path}"
        )
    output = (
        json.dumps(
            _removal_journal_value(manifest_path, manifest, quarantined),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_regular(path, output, 0o600)
    contents, metadata = _read_regular(path, label="Removal journal")
    if contents != output or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise OwnershipError("Removal journal changed while it was created.")
    return output


def _load_removal_journal(
    manifest_path: Path,
    allowed: dict[str, AllowedArtifact],
) -> tuple[dict[str, Any], list[QuarantinedArtifact], bytes] | None:
    path = _removal_journal_path(manifest_path)
    if _safe_lstat(path) is None:
        return None
    contents, metadata = _read_regular(path, label="Removal journal")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise OwnershipError("Removal journal permissions must be mode 0600.")
    try:
        value = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OwnershipError("Removal journal is not valid UTF-8 JSON.") from error
    if (
        not isinstance(value, dict)
        or value.get("version") != MANIFEST_VERSION
        or value.get("manifest") != str(manifest_path)
    ):
        raise OwnershipError("Removal journal has an unsupported or invalid header.")
    artifacts = value.get("artifacts")
    _validate_artifact_entries(artifacts, label="Removal journal")
    raw_quarantines = value.get("quarantines")
    if not isinstance(raw_quarantines, list) or len(raw_quarantines) != len(artifacts):
        raise OwnershipError("Removal journal has invalid quarantine records.")

    quarantined: list[QuarantinedArtifact] = []
    seen_names: set[str] = set()
    seen_paths: set[Path] = set()
    for raw in raw_quarantines:
        if not isinstance(raw, dict):
            raise OwnershipError("Removal journal has an invalid quarantine record.")
        name = raw.get("name")
        expected = allowed.get(name) if isinstance(name, str) else None
        entry = artifacts.get(name) if isinstance(name, str) else None
        if expected is None or entry is None or name in seen_names:
            raise OwnershipError("Removal journal does not match the expected install paths.")
        if (
            entry["path"] != str(expected.path)
            or entry["kind"] != expected.kind
            or (expected.kind == "symlink" and entry["target"] != expected.target)
            or raw.get("original") != str(expected.path)
            or not isinstance(raw.get("path"), str)
            or not isinstance(raw.get("directory"), str)
        ):
            raise OwnershipError("Removal journal does not match the expected install paths.")
        path = Path(raw["path"])
        directory = Path(raw["directory"])
        if (
            not path.is_absolute()
            or not directory.is_absolute()
            or directory.parent != expected.path.parent
            or not directory.name.startswith(f".{expected.path.name}.remove.")
            or path != directory / expected.path.name
            or path in seen_paths
        ):
            raise OwnershipError("Removal journal has an unsafe quarantine path.")
        directory_metadata = _safe_lstat(directory)
        if directory_metadata is not None and (
            stat.S_ISLNK(directory_metadata.st_mode)
            or not stat.S_ISDIR(directory_metadata.st_mode)
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
        ):
            raise OwnershipError("Removal journal has an unsafe quarantine directory.")
        seen_names.add(name)
        seen_paths.add(path)
        quarantined.append(
            QuarantinedArtifact(expected, entry, path=path, directory=directory)
        )
    if seen_names != set(artifacts):
        raise OwnershipError("Removal journal is missing quarantine records.")
    return value, quarantined, contents


def _remove_removal_journal(manifest_path: Path, expected_contents: bytes) -> None:
    path = _removal_journal_path(manifest_path)
    contents, metadata = _read_regular(path, label="Removal journal")
    if contents != expected_contents or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise OwnershipError("Removal journal changed before it could be cleared.")
    path.unlink()


def _recover_pending_removal(
    manifest_path: Path,
    allowed: dict[str, AllowedArtifact],
) -> None:
    loaded = _load_removal_journal(manifest_path, allowed)
    if loaded is None:
        return
    journal, quarantined, journal_contents = loaded
    manifest = _load_manifest(manifest_path)
    if manifest is None:
        raise OwnershipError("Removal journal exists but the ownership manifest is missing.")

    if manifest["artifacts"] == journal["artifacts"]:
        errors = _rollback_quarantined(quarantined)
        errors.extend(_remove_empty_quarantine_directories(quarantined))
        if errors:
            raise OwnershipError(
                "Pending removal could not be rolled back; recovery data: "
                + ", ".join(errors)
            )
    elif not manifest["artifacts"]:
        errors = _finalize_quarantined(quarantined)
        if errors:
            raise OwnershipError(
                "Committed removal quarantine could not be cleared; recovery data: "
                + ", ".join(errors)
            )
    else:
        raise OwnershipError("Removal journal and ownership manifest disagree.")
    _remove_removal_journal(manifest_path, journal_contents)


def _validated_installed_manifest(
    manifest_path: Path,
    allowed: dict[str, AllowedArtifact],
) -> dict[str, Any]:
    _recover_pending_removal(manifest_path, allowed)
    manifest = _load_manifest(manifest_path)
    if manifest is None:
        raise OwnershipError(
            "Ownership manifest is missing; rerun the source installer once to migrate this pre-release."
        )
    for name, entry in manifest["artifacts"].items():
        expected = allowed.get(name)
        if (
            expected is None
            or entry["path"] != str(expected.path)
            or entry["kind"] != expected.kind
            or (expected.kind == "symlink" and entry["target"] != expected.target)
        ):
            raise OwnershipError("Ownership manifest does not match the expected install paths.")
        if not _current_matches_entry(expected.path, entry):
            raise OwnershipError(f"Owned artifact is missing or changed: {expected.path}")
    return manifest


def remove_owned(
    manifest_path: Path,
    allowed: dict[str, AllowedArtifact],
) -> None:
    manifest = _validated_installed_manifest(manifest_path, allowed)
    if not manifest["artifacts"]:
        return
    quarantined: list[QuarantinedArtifact] = []
    journal_contents: bytes | None = None
    try:
        for name, entry in manifest["artifacts"].items():
            artifact = allowed[name]
            if not _current_matches_entry(artifact.path, entry):
                raise OwnershipError(f"Owned artifact changed during uninstall: {artifact.path}")
            directory = Path(
                tempfile.mkdtemp(
                    dir=artifact.path.parent,
                    prefix=f".{artifact.path.name}.remove.",
                )
            )
            staged = QuarantinedArtifact(
                artifact=artifact,
                entry=entry,
                path=directory / artifact.path.name,
                directory=directory,
            )
            quarantined.append(staged)

        # Persist every recovery location before moving the first external
        # artifact. A later invocation can roll back an interrupted staging
        # phase or finish cleanup after the manifest commit.
        journal_contents = _write_removal_journal(
            manifest_path, manifest, quarantined
        )
        for staged in quarantined:
            artifact = staged.artifact
            entry = staged.entry
            if not _current_matches_entry(artifact.path, entry):
                raise OwnershipError(f"Owned artifact changed during uninstall: {artifact.path}")
            _move_to_quarantine(artifact.path, staged.path)
            if not _current_matches_entry(staged.path, entry):
                raise OwnershipError(
                    f"Owned artifact changed while it was quarantined: {artifact.path}"
                )

        # Commit ownership only after every external object has been staged and
        # verified. A failed manifest write is still rollback-safe.
        updated_manifest = dict(manifest)
        updated_manifest["artifacts"] = {}
        _write_manifest(manifest_path, updated_manifest)
    except Exception as error:
        rollback_errors = _rollback_quarantined(quarantined)
        rollback_errors.extend(_remove_empty_quarantine_directories(quarantined))
        if not rollback_errors and journal_contents is not None:
            try:
                _remove_removal_journal(manifest_path, journal_contents)
            except (OSError, OwnershipError) as journal_error:
                rollback_errors.append(
                    f"{_removal_journal_path(manifest_path)} ({journal_error})"
                )
        if rollback_errors:
            locations = ", ".join(rollback_errors)
            raise OwnershipError(
                f"Removal failed and automatic rollback was incomplete; recovery data: {locations}"
            ) from error
        raise

    cleanup_errors = _finalize_quarantined(quarantined)
    if cleanup_errors:
        raise OwnershipError(
            "Owned artifacts were detached but quarantine cleanup failed: "
            + ", ".join(cleanup_errors)
        )
    assert journal_contents is not None
    _remove_removal_journal(manifest_path, journal_contents)


def _move_to_quarantine(source: Path, destination: Path) -> None:
    os.rename(source, destination)


def _rollback_quarantined(quarantined: Sequence[QuarantinedArtifact]) -> list[str]:
    errors: list[str] = []
    for staged in reversed(quarantined):
        original_exists = os.path.lexists(staged.artifact.path)
        staged_exists = os.path.lexists(staged.path)
        if not staged_exists:
            if not original_exists or not _current_matches_entry(
                staged.artifact.path, staged.entry
            ):
                errors.append(str(staged.directory))
            continue
        if original_exists or not _current_matches_entry(staged.path, staged.entry):
            errors.append(str(staged.path))
            continue
        try:
            _move_to_quarantine(staged.path, staged.artifact.path)
        except OSError:
            errors.append(str(staged.path))
            continue
        if not _current_matches_entry(staged.artifact.path, staged.entry):
            errors.append(str(staged.artifact.path))
    return errors


def _remove_empty_quarantine_directories(
    quarantined: Sequence[QuarantinedArtifact],
) -> list[str]:
    errors: list[str] = []
    for directory in {staged.directory for staged in quarantined}:
        try:
            directory.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            errors.append(f"{directory} ({error})")
    return errors


def _finalize_quarantined(
    quarantined: Sequence[QuarantinedArtifact],
) -> list[str]:
    errors: list[str] = []
    for staged in quarantined:
        try:
            if os.path.lexists(staged.artifact.path):
                raise OwnershipError(
                    f"An unowned artifact appeared at {staged.artifact.path}"
                )
            if os.path.lexists(staged.path):
                if not _current_matches_entry(staged.path, staged.entry):
                    raise OwnershipError(
                        f"Quarantined artifact changed before deletion: {staged.path}"
                    )
                staged.path.unlink()
        except (OSError, OwnershipError) as error:
            errors.append(f"{staged.path} ({error})")
    if not errors:
        errors.extend(_remove_empty_quarantine_directories(quarantined))
    return errors


def _install_artifacts_from_args(args: argparse.Namespace) -> list[InstallArtifact]:
    artifacts: list[InstallArtifact] = []
    for name, path, source, raw_mode in args.regular or []:
        try:
            mode = int(raw_mode, 8)
        except ValueError as error:
            raise OwnershipError(f"Invalid mode for {name}: {raw_mode}") from error
        artifacts.append(
            InstallArtifact(name, Path(path), "regular", source=Path(source), mode=mode)
        )
    for name, path, target in args.symlink or []:
        artifacts.append(InstallArtifact(name, Path(path), "symlink", target=target))
    return artifacts


def _add_install_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--profiles-expected", choices=("0", "1"), required=True)
    parser.add_argument("--regular", nargs=4, action="append", metavar=("NAME", "PATH", "SOURCE", "MODE"))
    parser.add_argument("--symlink", nargs=3, action="append", metavar=("NAME", "PATH", "TARGET"))


def _add_allowed_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--allow-regular", nargs=2, action="append", metavar=("NAME", "PATH"))
    parser.add_argument("--allow-symlink", nargs=3, action="append", metavar=("NAME", "PATH", "TARGET"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-install")
    _add_install_arguments(check)
    install = commands.add_parser("install")
    _add_install_arguments(install)
    status = commands.add_parser("status")
    _add_allowed_arguments(status)
    status.add_argument("--field", choices=("profiles-expected", "has-artifact"), required=True)
    status.add_argument("--name")
    run = commands.add_parser("run-owned")
    _add_allowed_arguments(run)
    run.add_argument("--name", required=True)
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    remove = commands.add_parser("remove-owned")
    _add_allowed_arguments(remove)
    profiles = commands.add_parser("set-profiles-expected")
    _add_allowed_arguments(profiles)
    profiles.add_argument("--value", choices=("0", "1"), required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command in {"check-install", "install"}:
            artifacts = _install_artifacts_from_args(args)
            if args.command == "check-install":
                _validate_artifact_parents(artifacts, args.home)
                _validate_install(
                    args.prefix,
                    args.manifest,
                    artifacts,
                    profiles_expected=args.profiles_expected == "1",
                )
            else:
                install_artifacts(
                    args.prefix,
                    args.manifest,
                    artifacts,
                    profiles_expected=args.profiles_expected == "1",
                    home=args.home,
                )
        else:
            allowed = _parse_allowed(args)
            manifest = _validated_installed_manifest(args.manifest, allowed)
            if args.command == "status":
                if args.field == "profiles-expected":
                    print("1" if manifest["profiles_expected"] else "0")
                else:
                    if not args.name:
                        raise OwnershipError("--name is required for has-artifact.")
                    print("1" if args.name in manifest["artifacts"] else "0")
            elif args.command == "run-owned":
                entry = manifest["artifacts"].get(args.name)
                artifact = allowed.get(args.name)
                if entry is None or artifact is None or artifact.kind != "regular":
                    raise OwnershipError(f"No owned executable artifact named {args.name!r}.")
                contents, metadata = _read_regular(
                    artifact.path,
                    label=f"Owned executable {artifact.name}",
                )
                if (
                    _sha256(contents) != entry["sha256"]
                    or stat.S_IMODE(metadata.st_mode) != entry["mode"]
                ):
                    raise OwnershipError(f"Owned executable changed: {artifact.path}")
                arguments = list(args.arguments)
                if arguments[:1] == ["--"]:
                    arguments.pop(0)
                if not contents.startswith(b"#!/bin/sh\n"):
                    raise OwnershipError(
                        f"Owned executable has an unexpected interpreter: {artifact.path}"
                    )
                # Feed the exact verified bytes to the system shell. This keeps
                # the launcher off a second mutable pathname while preserving
                # its positional arguments on macOS's POSIX /bin/sh.
                subprocess.run(
                    ["/bin/sh", "-s", "--", *arguments],
                    input=contents,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            elif args.command == "remove-owned":
                remove_owned(args.manifest, allowed)
            elif args.command == "set-profiles-expected":
                manifest["profiles_expected"] = args.value == "1"
                _write_manifest(args.manifest, manifest)
    except (OSError, OwnershipError, subprocess.SubprocessError) as error:
        print(f"Codex Gamepad ownership error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
