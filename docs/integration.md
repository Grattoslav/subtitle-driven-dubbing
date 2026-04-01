# Integration Model

This project is designed to be used as a small dubbing engine, not only as the bundled GUI.

## Core Contract

Input:
- a video file
- a subtitle file already written in the target dubbing language

Output:
- `VIDEO.dubbing_prep.json`
- `VIDEO.dubbing_segments.json`
- `VIDEO.voice_map.json`
- `VIDEO.dubbing_job_state.json`
- generated audio/video assets in `VIDEO_dub_assets/`

## Bring Your Own Credentials

This repository must remain reusable and safe to publish.

That means:
- no personal API keys in git
- no personal tokens in git
- no expectation that another user can reuse your local secrets

Each adopter is expected to provide:
- their own Hugging Face token if required by the selected model access path
- their own TTS or model credentials if they replace built-in backends

## Typical Integration

An adopter can:
1. run analysis to generate the dubbing JSON artifacts
2. read `dubbing_segments.json`
3. read `voice_map.json`
4. track progress using `dubbing_job_state.json`
5. plug their own player or frontend on top of the generated outputs

## What Another App Needs To Know

If you are building a wrapper or another UI, the important files are:
- `dubbing_segments.json` for timed dubbing content
- `voice_map.json` for voice assignment
- `dubbing_job_state.json` for progress and resume state

The built-in GUI is only one possible frontend.
The engine and JSON contract are the real reusable product surface.
