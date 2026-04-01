# Dubbing System

A simple automated dubbing pipeline for people who would rather listen than read subtitles.

This repository contains a working pipeline for simple AI dubbing of movies and TV episodes.

It is meant to be reusable by other developers:
- the repository does not include your private keys or tokens
- each adopter brings their own credentials
- the engine can be embedded into another player or UI

The goal is to:
  - take a video file plus subtitles already written in the target dubbing language
  - estimate who is speaking and when
  - assign a simple male or female dubbing voice
  - generate dubbed speech in a selected target language
  - start playback from the beginning before the full episode is finished
  - resume after crashes without starting over

This is not a lip-sync system.
It is not studio dubbing.
It is a practical, resumable dubbing workflow designed to be good enough for comfortable watching without reading subtitles.

## Current Status

This system has already been exercised end-to-end on a long TV episode with:
- video input
- `.srt` subtitles
- subtitle-driven analysis
- speaker diarization
- target-language-aware TTS
- resumable job state
- progressively playable output

The intended workflow is:
- pick a video
- run analysis automatically
- start dubbing automatically
- play the finished beginning while the rest is still rendering
- resume after failure

## Architecture

### `system/audio_processor.py`

Responsibilities:
- extract audio from video
- locate matching subtitles
- run `SRT-first` segmentation
- run pyannote diarization
- assign subtitle-aligned speakers
- estimate `male / female / unknown`
- export working JSON files

Outputs:
- `*.dubbing_prep.json`
- `*.dubbing_segments.json`
- `*.voice_map.json`
- `*.dubbing_job_state.json`

### `system/dubbing_runner.py`

Responsibilities:
- load segment and voice metadata
- generate TTS segment by segment
- retry transient TTS failures
- split overly long TTS text into smaller requests
- create progressive output from the beginning
- resume from saved state
- render final outputs

Current behavior:
- resumes after crashes
- keeps a persistent job state
- produces a progressive output file
- mixes dubbed speech over the original soundtrack

### `system/dabing_gui.py`

Responsibilities:
- minimal user-facing control flow
- choose a video
- automatically start analysis
- automatically start dubbing
- play the progressively rendered dubbed output
- fullscreen playback
- progress display from job state

## Inputs

Recommended minimum input:
  - a video file, for example `.mp4`
  - a matching `.srt` file in the same folder
  - subtitle text already written in the language you want the dubbing to speak

Credential expectation:
  - provide your own Hugging Face token if your model access requires it
  - provide your own TTS or model credentials if you swap backends
  - do not expect this repository to contain reusable private credentials

Optional:
- set the dubbing target language using `DUBBING_TARGET_LANGUAGE`

Subtitle matching strategy:
- exact same base filename
- underscore/space variants
- if there is only one `.srt` in the folder, use it
- otherwise use the closest normalized filename match

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

## Current Voice Strategy

The current setup uses a small voice set per target language.

Current built-in target languages:
- `cs`
- `sk`
- `en`

Child-like voices are approximated using pitch offset.

The goal is not to give every character a unique voice.
The goal is:
- a consistent male dubbing voice
- a consistent female dubbing voice
- speaker assignment that is stable enough for practical dubbing

## What the System Already Does

- process a full episode from the beginning
- let playback start before the entire episode is complete
- continue rendering in the background
- resume after crashes from `dubbing_job_state.json`
- use subtitles as the primary text source
- carry `target_language` in the generated dubbing metadata

## Known Limits

- diarization still has edge cases
- soundtrack mixing still needs tuning
- no lip-sync
- not intended as a studio-grade voice identity system
- no built-in subtitle translation step yet

This is a practical automated dubbing system, not a final production pipeline.

## Recommended Workflow

1. Put the video and `.srt` in the same folder.
2. Launch the GUI.
3. Select the video.
4. Let analysis finish.
5. Let dubbing continue automatically.
6. Test the progressive dubbed output.
7. If the app crashes, relaunch and resume.

Alternative integration model:
1. Generate `dubbing_segments.json`.
2. Read `voice_map.json` and `dubbing_job_state.json`.
3. Plug your own player, queue, or UI on top of the generated JSON contract.

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

## Technical Notes

- the `torchcodec` warning from pyannote is currently tolerated in this project
- deprecated `speechbrain` warnings are not blockers
- occasional `edge_tts` failures must be retried
- long subtitle blocks must be split into smaller TTS requests

## Support

If you publish this project and want people to support your work, add your real funding links in:
- [SUPPORT.md](SUPPORT.md)
- the funding section below

Suggested donation platforms:
- GitHub Sponsors
- Ko-fi
- Buy Me a Coffee
- Patreon

Replace the placeholder links with your own public profiles before publishing.

## Funding

Example section for public repos:

- Sponsor development: `https://github.com/sponsors/YOUR_NAME`
- Support on Ko-fi: `https://ko-fi.com/YOUR_NAME`
- Buy me a coffee: `https://buymeacoffee.com/YOUR_NAME`

## Next Priorities

The most sensible next steps are:
- make the GUI state clearer
- make progressive video output more robust
- keep improving soundtrack mixing under dubbed speech
- show a clear `ready until mm:ss` status
- validate the workflow on multiple unrelated videos, not just a single sample
