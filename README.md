# Subtitle-Driven Dubbing

A small dubbing microsystem for turning:

- a video file
- plus matching subtitles

into:

- structured dubbing JSON
- resumable dubbing jobs
- progressively playable dubbed output

This project is intentionally pragmatic. It is not a lip-sync system and it does not try to generate a unique voice for every character. The current goal is reliable, resumable, subtitle-driven dubbing with a small voice set.

## Core Idea

The system should be understood as a small engine with a clear contract:

Input:
- `video`
- `subtitles`

Output:
- `dubbing-ready JSON`

Everything else is a layer on top:
- runner
- progressive rendering
- GUI
- playback

## What It Does

- finds matching subtitles for a video
- uses subtitles as the primary segmentation source
- runs speaker diarization
- assigns simple speaker metadata
- exports structured dubbing JSON
- runs dubbing incrementally from the beginning
- resumes after crashes
- supports progressively playable output while the rest is still rendering

## Current Architecture

### `system/audio_processor.py`

Generates structured dubbing metadata from:
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

Minimal user-facing shell that:
- selects a video
- starts analysis
- starts dubbing
- shows progress
- plays the progressively rendered result

## Subtitle Matching

Subtitle lookup is automatic and currently tries:
- exact same base filename
- underscore/space variants
- single `.srt` file in the same folder
- closest normalized filename match

## Current Voice Strategy

The current implementation uses a deliberately small voice set:
- 1 Czech male voice
- 1 Czech female voice
- pitch offset for child-like voices

This is a feature, not a limitation by accident. The current target is practical automatic dubbing, not full cast voice acting.

## Repository Model

This repo is meant to be treated as a microsystem:

1. `video + subtitles -> dubbing JSON`
2. `dubbing JSON -> dubbed output`

That separation is intentional. It keeps the engine testable and makes the GUI replaceable.

See:
- [README_DUBBING.md](README_DUBBING.md)
- [docs/dubbing_model.md](docs/dubbing_model.md)
- [SUPPORT.md](SUPPORT.md)

## Publish Checklist

Before making the repo public:
- remove private local secrets
- confirm `.gitignore` excludes generated assets and local tokens
- replace funding placeholders in `SUPPORT.md`
- add your real project name and demo material

## Support

If this project becomes public and useful, support links can live in:
- [SUPPORT.md](SUPPORT.md)
- `.github/FUNDING.yml`

