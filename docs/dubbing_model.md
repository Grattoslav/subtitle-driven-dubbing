# Working Model

This file is the current source of truth for the project direction.

## Problem We Are Solving

We want to automatically create simple dubbing for movies and TV episodes so that:
- playback can start as early as possible
- lip-sync is not required
- male and female voices are assigned well enough for practical listening
- the system can recover after failure

## Product Model

The intended user flow is:
- choose a video
- if subtitles exist, use them as the dubbing text source
- run analysis automatically
- start dubbing automatically
- allow playback once the beginning is ready
- continue rendering in the background
- save a final complete output when done

Core input contract:
- the video can be in any spoken language
- the subtitle file should already be written in the target dubbing language
- subtitle translation is upstream of this engine, not part of the core runtime contract

## Technical Model

### Segmentation

Primary segmentation:
- `.srt`

Fallback:
- VAD

Reason:
- subtitles are more stable than pure audio segmentation
- subtitle-first gives better practical dubbing alignment

### Speaker Model

We use:
- pyannote diarization
- subtitle-aligned speaker assignment

We do not require:
- exact identity of every character

We do require:
- stable enough speaker separation inside scenes
- usable grouping for a small dubbing voice set

### Voice Model

Current simplification:
- 1 Czech male voice
- 1 Czech female voice
- child-like voices approximated with pitch offset

This is intentional.
The goal is robustness, not a large acting cast.

### State Model

Job state is stored in JSON.

This is essential.
The pipeline must not be a one-shot script with no memory.

We must always know:
- what is finished
- what is pending
- what failed
- where to resume

### Playback Model

We do not want a trailer-like preview.
We want:
- the same episode
- from the beginning
- progressively completed over time

So the playback model is:
- a growing output
- plus a final completed output

## What Is Correct For This Project

The current correct direction is:
- subtitle-first processing
- pyannote for diarization
- a small simple voice set
- a resumable runner
- progressively playable output

## What To Avoid

We should avoid:
- per-episode manual tuning
- design choices tied to one sample episode only
- GUI cluttered with technical controls
- workflows that restart from zero after failure
- dubbing audio with no preserved scene atmosphere

## Decision Filter

When evaluating future changes, use this filter:

1. Does this help start playback earlier?
2. Does this improve crash recovery?
3. Does this generalize to arbitrary videos, not just one sample?
4. Does this simplify the GUI?
5. Does this improve robustness more than it just looks clever?

If not, it is probably not a priority.
