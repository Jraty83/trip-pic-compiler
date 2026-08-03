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
    from datetime import datetime

    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir = out_dir / "media"
    if media_dir.exists():
        shutil.rmtree(media_dir)
    media_dir.mkdir(parents=True)

    # Hard guarantee: oldest → newest by capture timestamp
    ordered = sorted(
        selected,
        key=lambda m: (m.captured_at or datetime.min, m.path.name),
    )
    from pipeline.curate import assign_day_labels

    assign_day_labels(ordered, prefs.day_label_format)

    slides: List[Dict[str, Any]] = []
    for idx, item in enumerate(ordered, start=1):
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
    # CSS + JS copied as-is
    for filename in ("styles.css", "app.js"):
        src = template_dir / filename
        if not src.exists():
            raise FileNotFoundError(f"Missing presentation template: {src}")
        shutil.copy2(src, out_dir / filename)

    # HTML gets timeline embedded so file:// works (Chrome blocks fetch of local JSON).
    html_template = (template_dir / "index.html").read_text(encoding="utf-8")
    embedded = json.dumps(timeline, ensure_ascii=False)
    inject = (
        f"<script>window.__TIMELINE__ = {embedded};</script>\n"
        "    <script src=\"app.js\"></script>"
    )
    if '<script src="app.js"></script>' not in html_template:
        raise RuntimeError("index.html template missing app.js script tag")
    html = html_template.replace('<script src="app.js"></script>', inject)
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    return out_dir / "index.html"


def repair_presentation_embed(presentation_dir: Path) -> Path:
    """Re-embed timeline.json into an existing presentation index.html."""
    presentation_dir = presentation_dir.resolve()
    timeline_path = presentation_dir / "timeline.json"
    if not timeline_path.exists():
        raise FileNotFoundError(f"Missing timeline.json in {presentation_dir}")
    with timeline_path.open(encoding="utf-8") as fh:
        timeline = json.load(fh)

    template_dir = presentation_template_dir()
    shutil.copy2(template_dir / "app.js", presentation_dir / "app.js")
    shutil.copy2(template_dir / "styles.css", presentation_dir / "styles.css")

    html_template = (template_dir / "index.html").read_text(encoding="utf-8")
    embedded = json.dumps(timeline, ensure_ascii=False)
    inject = (
        f"<script>window.__TIMELINE__ = {embedded};</script>\n"
        "    <script src=\"app.js\"></script>"
    )
    html = html_template.replace('<script src="app.js"></script>', inject)
    index_path = presentation_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return index_path
