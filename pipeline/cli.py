"""CLI entrypoint — cross-platform (macOS / Windows)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

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
from pipeline.ingest import discover_media
from pipeline.media import ffmpeg_available, save_manifest
from pipeline.normalize import normalize_all
from pipeline.present import build_presentation
from pipeline.sanitize import sanitize_all

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Trip Pic Compiler — sanitize trip media and draft a taste-driven presentation.",
)
console = Console()


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


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
        if Confirm.ask(f"Käytetäänkö olemassa olevaa {prefs_path.name}?", default=True):
            return load_preferences(prefs_path)
    elif example.exists() and Confirm.ask(
        "Ladataanko pohja preferences.example.yaml:sta?", default=True
    ):
        base = load_preferences(example)

    target = FloatPrompt.ask("Tavoitekesto (minuuttia)", default=base.target_duration_min)
    image_sec = FloatPrompt.ask("Sekuntia per kuva", default=base.image_seconds)

    console.print(
        "\n[dim]Kirjoita makuprompti. Tyhjä rivi lopettaa.\n"
        "Voit myös liittää tekstin prompts/examples/taste_fi.txt:stä.[/dim]\n"
    )
    if base.taste_prompt.strip():
        console.print("[dim]Nykyinen prompt (Enter säilyttää):[/dim]")
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
    console.print(f"[green]Tallennettu[/green] → {prefs_path}")
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


@app.command("run")
def run_pipeline(
    input_dir: Optional[Path] = typer.Argument(
        None,
        help="Kansio jossa kuvat/videot (esim. input/romania-2026)",
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
    console.print(f"[bold]Trip Pic Compiler[/bold] v{__version__}\n")

    if input_dir is None:
        raw = Prompt.ask(
            "Mediakansio",
            default=str(root / "input"),
        )
        input_dir = Path(raw)
    input_dir = _resolve(input_dir)

    if output_dir is None:
        output_dir = root / "output" / input_dir.name
    output_dir = _resolve(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prefs_path = _resolve(preferences) if preferences else default_preferences_path()

    if not ffmpeg_available():
        console.print(
            "[yellow]Varoitus:[/yellow] ffmpeg/ffprobe ei löydy PATH:sta. "
            "Videoiden orientointi ja kesto jäävät vajaiksi. "
            "Asenna: macOS `brew install ffmpeg` · Windows `winget install ffmpeg`.\n"
        )

    # --- preferences (personalized layer) ---
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
    items = discover_media(input_dir)
    if not items:
        console.print("[red]Ei tuettuja media-tiedostoja.[/red]")
        raise typer.Exit(code=1)
    n_img = sum(1 for i in items if i.kind == "image")
    n_vid = sum(1 for i in items if i.kind == "video")
    console.print(f"  löytyi {len(items)} ({n_img} kuvaa, {n_vid} videota)")

    # --- normalize ---
    console.print("[bold]2/5 Normalisointi[/bold]  orientointi + metadata")
    if skip_normalize:
        normalized = items
    else:
        normalized = normalize_all(items, output_dir)
    save_manifest(output_dir / "manifest_normalized.json", normalized)

    # --- sanitize ---
    console.print("[bold]3/5 Sanitointi[/bold]  blur + duplikaatit")
    kept, rejected = sanitize_all(normalized, prefs, output_dir)
    save_manifest(
        output_dir / "manifest_sanitized.json",
        kept,
        meta={"rejected": len(rejected)},
    )
    console.print(f"  jäljellä {len(kept)}, hylätty {len(rejected)} → output/.../rejects/")

    # --- curate ---
    console.print("[bold]4/5 Kuratointi[/bold]  kesto + päiväpeitto (+ taste_prompt tallennetaan)")
    selected, meta = curate(kept, prefs)
    save_manifest(output_dir / "manifest_selected.json", selected, meta=meta)
    console.print(
        f"  valittu {meta['selected_count']} · "
        f"arvioitu kesto ~{meta['estimated_duration_min']} min "
        f"(tavoite {prefs.target_duration_min} min)"
    )

    # --- present ---
    console.print("[bold]5/5 Esitys[/bold]  HTML-draft")
    presentation_dir = output_dir / "presentation"
    index_html = build_presentation(selected, prefs, meta, presentation_dir)
    console.print(
        Panel.fit(
            f"[green]Valmis draft[/green]\n"
            f"Avaa selaimessa:\n[bold]{index_html}[/bold]\n\n"
            f"Timeline: {presentation_dir / 'timeline.json'}",
            border_style="green",
        )
    )


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
    for mod in ("PIL", "numpy", "imagehash", "yaml", "typer", "rich"):
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
