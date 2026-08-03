"""Normalize: orientation + capture time + basic dimensions/duration."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageOps

from pipeline.media import MediaItem, ffmpeg_available, run_ffprobe

# HEIC support is optional — works if pillow-heif is installed later.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass


def _exif_datetime(img: Image.Image) -> Optional[datetime]:
    exif = img.getexif()
    if not exif:
        return None
    # Prefer DateTimeOriginal (36867), then DateTimeDigitized, then DateTime
    for key in (36867, 36868, 306):
        raw = exif.get(key)
        if not raw:
            continue
        try:
            return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def normalize_image(item: MediaItem, out_dir: Path) -> MediaItem:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = item.path.stem
    # Always emit JPEG for consistent downstream handling
    dest = out_dir / f"{stem}.jpg"

    with Image.open(item.path) as img:
        captured = _exif_datetime(img) or _file_mtime(item.path)
        oriented = ImageOps.exif_transpose(img)
        if oriented is None:
            oriented = img
        rgb = oriented.convert("RGB")
        rgb.save(dest, "JPEG", quality=92, optimize=True)
        width, height = rgb.size

    item.path = dest
    item.captured_at = captured
    item.width = width
    item.height = height
    item.duration_sec = 0.0
    item.orientation_applied = True
    return item


def _video_rotation(probe: dict) -> int:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        # side_data rotation or tags.rotate
        for side in stream.get("side_data_list") or []:
            if "rotation" in side:
                try:
                    return int(float(side["rotation"]))
                except (TypeError, ValueError):
                    pass
        tags = stream.get("tags") or {}
        if "rotate" in tags:
            try:
                return int(tags["rotate"])
            except (TypeError, ValueError):
                pass
    return 0


def _video_size_duration(probe: dict) -> Tuple[int, int, float]:
    width = height = 0
    duration = 0.0
    fmt = probe.get("format") or {}
    try:
        duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    for stream in probe.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        if not duration:
            try:
                duration = float(stream.get("duration") or 0.0)
            except (TypeError, ValueError):
                pass
        break
    return width, height, duration


def _video_captured_at(probe: dict, path: Path) -> datetime:
    fmt = probe.get("format") or {}
    tags = fmt.get("tags") or {}
    for key in ("creation_time", "com.apple.quicktime.creationdate"):
        raw = tags.get(key)
        if not raw:
            continue
        # e.g. 2026-07-20T14:22:01.000000Z
        cleaned = str(raw).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(cleaned).replace(tzinfo=None)
        except ValueError:
            continue
    return _file_mtime(path)


def normalize_video(item: MediaItem, out_dir: Path) -> MediaItem:
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{item.path.stem}.mp4"

    if not ffmpeg_available():
        # Copy as-is; metadata limited
        if item.path.resolve() != dest.resolve():
            shutil.copy2(item.path, dest)
        item.path = dest
        item.captured_at = _file_mtime(item.path)
        item.orientation_applied = False
        item.duration_sec = 0.0
        return item

    probe = run_ffprobe(item.path)
    width, height, duration = _video_size_duration(probe)
    rotation = _video_rotation(probe)
    captured = _video_captured_at(probe, item.path)

    # Bake rotation into pixels so players show correct orientation; keep audio.
    # transpose filters for 90/270; hflip+vflip for 180.
    vf: Optional[str]
    if rotation in (90, -270):
        vf = "transpose=1"
    elif rotation in (-90, 270):
        vf = "transpose=2"
    elif rotation in (180, -180):
        vf = "hflip,vflip"
    else:
        vf = None

    cmd = ["ffmpeg", "-y", "-i", str(item.path)]
    if vf:
        cmd.extend(["-vf", vf])
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # Fallback: copy without re-encode
        shutil.copy2(item.path, dest)

    # After baking rotation, swap dimensions if needed
    if abs(rotation) in (90, 270):
        width, height = height, width

    item.path = dest
    item.captured_at = captured
    item.width = width
    item.height = height
    item.duration_sec = duration
    item.orientation_applied = True
    return item


def normalize_all(items: List[MediaItem], work_dir: Path) -> List[MediaItem]:
    images_dir = work_dir / "normalized" / "images"
    videos_dir = work_dir / "normalized" / "videos"
    result: List[MediaItem] = []
    for item in items:
        if item.kind == "image":
            result.append(normalize_image(item, images_dir))
        else:
            result.append(normalize_video(item, videos_dir))
    return result
