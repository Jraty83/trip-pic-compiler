"""Media item model and lightweight metadata helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


@dataclass
class MediaItem:
    path: Path
    kind: str  # "image" | "video"
    captured_at: Optional[datetime] = None
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    orientation_applied: bool = False
    sharpness: float = 0.0
    phash: Optional[str] = None
    keep: bool = True
    reject_reason: Optional[str] = None
    score: float = 0.0
    day_label: Optional[str] = None
    show_day_label: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["captured_at"] = self.captured_at.isoformat() if self.captured_at else None
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaItem":
        captured = data.get("captured_at")
        return cls(
            path=Path(data["path"]),
            kind=data["kind"],
            captured_at=datetime.fromisoformat(captured) if captured else None,
            duration_sec=float(data.get("duration_sec") or 0.0),
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            orientation_applied=bool(data.get("orientation_applied")),
            sharpness=float(data.get("sharpness") or 0.0),
            phash=data.get("phash"),
            keep=bool(data.get("keep", True)),
            reject_reason=data.get("reject_reason"),
            score=float(data.get("score") or 0.0),
            day_label=data.get("day_label"),
            show_day_label=bool(data.get("show_day_label")),
        )


def classify_path(path: Path) -> Optional[str]:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def ffmpeg_available() -> bool:
    return shutil.which("ffprobe") is not None and shutil.which("ffmpeg") is not None


def run_ffprobe(path: Path) -> Dict[str, Any]:
    """Return ffprobe JSON for a media file. Raises if ffprobe missing/fails."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ffprobe failed for {path}")
    return json.loads(result.stdout)


def save_manifest(path: Path, items: List[MediaItem], meta: Optional[Dict[str, Any]] = None) -> None:
    payload = {
        "meta": meta or {},
        "items": [item.to_dict() for item in items],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def load_manifest(path: Path) -> List[MediaItem]:
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    return [MediaItem.from_dict(row) for row in payload.get("items", [])]
