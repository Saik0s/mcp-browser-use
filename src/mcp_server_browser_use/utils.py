"""Utilities for file persistence and helpers."""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]


def save_execution_result(
    content: str,
    prefix: str = "result",
    metadata: JsonObject | None = None,
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
    # Timestamp alone (to seconds) can collide under concurrency.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    nonce = uuid.uuid4().hex[:8]

    # Sanitize prefix for filesystem
    safe_prefix = re.sub(r"[^\w\-]", "_", prefix)[:30]
    filename = f"{timestamp}_{safe_prefix}_{nonce}.md"
    file_path = results_dir / filename

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
