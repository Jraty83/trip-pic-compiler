"""Normalize: orientation + capture time + basic dimensions/duration."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PIL import Image, ImageOps

from pipeline.media import MediaItem, ffmpeg_available, run_ffprobe

ProgressCb = Optional[Callable[[int, int, str, str, float], None]]

# HEIC support when pillow-heif is installed.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass


def _parse_exif_dt(raw: object) -> Optional[datetime]:
    if raw is None:
        return None
    text = str(raw).strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _exif_datetime(img: Image.Image) -> Optional[datetime]:
    """Read capture time from EXIF (top-level + Exif IFD)."""
    exif = img.getexif()
    if not exif:
        return None

    # Prefer DateTimeOriginal / Digitized from Exif IFD (common on HEIC/iPhone).
    try:
        ifd = exif.get_ifd(0x8769)  # Exif IFD
    except Exception:  # noqa: BLE001
        ifd = {}
    for key in (36867, 36868):  # DateTimeOriginal, DateTimeDigitized
        parsed = _parse_exif_dt(ifd.get(key) if ifd else None)
        if parsed:
            return parsed
        parsed = _parse_exif_dt(exif.get(key))
        if parsed:
            return parsed

    # Fallback: DateTime (306) often present at top level
    parsed = _parse_exif_dt(exif.get(306))
    if parsed:
        return parsed
    return None


def capture_time_for_image(path: Path) -> datetime:
    """Always prefer source-file EXIF over filesystem mtime."""
    try:
        with Image.open(path) as img:
            captured = _exif_datetime(img)
            if captured:
                return captured
    except Exception:  # noqa: BLE001
        pass
    return _file_mtime(path)


def capture_time_for_video(path: Path) -> datetime:
    if ffmpeg_available():
        try:
            return _video_captured_at(run_ffprobe(path), path)
        except Exception:  # noqa: BLE001
            pass
    return _file_mtime(path)


def _file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def _can_reuse(source: Path, dest: Path) -> bool:
    if not dest.exists() or dest.stat().st_size <= 0:
        return False
    return dest.stat().st_mtime >= source.stat().st_mtime


def normalize_image(item: MediaItem, out_dir: Path) -> MediaItem:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = item.path.stem
    dest = out_dir / f"{stem}.jpg"
    source = item.path
    # Capture time must come from the original — reused JPEGs often lack EXIF dates.
    captured = capture_time_for_image(source)

    if _can_reuse(source, dest):
        with Image.open(dest) as img:
            width, height = img.size
        item.path = dest
        item.captured_at = captured
        item.width = width
        item.height = height
        item.duration_sec = 0.0
        item.orientation_applied = True
        return item

    with Image.open(source) as img:
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


def _parse_video_timestamp(raw: object) -> Optional[datetime]:
    """
    Parse video container timestamps into naive local wall-clock time.

    iPhone/QuickTime often has:
      creation_time = 2026-07-25T15:07:37.000000Z   (UTC)
      date          = 2026-07-25T18:07:37+0300       (local)

    Photo EXIF is local wall-clock without TZ. Prefer offset-aware local tags,
    and convert UTC tags to local so videos don't sort hours too early.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # Normalize Zulu and +0300 → +03:00 for fromisoformat
    text = text.replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    # Drop sub-seconds for simpler parse if present before offset
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # Sometimes "2026-07-25 18:07:37"
        try:
            return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    if dt.tzinfo is None:
        return dt

    offset = dt.utcoffset()
    if offset is not None and offset.total_seconds() == 0:
        # UTC → local timezone wall clock (matches camera EXIF for same trip TZ)
        return dt.astimezone().replace(tzinfo=None)

    # Offset-aware local (e.g. +03:00): keep the wall-clock components
    return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)


def _collect_video_tags(probe: dict) -> dict:
    tags = {}
    fmt = probe.get("format") or {}
    tags.update(fmt.get("tags") or {})
    for stream in probe.get("streams") or []:
        st = stream.get("tags") or {}
        for key, value in st.items():
            tags.setdefault(key, value)
    return tags


def _video_captured_at(probe: dict, path: Path) -> datetime:
    tags = _collect_video_tags(probe)
    # Prefer local-offset "date" over UTC creation_time
    for key in (
        "date",
        "com.apple.quicktime.creationdate",
        "creation_time",
        "com.apple.quicktime.creation_time",
    ):
        parsed = _parse_video_timestamp(tags.get(key))
        if parsed:
            return parsed
    return _file_mtime(path)


def _run_ffmpeg(cmd: List[str]) -> bool:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode == 0


def normalize_video(item: MediaItem, out_dir: Path) -> Tuple[MediaItem, str]:
    """Returns (item, mode) where mode is reuse|copy|remux|reencode|fallback."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{item.path.stem}.mp4"
    source = item.path
    captured = capture_time_for_video(source)

    if _can_reuse(source, dest):
        width = height = 0
        duration = 0.0
        if ffmpeg_available():
            try:
                probe = run_ffprobe(dest)
                width, height, duration = _video_size_duration(probe)
            except Exception:  # noqa: BLE001
                pass
        item.path = dest
        item.captured_at = captured
        item.width = width
        item.height = height
        item.duration_sec = duration
        item.orientation_applied = True
        return item, "reuse"

    if not ffmpeg_available():
        if source.resolve() != dest.resolve():
            shutil.copy2(source, dest)
        item.path = dest
        item.captured_at = captured
        item.orientation_applied = False
        item.duration_sec = 0.0
        return item, "copy"

    probe = run_ffprobe(source)
    width, height, duration = _video_size_duration(probe)
    rotation = _video_rotation(probe)
    # Prefer already-resolved source capture time
    captured = capture_time_for_video(source)

    vf: Optional[str]
    if rotation in (90, -270):
        vf = "transpose=1"
    elif rotation in (-90, 270):
        vf = "transpose=2"
    elif rotation in (180, -180):
        vf = "hflip,vflip"
    else:
        vf = None

    mode = "reencode"
    if vf is None:
        # No rotation bake needed — remux/stream-copy (much faster than libx264).
        ok = _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(dest),
            ]
        )
        if ok:
            mode = "remux"
        else:
            mode = "need_reencode"

    if vf is not None or mode == "need_reencode":
        ok = _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                *(["-vf", vf] if vf else []),
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
        if not ok:
            shutil.copy2(source, dest)
            mode = "fallback"
        else:
            mode = "reencode"

    if abs(rotation) in (90, 270) and mode == "reencode":
        width, height = height, width

    item.path = dest
    item.captured_at = captured
    item.width = width
    item.height = height
    item.duration_sec = duration
    item.orientation_applied = True
    return item, mode


def normalize_all(
    items: List[MediaItem],
    work_dir: Path,
    on_progress: ProgressCb = None,
) -> List[MediaItem]:
    images_dir = work_dir / "normalized" / "images"
    videos_dir = work_dir / "normalized" / "videos"
    result: List[MediaItem] = []
    total = len(items)
    for idx, item in enumerate(items, start=1):
        source_name = item.path.name
        t0 = time.monotonic()
        if item.kind == "image":
            result.append(normalize_image(item, images_dir))
            detail = "image"
        else:
            normalized, mode = normalize_video(item, videos_dir)
            result.append(normalized)
            detail = f"video/{mode}"
        elapsed = time.monotonic() - t0
        if on_progress:
            on_progress(idx, total, source_name, detail, elapsed)
    return result
