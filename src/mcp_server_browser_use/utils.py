"""Utilities for file persistence and helpers."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)


def save_execution_result(
    content: str,
    prefix: str = "result",
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Save execution result to a file in the results directory.

    Args:
        content: The text content to save (markdown/text).
        prefix: Filename prefix (e.g., 'agent', 'research').
        metadata: Optional metadata to save alongside in a .json file.

    Returns:
        Path to the saved file.
    """
    results_dir = settings.get_results_dir()
    # Include microseconds to avoid collisions when called multiple times per second.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    # Sanitize prefix for filesystem
    safe_prefix = re.sub(r"[^\w\-]", "_", prefix)[:30]
    base = f"{timestamp}_{safe_prefix}"
    file_path = results_dir / f"{base}.md"
    # Extremely unlikely, but still handle same-microsecond collisions deterministically.
    if file_path.exists():
        for i in range(1, 10_000):
            candidate = results_dir / f"{base}_{i}.md"
            if not candidate.exists():
                file_path = candidate
                break
        else:
            raise RuntimeError("Failed to allocate a unique result filename after 10,000 attempts")
    filename = file_path.name

    file_path.write_text(content, encoding="utf-8")

    if metadata:
        meta_path = file_path.with_suffix(".json")
        meta_full = {
            "timestamp": datetime.now().isoformat(),
            "file": filename,
            **metadata,
        }
        meta_path.write_text(json.dumps(meta_full, indent=2), encoding="utf-8")

    logger.info(f"Saved result to {file_path}")
    return file_path
