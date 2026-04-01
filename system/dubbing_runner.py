import argparse
import asyncio
import json
import re
import time
from pathlib import Path

import edge_tts
from moviepy import AudioFileClip, VideoFileClip
from pydub import AudioSegment


DEFAULT_EDGE_VOICES = {
    "caption_narrator": "cs-CZ-AntoninNeural",
    "male_cz": "cs-CZ-AntoninNeural",
    "female_cz": "cs-CZ-VlastaNeural",
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_json(path, payload):
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )


class DubbingRunner:
    def __init__(self, video_path):
        self.video_path = Path(video_path).resolve()
        self.base_path = self.video_path.with_suffix("")
        self.segments_path = self.base_path.with_suffix(".dubbing_segments.json")
        self.voice_map_path = self.base_path.with_suffix(".voice_map.json")
        self.job_state_path = self.base_path.with_suffix(".dubbing_job_state.json")
        self.assets_dir = self.base_path.parent / f"{self.base_path.name}_dub_assets"
        self.segment_audio_dir = self.assets_dir / "segments"
        self.segment_audio_dir.mkdir(parents=True, exist_ok=True)

        self.segment_payload = load_json(self.segments_path)
        self.voice_map_payload = load_json(self.voice_map_path)
        self.job_state = load_json(self.job_state_path)
        self.segments = self.segment_payload["segments"]
        self.voice_entries = self.voice_map_payload["voices"]
        self.voice_lookup = {}
        self._prepare_voice_map()

    def _load_original_audio(self):
        return AudioSegment.from_file(self.video_path)

    def _apply_ducking(self, original_audio, target_segments, end_time=None):
        ducked = original_audio
        fade_ms = 120
        for segment in target_segments:
            start_ms = max(0, int(segment["start"] * 1000))
            end_seconds = min(segment["end"], end_time) if end_time else segment["end"]
            end_ms = min(len(ducked), int(end_seconds * 1000))
            if end_ms <= start_ms:
                continue

            pre_start = max(0, start_ms - fade_ms)
            post_end = min(len(ducked), end_ms + fade_ms)
            middle = ducked[start_ms:end_ms] - 18
            if pre_start < start_ms:
                ramp_down = ducked[pre_start:start_ms].fade(from_gain=0, to_gain=-18, start=0, end=start_ms - pre_start)
                ducked = ducked[:pre_start] + ramp_down + ducked[start_ms:]
            ducked = ducked[:start_ms] + middle + ducked[end_ms:]
            if end_ms < post_end:
                ramp_up = ducked[end_ms:post_end].fade(from_gain=-18, to_gain=0, start=0, end=post_end - end_ms)
                ducked = ducked[:end_ms] + ramp_up + ducked[post_end:]
        return ducked

    def _prepare_voice_map(self):
        for entry in self.voice_entries:
            if not entry.get("tts_engine"):
                entry["tts_engine"] = "edge_tts"
            if entry["voice_id"] in DEFAULT_EDGE_VOICES:
                entry["tts_voice"] = DEFAULT_EDGE_VOICES.get(
                    entry["voice_id"],
                    "cs-CZ-AntoninNeural",
                )
            elif not entry.get("tts_voice"):
                entry["tts_voice"] = "cs-CZ-AntoninNeural"
            self.voice_lookup[entry["voice_id"]] = entry
        save_json(self.voice_map_path, self.voice_map_payload)

    def _save_all(self):
        save_json(self.segments_path, self.segment_payload)
        save_json(self.voice_map_path, self.voice_map_payload)
        save_json(self.job_state_path, self.job_state)

    def reset_job(self):
        for segment in self.segments:
            if segment["dub"]["should_dub"]:
                segment["dub"]["status"] = "pending"
            else:
                segment["dub"]["status"] = "skipped"
            segment["dub"]["audio_file"] = None
            segment["dub"]["error"] = None

        for audio_file in self.segment_audio_dir.glob("*"):
            if audio_file.is_file():
                audio_file.unlink()

        for output_name in ("mixed_preview_audio.wav", "final_dub_audio.wav", f"{self.base_path.name}_dubbed.mp4"):
            output_path = self.assets_dir / output_name
            if output_path.exists():
                output_path.unlink()
        preview_video_path = self.assets_dir / f"{self.base_path.name}_preview.mp4"
        if preview_video_path.exists():
            preview_video_path.unlink()

        self.job_state["job_status"] = "ready"
        self.job_state["output_files"] = {
            "mixed_preview_audio": None,
            "preview_video": None,
            "final_dub_audio": None,
            "final_video": None,
        }
        playback = self.job_state.setdefault("playback_strategy", {})
        playback["ready_until"] = 0.0
        self._compute_progress()
        self._save_all()

    def _segment_path(self, segment_id):
        return self.segment_audio_dir / f"{segment_id}.mp3"

    def _pending_segments(self):
        for segment in self.segments:
            dub = segment["dub"]
            if dub["should_dub"] and dub["status"] in {"pending", "failed"}:
                yield segment

    def _compute_progress(self):
        pending = 0
        completed = 0
        failed = 0
        skipped = 0
        next_segment_id = None

        for segment in self.segments:
            dub = segment["dub"]
            if not dub["should_dub"]:
                skipped += 1
                continue
            if dub["status"] == "completed":
                completed += 1
            elif dub["status"] == "failed":
                failed += 1
                if next_segment_id is None:
                    next_segment_id = segment["segment_id"]
            else:
                pending += 1
                if next_segment_id is None:
                    next_segment_id = segment["segment_id"]

        self.job_state["progress"] = {
            "total_segments": len(self.segments),
            "dub_pending": pending,
            "dub_completed": completed,
            "dub_failed": failed,
            "dub_skipped": skipped,
            "next_segment_id": next_segment_id,
        }
        self.job_state["pending_segment_ids"] = [
            segment["segment_id"]
            for segment in self.segments
            if segment["dub"]["should_dub"] and segment["dub"]["status"] in {"pending", "failed"}
        ]
        self.job_state["completed_segment_ids"] = [
            segment["segment_id"]
            for segment in self.segments
            if segment["dub"]["status"] == "completed"
        ]
        self.job_state["failed_segments"] = [
            {
                "segment_id": segment["segment_id"],
                "error": segment["dub"]["error"],
            }
            for segment in self.segments
            if segment["dub"]["status"] == "failed"
        ]

    def _ready_prefix_end(self):
        ready_end = 0.0
        for segment in self.segments:
            dub = segment["dub"]
            if not dub["should_dub"]:
                ready_end = segment["end"]
                continue
            if dub["status"] != "completed":
                break
            ready_end = segment["end"]
        return ready_end

    async def _synthesize_segment(self, segment, voice_name, output_path):
        communicate = edge_tts.Communicate(
            segment["text_cs"],
            voice_name,
            pitch=segment["dub"].get("tts_pitch", "+0Hz"),
        )
        await communicate.save(str(output_path))

    def _split_tts_text(self, text, max_len=80):
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= max_len:
            return [text]
        chunks = []
        for part in re.split(r"\s+-\s+", text):
            part = part.strip()
            if not part:
                continue
            if len(part) <= max_len:
                chunks.append(part)
                continue
            sentences = re.split(r"(?<=[.!?])\s+", part)
            current = ""
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                candidate = f"{current} {sentence}".strip()
                if current and len(candidate) > max_len:
                    chunks.append(current)
                    current = sentence
                else:
                    current = candidate
            if current:
                chunks.append(current)
        return chunks or [text]

    def _synthesize_with_retry(self, segment, voice_name, output_path, retries=4):
        last_error = None
        chunks = self._split_tts_text(segment["text_cs"])
        temp_files = []
        try:
            for chunk_index, chunk_text in enumerate(chunks):
                temp_output = output_path.with_name(f"{output_path.stem}_{chunk_index}.mp3")
                temp_files.append(temp_output)
                chunk_segment = {
                    "text_cs": chunk_text,
                    "dub": {"tts_pitch": segment["dub"].get("tts_pitch", "+0Hz")},
                }
                for attempt in range(1, retries + 1):
                    try:
                        asyncio.run(
                            self._synthesize_segment(
                                chunk_segment,
                                voice_name,
                                temp_output,
                            )
                        )
                        break
                    except Exception as exc:
                        last_error = exc
                        if temp_output.exists():
                            temp_output.unlink()
                        if attempt >= retries:
                            raise
                        time.sleep(min(2 ** (attempt - 1), 8))

            combined = AudioSegment.empty()
            for index, temp_file in enumerate(temp_files):
                if index > 0:
                    combined += AudioSegment.silent(duration=120)
                combined += AudioSegment.from_file(temp_file)
            combined.export(output_path, format="mp3")
        finally:
            for temp_file in temp_files:
                if temp_file.exists():
                    temp_file.unlink()
        if last_error is not None and not output_path.exists():
            raise last_error

    def _render_mix(self, output_path, end_time=None):
        target_segments = []
        final_end = 0.0
        for segment in self.segments:
            dub = segment["dub"]
            if dub["status"] != "completed" or not dub["audio_file"]:
                continue
            if end_time is not None and segment["start"] >= end_time:
                continue
            target_segments.append(segment)
            final_end = max(final_end, min(segment["end"], end_time) if end_time else segment["end"])

        if final_end <= 0.0:
            return None

        original_audio = self._load_original_audio()[: int(final_end * 1000) + 250]
        mixed = self._apply_ducking(original_audio, target_segments, end_time=end_time)
        for segment in target_segments:
            audio = AudioSegment.from_file(segment["dub"]["audio_file"])
            mixed = mixed.overlay(audio, position=int(segment["start"] * 1000))
        mixed.export(output_path, format="wav")
        return output_path

    def _render_preview_if_needed(self):
        ready_end = self._ready_prefix_end()
        playback = self.job_state.setdefault("playback_strategy", {})
        previous_ready = playback.get("ready_until", 0.0)
        preview_path = self.assets_dir / "mixed_preview_audio.wav"
        preview_exists = preview_path.exists()
        if ready_end <= 0.0:
            playback["ready_until"] = max(previous_ready, ready_end)
            return
        if preview_exists and previous_ready > 0.0 and ready_end < previous_ready + 20.0:
            playback["ready_until"] = max(previous_ready, ready_end)
            return

        rendered = self._render_mix(preview_path, end_time=ready_end)
        if rendered:
            playback["ready_until"] = round(ready_end, 3)
            self.job_state["output_files"]["mixed_preview_audio"] = str(rendered)
            self._render_preview_video(rendered, ready_end)

    def _render_preview_video(self, preview_audio_path, ready_end):
        if ready_end <= 0.0:
            return
        preview_video_path = self.assets_dir / f"{self.base_path.name}_preview.mp4"
        temp_preview_video_path = preview_video_path.with_suffix(".tmp.mp4")
        video_clip = None
        audio_clip = None
        preview_clip = None
        try:
            if temp_preview_video_path.exists():
                temp_preview_video_path.unlink()
            video_clip = VideoFileClip(str(self.video_path)).subclipped(0, ready_end)
            audio_clip = AudioFileClip(str(preview_audio_path))
            preview_clip = video_clip.with_audio(audio_clip)
            preview_clip.write_videofile(
                str(temp_preview_video_path),
                codec="libx264",
                audio_codec="aac",
                logger=None,
            )
            if preview_video_path.exists():
                preview_video_path.unlink()
            temp_preview_video_path.replace(preview_video_path)
            self.job_state["output_files"]["preview_video"] = str(preview_video_path)
        except Exception:
            if temp_preview_video_path.exists():
                temp_preview_video_path.unlink()
        finally:
            if preview_clip is not None:
                preview_clip.close()
            if audio_clip is not None:
                audio_clip.close()
            if video_clip is not None:
                video_clip.close()

    def _render_final_outputs(self):
        final_audio_path = self.assets_dir / "final_dub_audio.wav"
        rendered_audio = self._render_mix(final_audio_path)
        if rendered_audio is None:
            return

        self.job_state["output_files"]["final_dub_audio"] = str(rendered_audio)
        final_video_path = self.assets_dir / f"{self.base_path.name}_dubbed.mp4"
        video_clip = VideoFileClip(str(self.video_path))
        audio_clip = AudioFileClip(str(rendered_audio))
        dubbed_clip = video_clip.with_audio(audio_clip)
        dubbed_clip.write_videofile(
            str(final_video_path),
            codec="libx264",
            audio_codec="aac",
            logger=None,
        )
        dubbed_clip.close()
        audio_clip.close()
        video_clip.close()
        self.job_state["output_files"]["final_video"] = str(final_video_path)

    def run(self, max_segments=None):
        self.job_state["job_status"] = "running"
        processed = 0
        self._compute_progress()
        self._save_all()

        if (
            self.job_state["progress"]["dub_pending"] == 0
            and self.job_state["progress"]["dub_failed"] == 0
        ):
            self._render_preview_if_needed()
            self.job_state["job_status"] = "completed"
            self._render_final_outputs()
            self._save_all()
            return
        try:
            for segment in self._pending_segments():
                voice_id = segment["dub"]["voice_id"]
                voice_entry = self.voice_lookup.get(voice_id)
                if voice_entry is None:
                    segment["dub"]["status"] = "failed"
                    segment["dub"]["error"] = f"Missing voice mapping for {voice_id}"
                    self._compute_progress()
                    self._save_all()
                    continue

                output_path = self._segment_path(segment["segment_id"])
                try:
                    self._synthesize_with_retry(
                        segment,
                        voice_entry["tts_voice"],
                        output_path,
                    )
                    segment["dub"]["status"] = "completed"
                    segment["dub"]["audio_file"] = str(output_path)
                    segment["dub"]["error"] = None
                except Exception as exc:
                    segment["dub"]["status"] = "failed"
                    segment["dub"]["error"] = str(exc)

                processed += 1
                self._compute_progress()
                self._render_preview_if_needed()
                self._save_all()

                if max_segments is not None and processed >= max_segments:
                    break
        finally:
            self._compute_progress()
            if self.job_state["progress"]["dub_pending"] == 0 and self.job_state["progress"]["dub_failed"] == 0:
                self.job_state["job_status"] = "completed"
                self._render_final_outputs()
            elif self.job_state["progress"]["dub_failed"] > 0:
                self.job_state["job_status"] = "partial_failed"
            else:
                self.job_state["job_status"] = "paused"
            self._save_all()


def main():
    parser = argparse.ArgumentParser(description="Resumable dubbing runner")
    parser.add_argument("video_path", help="Path to source video")
    parser.add_argument("--max-segments", type=int, default=None)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    runner = DubbingRunner(args.video_path)
    if args.reset:
        runner.reset_job()
    runner.run(max_segments=args.max_segments)


if __name__ == "__main__":
    main()
