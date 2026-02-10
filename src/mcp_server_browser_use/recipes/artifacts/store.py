"""Artifact store for recipe-learning pipeline.

Artifacts are persisted to disk so the pipeline can resume safely. This module enforces:
- Atomic writes (temp file + fsync + rename)
- Private permissions (0700 dirs, 0600 files) on POSIX
- Safe paths (no traversal, no symlink-following reads)
- schema_hash verification on read for resume safety
"""

from __future__ import annotations

import errno
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from mcp_server_browser_use.config import get_config_dir

from .models import ArtifactModel

TArtifact = TypeVar("TArtifact", bound=ArtifactModel)

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class ArtifactStoreError(RuntimeError):
    pass


class ArtifactPathError(ArtifactStoreError):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactSchemaMismatchError(ArtifactStoreError):
    artifact_path: Path
    expected_schema_hash: str
    found_schema_hash: str

    def __str__(self) -> str:
        return (
            "Artifact schema_hash mismatch, resume is unsafe. "
            f"path={self.artifact_path} expected={self.expected_schema_hash} found={self.found_schema_hash}"
        )


def get_default_artifacts_dir() -> Path:
    # Contract: artifacts live under the config dir, but MUST be private.
    return get_config_dir() / "artifacts"


def _nofollow_flag() -> int:
    # O_NOFOLLOW is not available on all platforms (Windows).
    return int(getattr(os, "O_NOFOLLOW", 0))


def _validate_component(name: str, *, label: str) -> str:
    if not name or not _SAFE_NAME_RE.fullmatch(name):
        raise ArtifactPathError(f"Invalid {label} {name!r}, expected {_SAFE_NAME_RE.pattern}")
    return name


def _ensure_private_dir(path: Path) -> None:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        # Create with restrictive perms, then chmod to override umask.
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(path, 0o700)
        return

    if stat.S_ISLNK(st.st_mode):
        raise ArtifactPathError(f"Refusing to use symlink directory: {path}")
    if not stat.S_ISDIR(st.st_mode):
        raise ArtifactPathError(f"Expected directory at {path}, found mode={oct(stat.S_IMODE(st.st_mode))}")
    if os.name != "nt":
        os.chmod(path, 0o700)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    _ensure_private_dir(path.parent)

    tmp_name = f".{path.name}.tmp.{os.getpid()}"
    tmp_path = path.parent / tmp_name

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _nofollow_flag()
    fd = os.open(str(tmp_path), flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _read_bytes_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY | _nofollow_flag()
    try:
        fd = os.open(str(path), flags)
    except OSError as e:
        if e.errno in (errno.ELOOP, getattr(errno, "EMLINK", 0)):
            raise ArtifactPathError(f"Refusing to follow symlink for artifact read: {path}") from e
        raise

    with os.fdopen(fd, "rb") as f:
        return f.read()


class ArtifactStore:
    def __init__(self, root_dir: Path | None = None) -> None:
        self._root_dir = (root_dir or get_default_artifacts_dir()).expanduser()

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def task_dir(self, task_id: str) -> Path:
        _validate_component(task_id, label="task_id")
        return self._root_dir / task_id

    def artifact_path(self, task_id: str, artifact_name: str) -> Path:
        _validate_component(artifact_name, label="artifact_name")
        return self.task_dir(task_id) / f"{artifact_name}.json"

    def write(self, task_id: str, artifact_name: str, artifact: ArtifactModel) -> Path:
        root = self._root_dir
        _ensure_private_dir(root)

        task_dir = self.task_dir(task_id)
        _ensure_private_dir(task_dir)

        path = self.artifact_path(task_id, artifact_name)
        payload_obj = artifact.model_dump(mode="json")
        payload = (json.dumps(payload_obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
        _atomic_write_bytes(path, payload)
        return path

    def read(self, task_id: str, artifact_name: str, model_cls: type[TArtifact]) -> TArtifact:
        path = self.artifact_path(task_id, artifact_name)
        raw = _read_bytes_nofollow(path)
        data: object = json.loads(raw.decode("utf-8"))
        artifact = model_cls.model_validate(data)

        expected = model_cls.schema_hash_value()
        found = artifact.schema_hash
        if found != expected:
            raise ArtifactSchemaMismatchError(path, expected_schema_hash=expected, found_schema_hash=found)

        return artifact
