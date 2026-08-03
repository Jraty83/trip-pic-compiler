"""CLI entrypoint — cross-platform (macOS / Windows)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, Prompt

from pipeline import __version__
from pipeline.config import (
    Preferences,
    default_preferences_path,
    example_preferences_path,
    load_preferences,
    project_root,
    save_preferences,
)
from pipeline.curate import curate
from pipeline.ingest import collect_scan_roots, discover_media_in_roots
from pipeline.media import MediaItem, ffmpeg_available, save_manifest
from pipeline.normalize import normalize_all
from pipeline.present import build_presentation, repair_presentation_embed
from pipeline.progress import PipelineETA, StageETA, StickyETA, format_duration
from pipeline.sanitize import sanitize_all

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Trip Pic Compiler — sanitize trip media and draft a taste-driven presentation.",
)
console = Console()


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def _format_prefs_panel(prefs: Preferences, title: str) -> Panel:
    taste = (prefs.taste_prompt or "").strip() or "[dim](tyhjä)[/dim]"
    body = (
        f"[bold]target_duration_min[/bold]: {prefs.target_duration_min}\n"
        f"[bold]image_seconds[/bold]: {prefs.image_seconds}\n"
        f"[bold]day_label_format[/bold]: {prefs.day_label_format}\n"
        f"[bold]blur_threshold[/bold]: {prefs.blur_threshold}\n"
        f"[bold]duplicate_hash_distance[/bold]: {prefs.duplicate_hash_distance}\n"
        f"[bold]max_burst_keep[/bold]: {prefs.max_burst_keep}\n\n"
        f"[bold]taste_prompt[/bold]:\n{taste}"
    )
    return Panel(body, title=title, border_style="gold1")


def collect_preferences(prefs_path: Path) -> Preferences:
    """Interactive taste layer — not hardcoded in the engine."""
    console.print(
        Panel.fit(
            "[bold]Maku & kesto[/bold]\n"
            "Geneerinen moottori perkaa median.\n"
            "Seuraavat valinnat personoivat kuratoinnin.",
            border_style="gold1",
        )
    )

    base = Preferences()
    example = example_preferences_path()
    if prefs_path.exists():
        existing = load_preferences(prefs_path)
        console.print(_format_prefs_panel(existing, f"Nykyinen {prefs_path.name}"))
        if Confirm.ask(f"Käytetäänkö yllä olevaa {prefs_path.name}?", default=True):
            return existing
        base = existing
    elif example.exists():
        example_prefs = load_preferences(example)
        console.print(_format_prefs_panel(example_prefs, "preferences.example.yaml"))
        if Confirm.ask("Ladataanko pohja preferences.example.yaml:sta?", default=True):
            base = example_prefs

    target = FloatPrompt.ask("Tavoitekesto (minuuttia)", default=base.target_duration_min)
    image_sec = FloatPrompt.ask("Sekuntia per kuva", default=base.image_seconds)

    console.print(
        "\n[dim]Kirjoita makuprompti. Tyhjä rivi lopettaa.\n"
        "Voit myös liittää tekstin prompts/examples/taste_fi.txt:stä.[/dim]\n"
    )
    if base.taste_prompt.strip():
        console.print("[dim]Nykyinen prompt:[/dim]")
        console.print(base.taste_prompt.strip())
        keep = Confirm.ask("Säilytetäänkö nykyinen taste_prompt?", default=True)
        if keep:
            taste = base.taste_prompt
        else:
            taste = _read_multiline_prompt()
    else:
        taste = _read_multiline_prompt()

    prefs = Preferences(
        target_duration_min=float(target),
        image_seconds=float(image_sec),
        day_label_format=base.day_label_format,
        taste_prompt=taste.strip(),
        blur_threshold=base.blur_threshold,
        duplicate_hash_distance=base.duplicate_hash_distance,
        max_burst_keep=base.max_burst_keep,
    )
    save_preferences(prefs_path, prefs)
    console.print(_format_prefs_panel(prefs, f"Tallennettu → {prefs_path.name}"))
    return prefs


def _read_multiline_prompt() -> str:
    lines = []
    while True:
        try:
            line = Prompt.ask("", default="")
        except (EOFError, KeyboardInterrupt):
            break
        if line == "" and lines:
            break
        if line == "" and not lines:
            continue
        lines.append(line)
    return "\n".join(lines)


def _remaining_kinds(items: List[MediaItem], done: int) -> tuple:
    left = items[done:]
    return (
        sum(1 for i in left if i.kind == "image"),
        sum(1 for i in left if i.kind == "video"),
    )


@app.command("run")
def run_pipeline(
    input_dir: Optional[Path] = typer.Argument(
        None,
        help="Kansio tai .zip (esim. input/romania-2026 tai input/romania.zip)",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Tulostekansio (oletus: output/<input-nimi>)",
    ),
    preferences: Optional[Path] = typer.Option(
        None,
        "--preferences",
        "-p",
        help="Polku preferences.yaml (oletus: ./preferences.yaml)",
    ),
    skip_prefs_prompt: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Älä kysy preferenssejä; käytä tiedostoa tai examplea",
    ),
    skip_normalize: bool = typer.Option(False, help="Ohita normalisointi (debug)"),
) -> None:
    """Aja koko putki: ingest → normalize → sanitize → curate → presentation."""
    root = project_root()
    pipe_eta = PipelineETA()
    console.print(f"[bold]Trip Pic Compiler[/bold] v{__version__}\n")

    if input_dir is None:
        raw = Prompt.ask(
            "Mediakansio tai .zip",
            default=str(root / "input"),
        )
        input_dir = Path(raw)
    input_dir = _resolve(input_dir)

    if output_dir is None:
        stem = input_dir.stem if input_dir.suffix.lower() == ".zip" else input_dir.name
        output_dir = root / "output" / stem
    output_dir = _resolve(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prefs_path = _resolve(preferences) if preferences else default_preferences_path()

    if not ffmpeg_available():
        console.print(
            "[yellow]Varoitus:[/yellow] ffmpeg/ffprobe ei löydy PATH:sta. "
            "Videoiden orientointi ja kesto jäävät vajaiksi. "
            "Asenna: macOS `brew install ffmpeg` · Windows `winget install ffmpeg`.\n"
        )

    if skip_prefs_prompt:
        if prefs_path.exists():
            prefs = load_preferences(prefs_path)
        elif example_preferences_path().exists():
            prefs = load_preferences(example_preferences_path())
            console.print("[dim]Käytetään preferences.example.yaml[/dim]")
        else:
            prefs = Preferences()
    else:
        prefs = collect_preferences(prefs_path)

    # --- ingest ---
    console.print(f"[bold]1/5 Ingest[/bold]  {input_dir}")
    console.print(
        "  [dim]input/ luetaan vain — .zip ja raakamedia säilyvät muuttumattomina; "
        "purku menee output/.../_extracted/[/dim]"
    )
    roots = collect_scan_roots(
        input_dir,
        output_dir,
        on_progress=lambda msg: console.print(f"  {msg}"),
    )
    items = discover_media_in_roots(roots)
    if not items:
        console.print("[red]Ei tuettuja media-tiedostoja.[/red]")
        raise typer.Exit(code=1)
    n_img = sum(1 for i in items if i.kind == "image")
    n_vid = sum(1 for i in items if i.kind == "video")
    pipe_eta.set_counts(n_img, n_vid, prefs.target_duration_min, prefs.image_seconds)
    console.print(f"  löytyi {len(items)} ({n_img} kuvaa, {n_vid} videota)")

    with StickyETA(console, pipe_eta) as status:
        status.update(normalize_eta=len(items) * 1.0, stage_note="stage: ingest done")

        # --- normalize ---
        console.print("[bold]2/5 Normalisointi[/bold]  orientointi + metadata")
        stage = StageETA(len(items), "normalize")
        t_norm = time.monotonic()

        def on_norm(idx: int, total: int, name: str, detail: str, dur: float) -> None:
            stage.record(name, detail, dur)
            rem_i, rem_v = _remaining_kinds(items, idx)
            rem = stage.eta_remaining(rem_i, rem_v)
            status.log(f"  {stage.file_line(rem_i, rem_v)}")
            status.update(
                normalize_eta=rem,
                stage_note=f"stage: normalize · {idx}/{total}",
            )

        if skip_normalize:
            normalized = items
        else:
            normalized = normalize_all(items, output_dir, on_progress=on_norm)
        pipe_eta.mark_stage("normalize", time.monotonic() - t_norm)
        save_manifest(output_dir / "manifest_normalized.json", normalized)
        status.log(
            f"  valmis: {len(normalized)} · stage {format_duration(pipe_eta._measured['normalize'])}"
        )
        status.update(stage_note="stage: normalize done")

        # --- sanitize ---
        console.print("[bold]3/5 Sanitointi[/bold]  blur + duplikaatit")
        t_san = time.monotonic()
        san_stage = StageETA(len(normalized) * 2, "sanitize")

        def on_san(idx: int, total: int, name: str, detail: str, dur: float) -> None:
            san_stage.record(name, detail, dur)
            # Log sparsely so the terminal stays readable; sticky ETA always updates.
            if san_stage.done == 1 or san_stage.done % 25 == 0 or detail in {
                "reject_blur",
                "duplicate",
                "error",
            }:
                status.log(
                    f"  [{san_stage.done}] {detail}: {name}  ({format_duration(dur)})"
                )
            approx_left = max(0.0, pipe_eta.estimate_sanitize() - san_stage.elapsed)
            rem = approx_left + pipe_eta.estimate_curate() + pipe_eta.estimate_present()
            status.update(
                stage_note=(
                    f"stage: sanitize · processed {san_stage.done} · "
                    f"stage left ~{format_duration(approx_left)}"
                ),
                remaining_override=rem,
            )
        kept, rejected = sanitize_all(normalized, prefs, output_dir, on_progress=on_san)
        pipe_eta.mark_stage("sanitize", time.monotonic() - t_san)
        save_manifest(
            output_dir / "manifest_sanitized.json",
            kept,
            meta={"rejected": len(rejected)},
        )
        status.log(
            f"  jäljellä {len(kept)}, hylätty {len(rejected)} · "
            f"stage {format_duration(pipe_eta._measured['sanitize'])}"
        )
        status.update(stage_note="stage: sanitize done")

        # --- curate ---
        console.print(
            "[bold]4/5 Kuratointi[/bold]  kesto + päiväpeitto (+ taste_prompt tallennetaan)"
        )
        t_cur = time.monotonic()
        selected, meta = curate(kept, prefs)
        pipe_eta.mark_stage("curate", time.monotonic() - t_cur)
        pipe_eta.n_selected_estimate = len(selected)
        save_manifest(output_dir / "manifest_selected.json", selected, meta=meta)
        status.log(
            f"  valittu {meta['selected_count']} "
            f"({meta.get('selected_images', '?')} kuvaa, "
            f"{meta.get('selected_videos', '?')} videota) · "
            f"arvioitu kesto ~{meta['estimated_duration_min']} min "
            f"(tavoite {prefs.target_duration_min} min) · "
            f"stage {format_duration(pipe_eta._measured['curate'])}"
        )
        status.update(stage_note="stage: curate done")

        # --- present ---
        console.print("[bold]5/5 Esitys[/bold]  HTML-draft")
        t_pre = time.monotonic()
        presentation_dir = output_dir / "presentation"
        index_html = build_presentation(selected, prefs, meta, presentation_dir)
        pipe_eta.mark_stage("present", time.monotonic() - t_pre)
        status.update(stage_note="stage: present done")

    console.print(
        Panel.fit(
            f"[green]Valmis draft[/green]\n"
            f"[bold]{index_html}[/bold]\n\n"
            f"Timeline: {presentation_dir / 'timeline.json'}\n"
            f"Valinta: {meta.get('selected_images', '?')} kuvaa + "
            f"{meta.get('selected_videos', '?')} videota · "
            f"~{meta.get('estimated_duration_min', '?')} min\n"
            f"Kokonaiskesto (ajo): {format_duration(pipe_eta.elapsed)}",
            border_style="green",
        )
    )

    if Confirm.ask("Avataanko esitys selaimessa?", default=True):
        try:
            import webbrowser

            webbrowser.open(index_html.as_uri())
            console.print("[green]Avattu selaimeen.[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]Selainta ei voitu avata:[/yellow] {exc}")
            console.print(f"Avaa manuaalisesti: {index_html}")
    else:
        console.print(f"[dim]OK — avaa myöhemmin:[/dim] {index_html}")
        console.print("[dim]tai:[/dim] python -m pipeline open " + str(presentation_dir))

@app.command("open")
def open_presentation(
    presentation_dir: Path = typer.Argument(
        ...,
        help="Presentation folder or index.html path",
    ),
) -> None:
    """Repair file:// embed if needed and open the draft in a browser."""
    import webbrowser

    path = _resolve(presentation_dir)
    if path.name == "index.html":
        folder = path.parent
    else:
        folder = path
    index_html = repair_presentation_embed(folder)
    webbrowser.open(index_html.as_uri())
    console.print(f"[green]Opened[/green] {index_html}")


@app.command("prefs")
def prefs_cmd(
    path: Optional[Path] = typer.Option(None, "--path", "-p"),
) -> None:
    """Luo tai päivitä preferences.yaml interaktiivisesti."""
    prefs_path = _resolve(path) if path else default_preferences_path()
    collect_preferences(prefs_path)


@app.command("doctor")
def doctor() -> None:
    """Tarkista riippuvuudet (Python-paketit + ffmpeg)."""
    console.print(f"Trip Pic Compiler v{__version__}")
    console.print(f"Project root: {project_root()}")
    console.print(f"ffmpeg/ffprobe: {'OK' if ffmpeg_available() else 'PUUTTUU'}")
    for mod in ("PIL", "numpy", "imagehash", "yaml", "typer", "rich", "pillow_heif"):
        try:
            __import__(mod if mod != "PIL" else "PIL")
            console.print(f"  {mod}: OK")
        except ImportError:
            console.print(f"  {mod}: [red]PUUTTUU[/red] — pip install -r requirements.txt")


@app.callback()
def main() -> None:
    """Trip Pic Compiler."""


if __name__ == "__main__":
    app()
