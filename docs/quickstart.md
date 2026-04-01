# Quick Start

## 1. Put input files together

Place these in the same folder:
- a video file
- a matching `.srt` subtitle file

Example:

```text
movie.mp4
movie.srt
```

## 2. Install dependencies

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Optional target language selection:

```powershell
$env:DUBBING_TARGET_LANGUAGE="cs"
```

Currently supported voice registries:
- `cs`
- `sk`
- `en`

Credentials:
- if a model backend needs access credentials, provide your own
- this repository does not ship public reusable private keys or tokens
- keep local secrets out of git

## 3. Launch the GUI

```powershell
python system\dabing_gui.py
```

or:

```powershell
Start_Dabing.bat
```

## 4. Select a video

The GUI should:
- run analysis automatically
- create dubbing JSON files
- start the dubbing job automatically
- enable playback once the beginning is ready

Important:
- the selected `DUBBING_TARGET_LANGUAGE` controls TTS voice selection
- it does not automatically translate subtitle text
- the expected input is a subtitle file already written in the desired dubbing language

## 5. Resume after interruption

If the app stops, launch it again and select the same video.

The system uses:
- `VIDEO.dubbing_job_state.json`

to continue instead of starting from zero.

## Generated Files

After analysis you should see:
- `VIDEO.dubbing_prep.json`
- `VIDEO.dubbing_segments.json`
- `VIDEO.voice_map.json`
- `VIDEO.dubbing_job_state.json`

During dubbing you should see:
- `VIDEO_dub_assets/`

## Engine-first usage

You do not have to use the built-in GUI.

The core reusable contract is:
- input: `video + target-language subtitles`
- output: `dubbing_prep.json`, `dubbing_segments.json`, `voice_map.json`, `dubbing_job_state.json`

This lets you build your own:
- player
- queue runner
- web UI
- integration layer

## Troubleshooting

Check:
- `dabing_debug.log`
- `VIDEO.dubbing_job_state.json`

Common non-blocking warnings:
- `torchcodec` warnings from pyannote
- deprecated warnings from speechbrain
