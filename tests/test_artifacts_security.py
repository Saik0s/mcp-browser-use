"""Security and correctness tests for pipeline artifact persistence."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from mcp_server_browser_use.recipes.artifacts.models import SessionRecording
from mcp_server_browser_use.recipes.artifacts.store import ArtifactPathError, ArtifactSchemaMismatchError, ArtifactStore


def _make_recording(*, task: str, result_size: int = 0) -> SessionRecording:
    return SessionRecording(
        task=task,
        result=("x" * result_size) if result_size else "ok",
        requests=[],
        responses=[],
        navigation_urls=["https://example.com"],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=None,
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits not meaningful on Windows")
def test_permissions(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    task_id = "00000000-0000-0000-0000-000000000000"

    path = store.write(task_id, "recording", _make_recording(task="t"))

    root_mode = stat.S_IMODE(store.root_dir.stat().st_mode)
    task_mode = stat.S_IMODE(store.task_dir(task_id).stat().st_mode)
    file_mode = stat.S_IMODE(path.stat().st_mode)

    assert root_mode == 0o700
    assert task_mode == 0o700
    assert file_mode == 0o600


def test_atomic_write(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    task_id = "11111111-1111-1111-1111-111111111111"

    store.write(task_id, "recording", _make_recording(task="v1", result_size=200_000))

    stop = threading.Event()
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            while not stop.is_set():
                artifact = store.read(task_id, "recording", SessionRecording)
                assert artifact.task in {"v1", "v2", "v3"}
        except BaseException as e:
            errors.append(e)
            stop.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    for version in ("v2", "v3"):
        store.write(task_id, "recording", _make_recording(task=version, result_size=200_000))
        time.sleep(0.01)

    stop.set()
    t.join(timeout=2.0)

    if errors:
        raise errors[0]


def test_schema_hash_mismatch_fails_fast(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    task_id = "22222222-2222-2222-2222-222222222222"

    path = store.write(task_id, "recording", _make_recording(task="t"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_hash"] = "deadbeef"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ArtifactSchemaMismatchError):
        store.read(task_id, "recording", SessionRecording)


def test_non_following_reads_reject_symlink(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    task_id = "33333333-3333-3333-3333-333333333333"

    target = tmp_path / "outside.json"
    payload = _make_recording(task="t").model_dump(mode="json")
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    store.root_dir.mkdir(parents=True, exist_ok=True)
    store.task_dir(task_id).mkdir(parents=True, exist_ok=True)

    symlink_path = store.artifact_path(task_id, "recording")
    symlink_path.symlink_to(target)

    with pytest.raises(ArtifactPathError):
        store.read(task_id, "recording", SessionRecording)
