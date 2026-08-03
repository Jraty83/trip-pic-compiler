# Trip Pic Compiler

Paikallinen moottori matkakuville ja -videoille: normalisoi, sanitoi, kuratoi makusi mukaan ja tuottaa HTML-esitysdraftin (30–60 min).

**Julkinen repo = vain koodi.** Kuvat, videot, `preferences.yaml` ja API-avaimet pysyvät koneellasi (gitignore).

Toimii **macOS** ja **Windows** — sama Python-CLI molemmissa.

---

## Mitä pipeline tekee

| Vaihe | Tyyppi | Mitä |
|--------|--------|------|
| Ingest | geneerinen | Löytää kuvat/videot kansiosta |
| Normalisointi | geneerinen | Orientointi, EXIF/aika, videot → mp4 + ääni |
| Sanitointi | geneerinen | Suttuisten poisto, near-duplikaatit |
| Preferenssit | **personoitu** | Sinä annat makupromptin + keston |
| Kuratointi | moottori + maku | v0.1: heuristic + päiväpeitto; `taste_prompt` valmiina vision-API:lle |
| Esitys | geneerinen | HTML-slideshow, ~8 s/kuva, videot äänellä, päiväleima `dd/mm/yyyy` |

---

## Vaatimukset

- Python **3.9+**
- **ffmpeg** + **ffprobe** (suositus videoille)

### ffmpeg

**macOS**
```bash
brew install ffmpeg
```

**Windows**
```bash
winget install ffmpeg
```
Varmista että `ffmpeg` ja `ffprobe` löytyvät PATH:sta (uusi terminaali asennuksen jälkeen).

---

## Asennus

```bash
git clone <tämän-repon-url>
cd trip-pic-compiler

python3 -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Tarkista ympäristö:
```bash
python -m pipeline doctor
```

---

## Romanian (tai muun) matkan pilotointi

1. Lataa albumi Google Kuvista koneelle.
2. Kopioi tiedostot esim. kansioon:
   ```text
   input/romania-2026/
   ```
3. Aja putki (kysyy makua ja kestoa interaktiivisesti):
   ```bash
   python -m pipeline run input/romania-2026
   ```
4. Avaa selaimessa:
   ```text
   output/romania-2026/presentation/index.html
   ```

Ilman kysymyksiä (käyttää `preferences.yaml` tai examplea):
```bash
python -m pipeline run input/romania-2026 -y
```

Pelkkä preferenssien luonti/päivitys:
```bash
python -m pipeline prefs
```

---

## Preferenssit (maku-kerros)

Kopioi pohja tai anna CLI:n luoda:

```bash
cp preferences.example.yaml preferences.yaml
```

`preferences.yaml` on **gitignored**. Esimerkkikentät:

- `target_duration_min` — esim. 45
- `image_seconds` — esim. 8
- `taste_prompt` — vapaa teksti (suosi / vältä)
- `day_label_format` — oletus `%d/%m/%Y`
- sanitointirajat: `blur_threshold`, `duplicate_hash_distance`

Esimerkkimakupromptti: `prompts/examples/taste_fi.txt`

---

## Tulosteet (`output/...`, ei gittiin)

```text
output/<matka>/
  normalized/          # oikaistut mediat
  rejects/             # blur / duplikaatit
  manifest_*.json      # välitulokset
  presentation/
    index.html         # avaa tämä
    timeline.json
    media/
```

---

## Tietosuoja

Älä commitoi:

- `input/` (media)
- `output/`
- `preferences.yaml`
- `.env`

Julkisessa repossa on vain moottori, templatet ja esimerkkipromptit.

---

## Seuraavat askeleet (roadmap)

- Vision-API-kuratointi käyttäen `taste_prompt`ia
- HEIC-tuki (`pillow-heif`) oletuksena
- Keep/drop-palaute → preferenssien hienosäätö
- Yksi renderöity MP4-export (valinnainen)

---

## Lisenssi

MIT
