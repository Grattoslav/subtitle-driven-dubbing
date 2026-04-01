# Integration Example

This folder contains a minimal consumer example for the dubbing engine.

## What it shows

It demonstrates how another developer can:
- select a video
- select a subtitle file
- call the engine
- start the dubbing workflow
- play the progressively generated dubbed output

## Included example

- `integration_player.py`

This is intentionally separate from the main project GUI.
It exists to show how someone can build their own player or frontend on top of the engine.

## Run

```powershell
python examples\integration_player.py
```

## Notes

- `F` toggles fullscreen on and off
- the subtitle file is passed explicitly to the engine
- this example is meant as a consumer app, not as the canonical project UI
