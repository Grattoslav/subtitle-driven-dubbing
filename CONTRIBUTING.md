# Contributing

Thanks for considering contributions.

This project is still evolving, but the direction is already clear:
- keep the engine small
- keep the contract explicit
- improve robustness before adding complexity

## Core Principle

The main product is not the GUI.
The main product is:

- `video + subtitles -> dubbing-ready JSON`

Everything else is built on top of that contract.

## Good Contributions

High-value contributions usually improve one of these:
- subtitle matching
- speaker stability
- resumable processing
- soundtrack mixing
- playback clarity
- documentation
- testability

## Low-Value Contributions

Please avoid contributions that mainly add:
- flashy but unclear GUI controls
- overcomplicated architecture
- per-episode manual hacks
- features that only work on one sample video

## Before You Open a PR

Please make sure:
- the change matches the microsystem model
- the code still works on Windows
- the change does not break resumable jobs
- the documentation stays accurate

## Development Notes

Current important files:
- `system/audio_processor.py`
- `system/dubbing_runner.py`
- `system/dabing_gui.py`

Current key artifacts:
- `*.dubbing_prep.json`
- `*.dubbing_segments.json`
- `*.voice_map.json`
- `*.dubbing_job_state.json`

## Reporting Problems

When opening an issue, include:
- what input files you used
- whether subtitles were found automatically
- what target language you used
- the relevant part of `dabing_debug.log`
- the current `dubbing_job_state.json` if the issue is about resume or rendering

## Design Rule

If a change makes the project more impressive but less reliable, it is probably the wrong change.

