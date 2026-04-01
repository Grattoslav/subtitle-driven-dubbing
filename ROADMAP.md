# Roadmap

## Current Stage

The project already has:
- subtitle-first analysis
- pyannote-based speaker handling
- dubbing-ready JSON export
- resumable dubbing jobs
- progressive playback model
- target-language-aware voice mapping

## Near-Term Priorities

### 1. Playback stability
- make GUI playback state clearer
- improve progressive video refresh behavior
- make timeline seeking smoother

### 2. Soundtrack quality
- improve original-audio ducking
- reduce cases where the dub sounds too isolated
- make background music and ambience more consistent

### 3. Robustness
- continue reducing transient TTS failures
- improve failure recovery and auto-resume behavior
- reduce GUI confusion around in-progress outputs

### 4. Multi-language workflow
- keep target-language-aware voice mapping
- add cleaner support for translated subtitle inputs
- eventually support optional translation pre-processing

## Mid-Term Priorities

### 5. Better speaker handling
- reduce speaker fragmentation
- improve short-utterance assignment
- improve overlap handling

### 6. Cleaner public API
- add a dedicated engine entrypoint
- make JSON generation a first-class CLI workflow
- separate engine, runner, and GUI more cleanly

## Out of Scope For Now

- lip-sync
- per-character theatrical voice acting
- perfect identity tracking for all speakers
- studio-grade dialogue separation

