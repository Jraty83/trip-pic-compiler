"""Ingest: discover media files under an input directory."""

from __future__ import annotations

from pathlib import Path
from typing import List

from pipeline.media import MediaItem, classify_path


def discover_media(input_dir: Path) -> List[MediaItem]:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    items: List[MediaItem] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        kind = classify_path(path)
        if kind is None:
            continue
        items.append(MediaItem(path=path.resolve(), kind=kind))
    return items
