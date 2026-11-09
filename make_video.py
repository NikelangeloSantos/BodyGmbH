#!/usr/bin/env python3
"""
Die Körper GmbH – Folge 1: Kaffee
Baut aus den Flow-Clips im Repo das fertige Video – OHNE eingebrannte Schrift
(Texte und Untertitel kommen später in TikTok dazu).

  1. erzeugt die Sprecherstimme über ElevenLabs (Stimme TUKJhQmz3RPYBNAgC5A1)
  2. bringt alle Clips auf 1080x1920 (9:16), 30 fps und schneidet sie aneinander
  3. legt den Sprecher darüber und senkt dabei den Originalton ab
  4. gleicht die Lautstärke an (TikTok-Niveau)
  5. schreibt texte_fuer_tiktok.txt mit den Zeitpunkten für deine Texte

Voraussetzungen: Python 3.8+, ffmpeg + ffprobe im PATH,
Umgebungsvariable ELEVENLABS_API_KEY.
Fertige Sprecherdateien in audio/sprecherN.mp3 werden wiederverwendet
(kein neuer API-Aufruf). Zum Neu-Generieren: Ordner audio/ löschen.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ------------------------------------------------------------------ Einstellungen
VOICE_ID = "TUKJhQmz3RPYBNAgC5A1"
MODEL_ID = "eleven_multilingual_v2"
VOICE_SETTINGS = {"stability": 0.65, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}

AUSGABE = "koerper_gmbh_folge1_kaffee.mp4"
BREITE, HOEHE, FPS = 1080, 1920, 30
ORIGINALTON_BEI_SPRECHER = 0.30   # Lautstärke der Clips, während der Sprecher redet (1.0 = voll)
ORIGINALTON_SONST = 1.0
SPRECHER_LAUTSTAERKE = 1.0
MIN_PAUSE = 0.25                  # Mindestabstand zwischen zwei Sprecherzeilen (s)

# Reihenfolge der Clips. "datei" = ein eindeutiger Teil des Dateinamens.
# "kuerzen" = Clip nach so vielen Sekunden abschneiden (None = ganzer Clip).
CLIPS = [
    {"name": "kueche",       "datei": "Person_sipping_coffee_in_kitchen",   "kuerzen": None},  # Szene 1
    {"name": "adenosin",     "datei": "Blob_characters_entering_office",    "kuerzen": None},  # Szene 2
    {"name": "koffein",      "datei": "Coffee_beans_taking_office_chairs",  "kuerzen": None},  # Szene 3
    {"name": "chef_wach",    "datei": "Character_runs_into_room",           "kuerzen": None},  # Szene 4
    {"name": "uhr",          "datei": "Clock_advancing_and_cuckoo_jumping", "kuerzen": None},  # Übergang
    {"name": "schichtende",  "datei": "Coffee_characters_leave_and_enter",  "kuerzen": None},  # Szene 5
    {"name": "mensch_muede", "datei": "Man_typing_then_becoming_tired",     "kuerzen": None},  # außen: Folge sichtbar
    {"name": "einschlafen",  "datei": "Characters_falling_asleep_in_office", "kuerzen": None},  # Szene 6, Pointe
]

# Sprecherzeilen: "bei" = Clip-Name, "ab" = Sekunden nach Beginn dieses Clips.
# Läuft eine Zeile noch, schiebt das Skript die nächste automatisch nach hinten.
SPRECHER = [
    {"bei": "kueche",      "ab": 0.3, "text": "7 Uhr morgens. Erster Kaffee. Und in deinem Kopf bricht Chaos aus."},
    {"bei": "adenosin",    "ab": 0.3, "text": "Das ist Adenosin. Je länger du wach bist, desto mehr davon sammelt sich an."},
    {"bei": "koffein",     "ab": 0.3, "text": "Koffein sieht Adenosin so ähnlich, dass es auf dieselben Plätze passt. Nur macht es nicht müde."},
    {"bei": "chef_wach",   "ab": 1.8, "text": "Aber die Müdigkeit ist nicht weg. Sie wird nur nicht mehr gemeldet."},
    {"bei": "schichtende", "ab": 0.3, "text": "Nach etwa fünf Stunden ist rund die Hälfte des Koffeins abgebaut."},
    {"bei": "einschlafen", "ab": 0.3, "text": "Und die aufgestaute Müdigkeit meldet sich zurück."},
]

# Texte, die du in TikTok einfügen willst (landen nur in texte_fuer_tiktok.txt).
EINBLENDUNGEN = [
    {"bei": "kueche",      "ab": 0.0, "text": "Was in deinem Körper passiert, wenn du Kaffee trinkst"},
    {"bei": "uhr",         "ab": 0.0, "text": "5 Stunden später"},
    {"bei": "einschlafen", "ab": 5.0, "text": "Was soll die Körper GmbH als Nächstes erleben?"},
]
# ---------------------------------------------------------------------------------

ORDNER = Path(__file__).resolve().parent
AUDIO = ORDNER / "audio"
ARBEIT = ORDNER / "_build"
VIDEO_ENDUNGEN = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def fehler(text):
    print(f"\nFEHLER: {text}")
    sys.exit(1)


def lauf(befehl):
    ergebnis = subprocess.run(befehl, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if ergebnis.returncode != 0:
        print(ergebnis.stderr[-3000:])
        fehler("ffmpeg ist abgebrochen (Meldung oben).")
    return ergebnis


def dauer(datei):
    return float(lauf(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                       "-of", "default=nw=1:nk=1", str(datei)]).stdout.strip())


def hat_ton(datei):
    return bool(lauf(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                      "stream=index", "-of", "csv=p=0", str(datei)]).stdout.strip())


def finde(teil):
    treffer = [p for p in ORDNER.rglob("*")
               if p.suffix.lower() in VIDEO_ENDUNGEN and teil.lower() in p.name.lower()
               and "_build" not in p.parts and ".git" not in p.parts and p.name != AUSGABE]
    if not treffer:
        fehler(f"Kein Clip gefunden, der '{teil}' im Namen hat.")
    if len(treffer) > 1:
        print(f"  Hinweis: mehrere Dateien mit '{teil}', nehme {treffer[0].name}")
    return treffer[0]


def erzeuge_stimme(nr, text):
    AUDIO.mkdir(exist_ok=True)
    ziel = AUDIO / f"sprecher{nr}.mp3"
    if ziel.exists() and ziel.stat().st_size > 1000:
        print(f"  Sprecher {nr}: vorhanden ({dauer(ziel):.1f} s), wird wiederverwendet")
        return ziel
    schluessel = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not schluessel:
        fehler("ELEVENLABS_API_KEY ist nicht gesetzt.")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}?output_format=mp3_44100_128"
    daten = json.dumps({"text": text, "model_id": MODEL_ID,
                        "voice_settings": VOICE_SETTINGS}).encode("utf-8")
    anfrage = urllib.request.Request(url, data=daten, method="POST", headers={
        "xi-api-key": schluessel, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(anfrage, timeout=120) as antwort:
            ziel.write_bytes(antwort.read())
    except urllib.error.HTTPError as e:
        fehler(f"ElevenLabs antwortet mit {e.code}: {e.read().decode('utf-8', 'ignore')[:400]}")
    except urllib.error.URLError as e:
        fehler(f"ElevenLabs nicht erreichbar: {e.reason}")
    print(f"  Sprecher {nr}: erzeugt ({dauer(ziel):.1f} s)")
    return ziel


def normiere(nr, clip, quelle):
    laenge = dauer(quelle)
    if clip["kuerzen"]:
        laenge = min(laenge, clip["kuerzen"])
    ziel = ARBEIT / f"teil{nr:02d}.mp4"
    befehl = ["ffmpeg", "-y", "-i", str(quelle)]
    ton = "[0:a]"
    if not hat_ton(quelle):
        befehl += ["-f", "lavfi", "-t", f"{laenge}", "-i", "anullsrc=r=48000:cl=stereo"]
        ton = "[1:a]"
    befehl += ["-filter_complex",
               f"[0:v]scale={BREITE}:{HOEHE}:force_original_aspect_ratio=increase,"
               f"crop={BREITE}:{HOEHE},fps={FPS},setsar=1,format=yuv420p[v];"
               f"{ton}aformat=sample_rates=48000:channel_layouts=stereo[a]",
               "-map", "[v]", "-map", "[a]", "-t", f"{laenge:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
               "-c:a", "aac", "-b:a", "192k", str(ziel)]
    lauf(befehl)
    echte_laenge = dauer(ziel)
    print(f"  {nr}. {clip['name']:<13} {quelle.name[:45]:<45} {echte_laenge:4.1f} s")
    return ziel, echte_laenge


def mmss(t):
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:04.1f}"


def main():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            fehler(f"{tool} ist nicht installiert oder nicht im PATH.")
    ARBEIT.mkdir(exist_ok=True)

    print("1/4 Clips vorbereiten")
    starts, teile, t = {}, [], 0.0
    for i, clip in enumerate(CLIPS, 1):
        teil, laenge = normiere(i, clip, finde(clip["datei"]))
        starts[clip["name"]] = t
        teile.append(teil)
        t += laenge
    video_laenge = t

    print("2/4 Sprecherstimme (ElevenLabs)")
    zeilen, frei_ab = [], 0.0
    for nr, z in enumerate(SPRECHER, 1):
        if z["bei"] not in starts:
            fehler(f"Sprecherzeile {nr}: Clip '{z['bei']}' gibt es nicht in CLIPS.")
        datei = erzeuge_stimme(nr, z["text"])
        start = max(starts[z["bei"]] + z["ab"], frei_ab)
        if start > starts[z["bei"]] + z["ab"] + 0.05:
            print(f"    -> Zeile {nr} um {start - starts[z['bei']] - z['ab']:.1f} s nach hinten "
                  f"geschoben, weil die vorige noch läuft")
        ende = start + dauer(datei)
        zeilen.append((nr, datei, start, ende, z["text"]))
        frei_ab = ende + MIN_PAUSE
    gesamt = max(video_laenge, zeilen[-1][3] + 0.8)
    verlaengern = gesamt - video_laenge

    print("3/4 Zusammenschneiden und Ton mischen")
    liste = ARBEIT / "liste.txt"
    liste.write_text("".join(f"file '{p.name}'\n" for p in teile), encoding="utf-8")
    roh = ARBEIT / "roh.mp4"
    lauf(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy", str(roh)])

    bedingung = "+".join(f"between(t,{s:.2f},{e:.2f})" for (_, _, s, e, _) in zeilen)
    filter_teile = [f"[0:a]volume='if({bedingung},{ORIGINALTON_BEI_SPRECHER},{ORIGINALTON_SONST})'"
                    f":eval=frame,apad=whole_dur={gesamt:.3f}[o]"]
    mix = "[o]"
    for i, (_, _, s, _, _) in enumerate(zeilen, 1):
        ms = int(s * 1000)
        filter_teile.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                            f"volume={SPRECHER_LAUTSTAERKE},adelay={ms}|{ms}[s{i}]")
        mix += f"[s{i}]"
    filter_teile.append(f"{mix}amix=inputs={len(zeilen) + 1}:duration=first:normalize=0,"
                        f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    video_filter = (f"[0:v]tpad=stop_mode=clone:stop_duration={verlaengern:.3f}[v]"
                    if verlaengern > 0.01 else "[0:v]null[v]")
    if verlaengern > 0.01:
        print(f"  Hinweis: letzter Satz ist länger als das Bild, letztes Bild wird "
              f"{verlaengern:.1f} s gehalten")

    befehl = ["ffmpeg", "-y", "-i", str(roh)]
    for (_, datei, _, _, _) in zeilen:
        befehl += ["-i", str(datei)]
    befehl += ["-filter_complex", video_filter + ";" + ";".join(filter_teile),
               "-map", "[v]", "-map", "[a]", "-t", f"{gesamt:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(ORDNER / AUSGABE)]
    lauf(befehl)

    print("4/4 Zeitplan für TikTok-Texte schreiben")
    text = ["DIE KÖRPER GMBH – FOLGE 1: KAFFEE",
            f"Videolänge: {mmss(gesamt)}", "",
            "EINBLENDUNGEN (groß, oben im Bild)"]
    for e in EINBLENDUNGEN:
        text.append(f"  ab {mmss(starts[e['bei']] + e['ab'])}  {e['text']}")
    text += ["", "SPRECHER (Untertitel)"]
    for (nr, _, s, e, satz) in zeilen:
        text.append(f"  {mmss(s)} – {mmss(e)}  {satz}")
    text += ["", "CLIPS"]
    for clip in CLIPS:
        text.append(f"  ab {mmss(starts[clip['name']])}  {clip['name']}")
    (ORDNER / "texte_fuer_tiktok.txt").write_text("\n".join(text) + "\n", encoding="utf-8")

    print(f"\nFertig: {ORDNER / AUSGABE}  ({gesamt:.1f} s)")
    print(f"Zeitplan für deine Texte: {ORDNER / 'texte_fuer_tiktok.txt'}")


if __name__ == "__main__":
    main()
