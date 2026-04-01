# Subtitle-Driven Dubbing

Subtitle-Driven Dubbing is a small dubbing microsystem that turns:

- a video file
- plus matching subtitles

into:

- structured dubbing JSON
- resumable dubbing jobs
- progressively playable dubbed output

This project is intentionally pragmatic:
- no lip-sync
- no large cast simulation
- no manual per-episode setup as the main workflow

The current goal is simple, reliable, subtitle-driven dubbing with a small voice set, resumable processing, and a selectable target dubbing language.

## What This Project Does

- finds matching subtitles for a video
- uses subtitles as the primary segmentation source
- runs speaker diarization
- assigns simple speaker metadata
- exports dubbing-ready JSON
- generates dubbed speech incrementally from the beginning
- resumes after crashes
- supports progressively playable output while the rest is still rendering

## Core Contract

This repository is best understood as a small engine with a clear interface.

Input:
- `video`
- `subtitles`

Output:
- `dubbing-ready JSON`

Everything else is a layer on top:
- the runner
- progressive rendering
- the GUI
- playback

## Project Structure

### `system/audio_processor.py`

Builds structured dubbing metadata from:
- video
- subtitles

Outputs:
- `*.dubbing_prep.json`
- `*.dubbing_segments.json`
- `*.voice_map.json`
- `*.dubbing_job_state.json`

### `system/dubbing_runner.py`

Consumes dubbing metadata and:
- generates TTS segment by segment
- retries transient TTS failures
- stores resumable job state
- builds progressive output
- renders final outputs

### `system/dabing_gui.py`

Provides a minimal GUI that:
- selects a video
- starts analysis automatically
- starts dubbing automatically
- shows progress
- plays the progressively rendered result

## Current Processing Model

### Subtitle-first segmentation

Primary segmentation source:
- `.srt`

Fallback:
- VAD

This is intentional. Subtitle-driven segmentation is much more practical for dubbing than pure audio-only segmentation.

### Speaker assignment

Current speaker handling:
- pyannote diarization
- subtitle-aligned speaker assignment

The target is not exact character identity.
The target is stable enough speaker grouping for practical male and female voice assignment.

### Voice strategy

Current implementation uses a deliberately small voice set per target language.

Current built-in language registry:
- Czech (`cs`)
- Slovak (`sk`)
- English (`en`)

Each language currently maps to:
- 1 male voice
- 1 female voice
- pitch offset for child-like voices

This is a design choice, not an accident.

## Inputs

Recommended minimum input:
- a video file, for example `.mp4`
- a matching `.srt` file in the same folder

Optional behavior:
- choose a `target_language`
- default target language is currently `cs`

Subtitle lookup currently tries:
- exact same base filename
- underscore/space variants
- single `.srt` in the same folder
- closest normalized filename match

## Outputs

The system creates files next to the video:

- `VIDEO.dubbing_prep.json`
  - raw subtitle-aligned analysis data

- `VIDEO.dubbing_segments.json`
  - dubbing-ready segments

- `VIDEO.voice_map.json`
  - speaker to TTS voice mapping

- `VIDEO.dubbing_job_state.json`
  - resumable job state

- `VIDEO_dub_assets/`
  - generated segment audio
  - progressive output
  - final output

## Installation

This project currently targets Windows and Python 3.11.

Install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

You may also need:
- FFmpeg available on the system
- a Hugging Face token in `.hf_token` for model access when required

Optional:
- set `DUBBING_TARGET_LANGUAGE`

Example:

```powershell
$env:DUBBING_TARGET_LANGUAGE="en"
python system\dabing_gui.py
```

## Quick Start

### GUI

```powershell
python system\dabing_gui.py
```

Or:

```powershell
Start_Dabing.bat
```

Workflow:
1. Put the video and `.srt` in the same folder.
2. Launch the GUI.
3. Select the video.
4. Let analysis run.
5. Let dubbing continue automatically.
6. Start playback once the beginning is ready.

### JSON generation only

If you only want the structured dubbing artifacts, run the analysis step through the GUI or reuse the processor module directly.

The key product of this repository is the generated JSON contract, not only the GUI.

## Language Model

The engine is target-language aware.

That means:
- the generated JSON contains `target_language`
- voice mapping depends on `target_language`
- the dubbing runner selects voices from the language registry

Important:
- the engine does not currently translate subtitle text automatically
- the system assumes the text used for dubbing is already in the target language
- for cross-language dubbing, translated subtitle text or a preprocessing step is still needed

## Resumable Processing

The system stores persistent job state in:

- `VIDEO.dubbing_job_state.json`

This is what allows:
- crash recovery
- continuing from the last completed segment
- progressively playable output

## Known Limits

- diarization still has edge cases
- soundtrack mixing still needs tuning
- no lip-sync
- not intended as a studio-grade voice identity system

This is a practical automated dubbing system, not a final production pipeline.

## Debugging

Primary files to inspect:
- `dabing_debug.log`
- `VIDEO.dubbing_job_state.json`
- `VIDEO_dub_assets/`

Most important state fields:
- `job_status`
- `dub_completed`
- `dub_pending`
- `dub_failed`
- `ready_until`

## Additional Documentation

- [README_DUBBING.md](README_DUBBING.md)
- [docs/dubbing_model.md](docs/dubbing_model.md)
- [docs/quickstart.md](docs/quickstart.md)
- [SUPPORT.md](SUPPORT.md)

## Support

If this project becomes useful, support links can live in:
- [SUPPORT.md](SUPPORT.md)
- `.github/FUNDING.yml`
