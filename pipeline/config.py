"""Shared paths, preferences loading, and constants."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict

import yaml

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


@dataclass
class Preferences:
    """Personalized taste + timing — supplied by the user, not hardcoded in logic."""

    target_duration_min: float = 45.0
    image_seconds: float = 8.0
    day_label_format: str = "%d/%m/%Y"
    taste_prompt: str = ""
    blur_threshold: float = 80.0
    duplicate_hash_distance: int = 8
    max_burst_keep: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Preferences":
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def load_preferences(path: Path) -> Preferences:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Preferences file must be a YAML mapping: {path}")
    return Preferences.from_dict(raw)


def save_preferences(path: Path, prefs: Preferences) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            prefs.to_dict(),
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_preferences_path() -> Path:
    return project_root() / "preferences.yaml"


def example_preferences_path() -> Path:
    return project_root() / "preferences.example.yaml"


def presentation_template_dir() -> Path:
    return project_root() / "presentation" / "template"
