"""Ingest: discover media under a directory, or unpack .zip archives first."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Callable, List, Optional, Set

from pipeline.media import MediaItem, classify_path

ProgressCb = Optional[Callable[[str], None]]


def extract_zip(zip_path: Path, dest_dir: Path, on_progress: ProgressCb = None) -> Path:
    """Extract a zip into dest_dir (created if needed). Returns dest_dir."""
    if not zip_path.is_file():
        raise FileNotFoundError(f"Zip not found: {zip_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    if on_progress:
        on_progress(f"Extracting {zip_path.name} → {dest_dir}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    marker = dest_dir / ".trip_pic_extracted"
    marker.write_text(str(zip_path.resolve()), encoding="utf-8")
    return dest_dir


def _extract_if_needed(zip_path: Path, dest_dir: Path, on_progress: ProgressCb = None) -> Path:
    marker = dest_dir / ".trip_pic_extracted"
    if marker.exists() and dest_dir.is_dir():
        if on_progress:
            on_progress(f"Zip already extracted: {zip_path.name}")
        return dest_dir
    return extract_zip(zip_path, dest_dir, on_progress)


def collect_scan_roots(
    source: Path,
    work_dir: Path,
    on_progress: ProgressCb = None,
) -> List[Path]:
    """
    Resolve input path (folder or .zip) into directories to scan for media.

    - `run path/to/trip.zip` → extract under work_dir/_extracted/<stem>
    - `run path/to/folder` → scan folder; also unpack any *.zip directly in it
    """
    source = source.resolve()
    extract_root = work_dir / "_extracted"
    roots: List[Path] = []

    if source.is_file() and source.suffix.lower() == ".zip":
        roots.append(_extract_if_needed(source, extract_root / source.stem, on_progress))
        return roots

    if not source.is_dir():
        raise FileNotFoundError(f"Input not found (folder or .zip): {source}")

    roots.append(source)
    for zip_path in sorted(source.glob("*.zip")):
        roots.append(_extract_if_needed(zip_path, extract_root / zip_path.stem, on_progress))
    return roots


def discover_media_in_roots(roots: List[Path]) -> List[MediaItem]:
    items: List[MediaItem] = []
    seen: Set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if path.suffix.lower() == ".zip":
                continue
            kind = classify_path(path)
            if kind is None:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            # Skip files inside another zip path segment that is the archive itself
            seen.add(resolved)
            items.append(MediaItem(path=resolved, kind=kind))
    return items


def discover_media(input_dir: Path) -> List[MediaItem]:
    """Backward-compatible: scan a single directory tree."""
    return discover_media_in_roots([input_dir])
