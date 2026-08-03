# Trip Pic Compiler

Local engine for trip photos and videos: normalize, sanitize, curate to your taste, and produce an HTML presentation draft (typically 30–60 minutes).

**Public repo = code only.** Your media, `preferences.yaml`, and API keys stay on your machine (gitignored).

Works on **macOS** and **Windows** with the same Python CLI.

---

## Pipeline stages

| Stage | Type | What it does |
|--------|------|----------------|
| Ingest | generic | Finds images/videos in a folder (or unpacks a `.zip` first) |
| Normalize | generic | Orientation, EXIF/time, videos → mp4 with audio |
| Sanitize | generic | Blur removal, near-duplicate removal |
| Preferences | **personalized** | You provide taste prompt + target duration |
| Curate | engine + taste | v0.1 heuristic + day coverage; `taste_prompt` stored for vision API later |
| Present | generic | HTML slideshow, ~8 s/image, videos with audio, day label `dd/mm/yyyy` |

---

## Requirements

- Python **3.9+**
- **ffmpeg** + **ffprobe** (recommended for video)

### ffmpeg

**macOS**
```bash
brew install ffmpeg
```

**Windows**
```bash
winget install ffmpeg
```

Confirm `ffmpeg` and `ffprobe` are on your PATH (open a new terminal after install).

---

## Setup

```bash
git clone <this-repo-url>
cd trip-pic-compiler

python3 -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Check the environment:
```bash
python -m pipeline doctor
```

---

## Pilot a trip (e.g. Romania)

1. Download the album from Google Photos to your machine.
2. Either extract into a folder, or keep the archive as-is:
   ```text
   input/romania-2026/          # extracted files
   # or
   input/romania.zip            # untouched archive
   ```
3. Run the pipeline (asks for taste + duration interactively):
   ```bash
   python -m pipeline run input/romania-2026
   ```
   Or point at a zip directly:
   ```bash
   python -m pipeline run input/romania.zip
   ```
   Zips inside `input/` are also auto-extracted to `output/<name>/_extracted/`.
   **Your original files and `.zip` under `input/` are never modified** — safe to re-run or re-download raw data from the cloud.
4. Open in a browser:
   ```text
   output/romania-2026/presentation/index.html
   ```

Non-interactive (uses `preferences.yaml` or the example file):
```bash
python -m pipeline run input/romania-2026 -y
```

Create/update preferences only:
```bash
python -m pipeline prefs
```

### Progress & ETA

During long stages a **sticky status panel** stays at the bottom with:

- `pipeline elapsed`
- `ETA total → draft`

File-level lines scroll above it. Sanitize logs sparsely (every 25 items + rejects).

### Viewing the draft

Chrome blocks `fetch("timeline.json")` on `file://`. The generator **embeds** the timeline into `index.html`, so opening the file directly works.

```bash
python -m pipeline open output/romania-2026/presentation
```

Or open `presentation/index.html` in a browser after a fresh `run`.

Already-normalized outputs are reused on re-run (`reuse` / skip work when possible).

---

## Preferences (taste layer)

Copy the template or let the CLI create one:

```bash
cp preferences.example.yaml preferences.yaml
```

`preferences.yaml` is **gitignored**. Useful fields:

- `target_duration_min` — e.g. 45
- `image_seconds` — e.g. 8
- `taste_prompt` — free text (prefer / avoid)
- `day_label_format` — default `%d/%m/%Y`
- sanitize knobs: `blur_threshold`, `duplicate_hash_distance`

Example taste prompt: `prompts/examples/taste_fi.txt`

---

## Outputs (`output/...`, not committed)

```text
output/<trip>/
  _extracted/          # unpacked zips (derived; safe to delete)
  normalized/          # oriented media
  rejects/             # blur / duplicates
  manifest_*.json      # intermediate results
  presentation/
    index.html         # open this
    timeline.json
    media/
```

---

## Privacy

Do not commit:

- `input/` (media / zips)
- `output/`
- `preferences.yaml`
- `.env`

The public repo only contains the engine, templates, and example prompts.

---

## Roadmap

- Vision-API curation using `taste_prompt`
- Keep/drop feedback loop to refine preferences
- Optional single rendered MP4 export

---

## License

MIT
