"""Curate: build a timed selection using user preferences (taste layer input).

v0.1 uses a transparent heuristic: chronological coverage + sharpness,
sized to target duration. The taste_prompt is stored on the timeline for
future vision-API scoring — not hardcoded into engine logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from pipeline.config import Preferences
from pipeline.media import MediaItem


def _item_duration(item: MediaItem, image_seconds: float) -> float:
    if item.kind == "video":
        return max(item.duration_sec, 1.0)
    return image_seconds


def _day_key(dt: Optional[datetime]) -> str:
    if dt is None:
        return "unknown"
    return dt.strftime("%Y-%m-%d")


def assign_day_labels(items: List[MediaItem], day_format: str) -> None:
    prev_day: Optional[str] = None
    for item in sorted(items, key=lambda m: (m.captured_at or datetime.min, m.path.name)):
        if item.captured_at:
            label = item.captured_at.strftime(day_format)
            day = _day_key(item.captured_at)
        else:
            label = None
            day = "unknown"
        item.day_label = label
        item.show_day_label = bool(label) and day != prev_day and day != "unknown"
        if day != "unknown":
            prev_day = day


def heuristic_score(item: MediaItem) -> float:
    """Generic stand-in until vision scoring uses taste_prompt."""
    if item.kind == "video":
        # Prefer videos with a sensible length (not tiny, not endless)
        d = item.duration_sec or 0.0
        if d < 2:
            return 40.0
        if d > 180:
            return 55.0
        return 75.0 + min(d, 60) * 0.1
    # Images: sharpness normalized loosely
    return min(100.0, 40.0 + item.sharpness / 10.0)


def curate(
    candidates: List[MediaItem],
    prefs: Preferences,
) -> Tuple[List[MediaItem], dict]:
    """Select a subset that approximately fills target_duration_min."""
    target_sec = prefs.target_duration_min * 60.0
    image_seconds = prefs.image_seconds

    ranked = sorted(candidates, key=lambda m: (m.captured_at or datetime.min, m.path.name))
    for item in ranked:
        item.score = heuristic_score(item)

    # Ensure day coverage: take best item per day first, then fill by score
    by_day: dict = {}
    for item in ranked:
        key = _day_key(item.captured_at)
        by_day.setdefault(key, []).append(item)

    selected: List[MediaItem] = []
    selected_ids = set()
    total = 0.0

    # Pass 1: one representative per day (highest score)
    for day, day_items in sorted(by_day.items()):
        best = max(day_items, key=lambda m: m.score)
        dur = _item_duration(best, image_seconds)
        selected.append(best)
        selected_ids.add(id(best))
        total += dur

    # Pass 2: fill remaining budget with highest-scoring leftovers chronologically mixed
    leftovers = [m for m in ranked if id(m) not in selected_ids]
    leftovers.sort(key=lambda m: m.score, reverse=True)

    for item in leftovers:
        dur = _item_duration(item, image_seconds)
        if total + dur > target_sec * 1.05 and total >= target_sec * 0.85:
            continue
        if total >= target_sec:
            break
        selected.append(item)
        selected_ids.add(id(item))
        total += dur

    # Chronological final order + day labels
    selected.sort(key=lambda m: (m.captured_at or datetime.min, m.path.name))
    assign_day_labels(selected, prefs.day_label_format)

    # Recompute exact duration
    total = sum(_item_duration(m, image_seconds) for m in selected)
    meta = {
        "target_duration_min": prefs.target_duration_min,
        "estimated_duration_sec": round(total, 1),
        "estimated_duration_min": round(total / 60.0, 1),
        "image_seconds": image_seconds,
        "selected_count": len(selected),
        "candidate_count": len(candidates),
        "taste_prompt": prefs.taste_prompt,
        "curation_mode": "heuristic_v0.1",
        "note": (
            "Heuristic curation sized to duration with day coverage. "
            "taste_prompt is stored for upcoming vision-API scoring."
        ),
    }
    return selected, meta
