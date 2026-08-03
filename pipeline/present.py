"""Presentation draft: copy selected media + emit HTML slideshow player."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from pipeline.config import Preferences, presentation_template_dir
from pipeline.media import MediaItem


def _rel_media_name(item: MediaItem, index: int) -> str:
    ext = item.path.suffix.lower() or (".mp4" if item.kind == "video" else ".jpg")
    return f"{index:04d}_{item.kind}{ext}"


def build_presentation(
    selected: List[MediaItem],
    prefs: Preferences,
    meta: Dict[str, Any],
    out_dir: Path,
) -> Path:
    """Write a self-contained presentation folder; returns path to index.html."""
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir = out_dir / "media"
    if media_dir.exists():
        shutil.rmtree(media_dir)
    media_dir.mkdir(parents=True)

    slides: List[Dict[str, Any]] = []
    for idx, item in enumerate(selected, start=1):
        name = _rel_media_name(item, idx)
        dest = media_dir / name
        shutil.copy2(item.path, dest)
        duration = item.duration_sec if item.kind == "video" else prefs.image_seconds
        slides.append(
            {
                "src": f"media/{name}",
                "kind": item.kind,
                "duration_sec": round(float(duration), 2),
                "captured_at": item.captured_at.isoformat() if item.captured_at else None,
                "day_label": item.day_label,
                "show_day_label": item.show_day_label,
                "score": round(item.score, 1),
            }
        )

    timeline = {
        "meta": meta,
        "preferences": {
            "target_duration_min": prefs.target_duration_min,
            "image_seconds": prefs.image_seconds,
            "day_label_format": prefs.day_label_format,
        },
        "slides": slides,
    }
    timeline_path = out_dir / "timeline.json"
    with timeline_path.open("w", encoding="utf-8") as fh:
        json.dump(timeline, fh, indent=2, ensure_ascii=False)

    template_dir = presentation_template_dir()
    for filename in ("index.html", "styles.css", "app.js"):
        src = template_dir / filename
        if not src.exists():
            raise FileNotFoundError(f"Missing presentation template: {src}")
        shutil.copy2(src, out_dir / filename)

    return out_dir / "index.html"
