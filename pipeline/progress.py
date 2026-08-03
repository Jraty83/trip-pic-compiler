"""Progress / ETA helpers for long-running pipeline stages."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


def format_duration(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # NaN
        return "--:--"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class StageETA:
    """Rolling ETA for a single stage (e.g. normalize)."""

    def __init__(self, total: int, label: str = "") -> None:
        self.total = max(total, 0)
        self.label = label
        self.done = 0
        self.started_at = time.monotonic()
        self._durations: List[float] = []
        self._by_kind: Dict[str, List[float]] = defaultdict(list)
        self.last_duration = 0.0
        self.last_name = ""
        self.last_detail = ""

    def record(self, name: str, detail: str, duration_sec: float) -> None:
        self.done += 1
        self.last_duration = duration_sec
        self.last_name = name
        self.last_detail = detail
        self._durations.append(duration_sec)
        kind = "video" if detail.startswith("video") else "image"
        self._by_kind[kind].append(duration_sec)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def _avg(self, values: List[float], fallback: float = 0.5) -> float:
        if not values:
            return fallback
        window = values[-20:]
        return sum(window) / len(window)

    def eta_remaining(
        self,
        remaining_images: Optional[int] = None,
        remaining_videos: Optional[int] = None,
    ) -> float:
        left = self.total - self.done
        if left <= 0:
            return 0.0
        if remaining_images is not None and remaining_videos is not None:
            img_avg = self._avg(self._by_kind["image"], fallback=0.4)
            vid_avg = self._avg(self._by_kind["video"], fallback=8.0)
            return remaining_images * img_avg + remaining_videos * vid_avg
        return left * self._avg(self._durations, fallback=1.0)

    def file_line(
        self,
        remaining_images: Optional[int] = None,
        remaining_videos: Optional[int] = None,
    ) -> str:
        eta = self.eta_remaining(remaining_images, remaining_videos)
        return (
            f"[{self.done}/{self.total}] {self.last_detail}: {self.last_name}  "
            f"({format_duration(self.last_duration)})  "
            f"stage ETA {format_duration(eta)}"
        )


class PipelineETA:
    """Overall ETA to finished draft."""

    SANITIZE_PER_IMAGE = 0.15
    SANITIZE_PER_VIDEO = 0.02
    CURATE_BASE = 1.0
    PRESENT_PER_ITEM = 0.05
    PRESENT_BASE = 2.0

    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self._measured: Dict[str, float] = {}
        self.n_images = 0
        self.n_videos = 0
        self.n_selected_estimate = 0

    def set_counts(
        self,
        n_images: int,
        n_videos: int,
        target_duration_min: float,
        image_seconds: float,
    ) -> None:
        self.n_images = n_images
        self.n_videos = n_videos
        budget = target_duration_min * 60.0
        approx = int(budget / max(image_seconds, 1.0))
        self.n_selected_estimate = max(1, min(n_images + n_videos, approx))

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def mark_stage(self, name: str, duration_sec: float) -> None:
        self._measured[name] = duration_sec

    def estimate_sanitize(self) -> float:
        if "sanitize" in self._measured:
            return 0.0
        return self.n_images * self.SANITIZE_PER_IMAGE + self.n_videos * self.SANITIZE_PER_VIDEO

    def estimate_curate(self) -> float:
        if "curate" in self._measured:
            return 0.0
        return self.CURATE_BASE

    def estimate_present(self) -> float:
        if "present" in self._measured:
            return 0.0
        return self.PRESENT_BASE + self.n_selected_estimate * self.PRESENT_PER_ITEM

    def estimate_normalize_remaining(self, normalize_eta: float) -> float:
        if "normalize" in self._measured:
            return 0.0
        return max(0.0, normalize_eta)

    def total_remaining(self, normalize_eta: float = 0.0) -> float:
        return (
            self.estimate_normalize_remaining(normalize_eta)
            + self.estimate_sanitize()
            + self.estimate_curate()
            + self.estimate_present()
        )

    def sticky_text(self, normalize_eta: float = 0.0, stage_note: str = "") -> str:
        rem = self.total_remaining(normalize_eta)
        line = (
            f"pipeline elapsed {format_duration(self.elapsed)}   "
            f"ETA total → draft {format_duration(rem)}"
        )
        if stage_note:
            return f"{line}\n{stage_note}"
        return line


class StickyETA:
    """
    Keep pipeline elapsed / ETA total pinned at the bottom of the terminal
    while file-level progress lines scroll above.
    """

    def __init__(self, console: Console, pipe_eta: PipelineETA) -> None:
        self.console = console
        self.pipe_eta = pipe_eta
        self._remaining_override: Optional[float] = None
        self._normalize_eta = 0.0
        self._stage_note = ""
        self._live: Optional[Live] = None

    def _remaining(self) -> float:
        if self._remaining_override is not None:
            return self._remaining_override
        return self.pipe_eta.total_remaining(self._normalize_eta)

    def _render(self) -> Panel:
        rem = self._remaining()
        lines = (
            f"pipeline elapsed {format_duration(self.pipe_eta.elapsed)}   "
            f"ETA total → draft {format_duration(rem)}"
        )
        if self._stage_note:
            lines = f"{lines}\n{self._stage_note}"
        return Panel(
            Text(lines),
            title="[bold]Status[/bold]",
            border_style="cyan",
            padding=(0, 1),
        )

    def __enter__(self) -> "StickyETA":
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=8,
            transient=False,
            vertical_overflow="visible",
        )
        self._live.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._live is not None:
            self._live.__exit__(exc_type, exc, tb)
            self._live = None

    def update(
        self,
        normalize_eta: float = 0.0,
        stage_note: str = "",
        remaining_override: Optional[float] = None,
    ) -> None:
        self._normalize_eta = normalize_eta
        self._stage_note = stage_note
        self._remaining_override = remaining_override
        if self._live is not None:
            self._live.update(self._render())

    def log(self, message: str) -> None:
        """Scroll a progress line above the sticky status panel."""
        self.console.print(message)
        if self._live is not None:
            self._live.update(self._render())
