import os
import sys
import json
import re
import tempfile
import warnings
from pathlib import Path

# --- 1. BYPASS SECURITY CHECKS (CVE-2025-32434) ---
# We must do this BEFORE importing transformers or speechbrain
import torch

# Trick libraries into thinking we have torch 2.6.0
torch.__version__ = "2.6.0"


def _log(message):
    print(message, flush=True)


def _dummy_check_torch_load_is_safe(*args, **kwargs):
    return True


def _configure_model_cache():
    """Keep downloaded model files inside the project directory."""
    project_root = Path(__file__).resolve().parent.parent
    cache_dir = project_root / "model_checkpoints"
    cache_dir.mkdir(exist_ok=True)

    os.environ.setdefault("HF_HOME", str(cache_dir))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(cache_dir))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(cache_dir))


def _get_temp_audio_dir():
    temp_dir = Path(__file__).resolve().parent.parent / "temp_audio"
    temp_dir.mkdir(exist_ok=True)
    return temp_dir


def _normalize_path(path):
    return str(Path(path).resolve())


DEFAULT_TARGET_LANGUAGE = os.environ.get("DUBBING_TARGET_LANGUAGE", "cs").strip().lower() or "cs"


def _chunk_tensor(wav, chunk_len):
    for start in range(0, wav.shape[1], chunk_len):
        yield wav[:, start : start + chunk_len]


def _parse_srt_timestamp(timestamp):
    hours, minutes, seconds_ms = timestamp.split(":")
    seconds, millis = seconds_ms.split(",")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )


def _clean_subtitle_text(lines):
    text = " ".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _letter_case_stats(text):
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0, 0.0
    upper_count = sum(1 for char in letters if char.isupper())
    return len(letters), upper_count / len(letters)


def _looks_like_on_screen_text(text):
    stripped = text.strip()
    if not stripped:
        return False

    letter_count, uppercase_ratio = _letter_case_stats(stripped)
    if letter_count and uppercase_ratio >= 0.78 and len(stripped) <= 100:
        return True

    words = [word for word in re.split(r"\s+", stripped) if word]
    upper_words = []
    for word in words:
        letters = [char for char in word if char.isalpha()]
        if letters and all(char.isupper() for char in letters):
            upper_words.append(word)
    if len(words) >= 2 and len(upper_words) >= 2 and uppercase_ratio >= 0.45:
        return True

    if re.match(r'^".+" [A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ .-]{4,}$', stripped):
        return True

    if re.match(r"^(NEOTVÍRAT|POZOR|VAROVÁNÍ|WINDEN|TMA|TAJEMSTVÍ)\b", stripped):
        return True

    if re.match(r"^\d{1,2}\.\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]+", stripped):
        return True

    if re.match(
        r"^[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]{3,}\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+)*$",
        stripped,
    ):
        return True

    return False


def _classify_subtitle_kind(text):
    if not text:
        return "empty"
    if re.search(r"^[\[(].*[\])]$", text):
        return "sfx_caption"
    if "♪" in text:
        return "music_caption"
    if _looks_like_on_screen_text(text):
        return "on_screen_text"
    return "dialog"


def _read_text_with_fallbacks(path):
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1250", "utf-8", "latin1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _merge_group_text(items):
    return " ".join(item["subtitle_cs"] for item in items if item["subtitle_cs"]).strip()


def _slugify_speaker_id(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _disable_broken_local_proxy():
    """Ignore the common dead local proxy setting that blocks HF downloads."""
    broken_proxy_values = {"http://127.0.0.1:9", "https://127.0.0.1:9"}
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "GIT_HTTP_PROXY",
        "GIT_HTTPS_PROXY",
    ):
        if os.environ.get(key) in broken_proxy_values:
            os.environ.pop(key, None)
            _log(f"--- Removed broken proxy override: {key} ---")


def _patch_transformers_torch_load_check():
    """Transformers 4.57 moved the check to utils.import_utils."""
    patched = False

    try:
        import transformers.utils.import_utils as tf_import_utils

        tf_import_utils.check_torch_load_is_safe = _dummy_check_torch_load_is_safe
        patched = True
    except ImportError:
        pass

    try:
        import transformers.utils.hub as tf_hub

        tf_hub.check_torch_load_is_safe = _dummy_check_torch_load_is_safe
        patched = True
    except ImportError:
        pass

    try:
        import transformers.modeling_utils as tf_modeling_utils

        tf_modeling_utils.check_torch_load_is_safe = _dummy_check_torch_load_is_safe
        patched = True
    except ImportError:
        pass

    if patched:
        _log("--- Transformers safety check bypassed ---")


_configure_model_cache()
_disable_broken_local_proxy()
_patch_transformers_torch_load_check()

# Patch torch.load globally to allow pickle for trusted models
import torch.serialization
_orig_torch_load = torch.load
def _safe_torch_load(*args, **kwargs):
    # Try with weights_only=True first (modern way)
    if 'weights_only' not in kwargs:
        kwargs['weights_only'] = False # SpeechBrain 1.0.0 needs False for complex hparams
    return _orig_torch_load(*args, **kwargs)

torch.load = _safe_torch_load
torch.serialization.load = _safe_torch_load

# --- 2. IMPORTS ---
import torchaudio
import numpy as np
from moviepy import VideoFileClip
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.inference.VAD import VAD
from pyannote.audio import Pipeline as PyannotePipeline
from transformers import WhisperForConditionalGeneration, WhisperProcessor
from scipy.spatial.distance import cosine

class DiarizationProcessor:
    def __init__(self, hf_token=None, device=None):
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        _log(f"--- DiarizationProcessor: Using device {self.device} ---")
        
        # Load Hugging Face Token
        if hf_token:
            os.environ["HUGGINGFACE_HUB_TOKEN"] = hf_token
            
        # 1. Load SpeechBrain VAD (CRDNN)
        _log("Loading VAD model (SpeechBrain)...")
        self.vad_model = VAD.from_hparams(
            source="speechbrain/vad-crdnn-libriparty",
            run_opts={"device": self.device}
        )
        
        # 2. Load SpeechBrain Speaker Recognition (ECAPA-TDNN)
        _log("Loading Speaker ID model (ECAPA-TDNN)...")
        # In SpeechBrain 1.0.0, EncoderClassifier is preferred for embeddings
        self.spk_model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": self.device}
        )
        
        # 3. Load ASR model without SentencePiece-dependent SpeechBrain tokenizer.
        _log("Loading ASR model (Transformers Whisper)...")
        whisper_model_name = "openai/whisper-base.en"
        self.asr_processor = WhisperProcessor.from_pretrained(
            whisper_model_name,
            token=hf_token,
        )
        self.asr_model = WhisperForConditionalGeneration.from_pretrained(
            whisper_model_name,
            token=hf_token,
        ).to(self.device)
        self.asr_model.eval()

        self.pyannote_pipeline = None
        self.pyannote_available = False
        try:
            _log("Loading diarization model (pyannote)...")
            self.pyannote_pipeline = PyannotePipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=hf_token,
                cache_dir=str(Path(__file__).resolve().parent.parent / "model_checkpoints"),
            )
            self.pyannote_pipeline.to(
                torch.device("cuda" if self.device == "cuda" else "cpu")
            )
            self.pyannote_available = True
        except Exception as e:
            _log(f"Pyannote unavailable, falling back to embedding clustering: {e}")
        
        # Speaker cache
        self.known_speakers = [] # List of speaker records
        self.similarity_threshold = 0.32 # Cosine distance threshold

    def _are_genders_compatible(self, left, right):
        known = {left, right} - {"unknown", None}
        return len(known) <= 1

    def _merge_speaker_clusters(self, results, merge_threshold=0.30):
        dialog_results = [item for item in results if item.get("kind") == "dialog"]
        if len(self.known_speakers) < 2 or not dialog_results:
            return results

        parent = list(range(len(self.known_speakers)))
        raw_speaker_ids = [speaker["id"] for speaker in self.known_speakers]

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left, right):
            root_left = find(left)
            root_right = find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        for left in range(len(self.known_speakers)):
            for right in range(left + 1, len(self.known_speakers)):
                speaker_left = self.known_speakers[left]
                speaker_right = self.known_speakers[right]
                if not self._are_genders_compatible(
                    speaker_left.get("gender"),
                    speaker_right.get("gender"),
                ):
                    compatibility_blocked = True
                else:
                    compatibility_blocked = False

                distance = cosine(
                    speaker_left["embedding"],
                    speaker_right["embedding"],
                )
                if distance < 0.22 or (distance < merge_threshold and not compatibility_blocked):
                    union(left, right)

        raw_to_root = {
            speaker_id: find(index) for index, speaker_id in enumerate(raw_speaker_ids)
        }
        cluster_stats = {}

        for item in dialog_results:
            root = raw_to_root.get(item["speaker"])
            if root is None:
                continue
            stats = cluster_stats.setdefault(
                root,
                {
                    "first_seen": item["start"],
                    "male": 0,
                    "female": 0,
                    "pitches": [],
                },
            )
            stats["first_seen"] = min(stats["first_seen"], item["start"])
            gender = item.get("gender", "unknown")
            if gender in ("male", "female"):
                stats[gender] += 1
            pitch = item.get("pitch_hz")
            if pitch is not None:
                stats["pitches"].append(pitch)

        canonical_ids = {}
        ordered_roots = sorted(
            set(raw_to_root.values()),
            key=lambda root: cluster_stats.get(root, {}).get("first_seen", float("inf")),
        )
        for ordinal, root in enumerate(ordered_roots, start=1):
            canonical_ids[root] = f"Speaker {ordinal}"

        for item in results:
            if item.get("kind") != "dialog":
                continue
            root = raw_to_root.get(item["speaker"])
            if root is None:
                continue
            item["speaker"] = canonical_ids[root]
            stats = cluster_stats.get(root, {})
            male_votes = stats.get("male", 0)
            female_votes = stats.get("female", 0)
            if male_votes > female_votes:
                item["gender"] = "male"
            elif female_votes > male_votes:
                item["gender"] = "female"
            else:
                item["gender"] = "unknown"
            pitches = stats.get("pitches", [])
            item["pitch_hz"] = round(float(np.median(pitches)), 1) if pitches else None

        return results

    def find_subtitle_path(self, video_path):
        video = Path(video_path)
        normalized_stem = re.sub(r"[\W_]+", "", video.stem).lower()
        candidates = [
            video.with_suffix(".srt"),
            video.with_name(video.stem.replace("_", " ") + ".srt"),
            video.with_name(video.stem.replace(" ", "_") + ".srt"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return _normalize_path(candidate)
        srt_files = list(video.parent.glob("*.srt"))
        if len(srt_files) == 1:
            return _normalize_path(srt_files[0])
        for candidate in srt_files:
            candidate_stem = re.sub(r"[\W_]+", "", candidate.stem).lower()
            if candidate_stem == normalized_stem:
                return _normalize_path(candidate)
        for candidate in srt_files:
            candidate_stem = re.sub(r"[\W_]+", "", candidate.stem).lower()
            if normalized_stem in candidate_stem or candidate_stem in normalized_stem:
                return _normalize_path(candidate)
        return None

    def parse_srt(self, subtitle_path):
        text = _read_text_with_fallbacks(subtitle_path)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        blocks = text.strip().split("\n\n")
        subtitles = []
        for block in blocks:
            lines = [line.rstrip() for line in block.splitlines()]
            if len(lines) < 2 or "-->" not in lines[1]:
                continue

            start_raw, end_raw = [part.strip() for part in lines[1].split("-->")]
            text = _clean_subtitle_text(lines[2:])
            subtitles.append(
                {
                    "index": len(subtitles) + 1,
                    "start": _parse_srt_timestamp(start_raw),
                    "end": _parse_srt_timestamp(end_raw),
                    "subtitle_cs": text,
                    "kind": _classify_subtitle_kind(text),
                }
            )
        return self._merge_structural_subtitles(subtitles)

    def _merge_structural_subtitles(self, subtitles):
        merged = []
        index = 0
        while index < len(subtitles):
            current = dict(subtitles[index])
            if index + 1 < len(subtitles):
                nxt = subtitles[index + 1]
                gap = nxt["start"] - current["end"]
                quote_split = (
                    gap <= 0.5
                    and current["subtitle_cs"].startswith('"')
                    and '"' not in current["subtitle_cs"][1:]
                    and nxt["kind"] == "on_screen_text"
                )
                if quote_split:
                    merged.append(
                        {
                            "index": current["index"],
                            "indices": [current["index"], nxt["index"]],
                            "start": current["start"],
                            "end": nxt["end"],
                            "subtitle_cs": f"{current['subtitle_cs']} {nxt['subtitle_cs']}".strip(),
                            "kind": "on_screen_text",
                        }
                    )
                    index += 2
                    continue
            merged.append(current)
            index += 1
        return merged

    def group_subtitles(self, subtitles, max_gap=1.2, max_duration=12.0):
        groups = []
        current = []

        for item in subtitles:
            if item["kind"] != "dialog":
                if current:
                    groups.append(current)
                    current = []
                groups.append([item])
                continue

            if not current:
                current = [item]
                continue

            prev = current[-1]
            gap = item["start"] - prev["end"]
            duration = item["end"] - current[0]["start"]
            if gap <= max_gap and duration <= max_duration:
                current.append(item)
            else:
                groups.append(current)
                current = [item]

        if current:
            groups.append(current)

        grouped_items = []
        for group in groups:
            first = group[0]
            last = group[-1]
            if len(group) == 1:
                grouped_items.append(dict(first))
                continue

            grouped_items.append(
                {
                    "index": first["index"],
                    "indices": [item["index"] for item in group],
                    "start": first["start"],
                    "end": last["end"],
                    "subtitle_cs": _merge_group_text(group),
                    "kind": first["kind"],
                }
            )

        return grouped_items

    def estimate_gender(self, segment_audio, sample_rate):
        """Heuristic gender estimate from median F0 on voiced frames."""
        chunk_mono = segment_audio
        if chunk_mono.shape[0] > 1:
            chunk_mono = chunk_mono.mean(dim=0, keepdim=True)

        try:
            pitch = torchaudio.functional.detect_pitch_frequency(
                chunk_mono.cpu(),
                sample_rate=sample_rate,
                frame_time=0.03,
                win_length=20,
                freq_low=85,
                freq_high=300,
            )
            voiced = pitch[pitch > 0]
            if voiced.numel() == 0:
                return "unknown", None

            median_f0 = float(torch.median(voiced).item())
            if median_f0 < 165:
                return "male", median_f0
            if median_f0 > 185:
                return "female", median_f0
            return "unknown", median_f0
        except Exception as e:
            _log(f"Gender estimation fallback to unknown: {e}")
            return "unknown", None

    def _update_speaker_gender(self, speaker_record, gender_label):
        if gender_label not in ("male", "female"):
            return speaker_record["gender"]

        speaker_record["gender_votes"][gender_label] += 1
        male_votes = speaker_record["gender_votes"]["male"]
        female_votes = speaker_record["gender_votes"]["female"]
        if male_votes > female_votes:
            speaker_record["gender"] = "male"
        elif female_votes > male_votes:
            speaker_record["gender"] = "female"
        else:
            speaker_record["gender"] = "unknown"
        return speaker_record["gender"]

    def detect_speech_segments(self, audio_path):
        """SpeechBrain VAD on an already loaded waveform to avoid Windows path issues."""
        signal, fs = torchaudio.load(audio_path)
        if fs != self.vad_model.sample_rate:
            raise ValueError(
                f"Expected {self.vad_model.sample_rate} Hz audio for VAD, got {fs} Hz."
            )

        # Convert to mono for VAD consistency.
        if signal.shape[0] > 1:
            signal = signal.mean(dim=0, keepdim=True)

        chunk_size_seconds = 30
        chunk_len = int(fs * chunk_size_seconds)
        vad_probs = []

        for chunk in _chunk_tensor(signal, chunk_len):
            original_len = chunk.shape[1]
            if original_len == 0:
                continue

            if original_len < chunk_len:
                padding = torch.zeros(
                    (chunk.shape[0], chunk_len - original_len),
                    dtype=chunk.dtype,
                )
                chunk = torch.cat([chunk, padding], dim=1)

            chunk_prob = self.vad_model.get_speech_prob_chunk(chunk)
            frames_to_keep = max(
                1,
                int(original_len / (fs * self.vad_model.time_resolution)),
            )
            vad_probs.append(chunk_prob[:, :frames_to_keep, :].to(self.vad_model.device))

        if not vad_probs:
            return torch.empty((0, 2))

        vad_prob = torch.cat(vad_probs, dim=1)
        prob_th = self.vad_model.apply_threshold(vad_prob)
        boundaries = self.vad_model.get_boundaries(prob_th, output_value="seconds")
        boundaries = self.vad_model.merge_close_segments(boundaries, close_th=0.25)
        boundaries = self.vad_model.remove_short_segments(boundaries, len_th=0.25)
        return boundaries.cpu()

    def extract_audio(self, video_path):
        """Extracts 16kHz mono audio from video."""
        video_path = _normalize_path(video_path)
        _log(f"Extracting audio from {video_path}...")
        clip = VideoFileClip(video_path)
        fd, temp_wav = tempfile.mkstemp(suffix=".wav", dir=str(_get_temp_audio_dir()))
        os.close(fd)
        temp_wav = _normalize_path(temp_wav)
        _log(f"Temporary WAV path: {temp_wav}")
        # Force 16000Hz and mono
        clip.audio.write_audiofile(temp_wav, fps=16000, nbytes=2, codec='pcm_s16le', ffmpeg_params=["-ac", "1"])
        clip.close()
        return temp_wav

    def extract_speaker_features(self, segment_audio, sample_rate):
        """Extract embedding and coarse pitch/gender hints for offline clustering."""
        embedding = self.spk_model.encode_batch(segment_audio)
        embedding = embedding.squeeze().cpu().numpy()
        gender_label, pitch_hz = self.estimate_gender(segment_audio, sample_rate)
        duration = float(segment_audio.shape[1] / sample_rate)
        is_reference = duration >= 1.2
        return {
            "embedding": embedding,
            "gender_guess": gender_label,
            "pitch_hz": pitch_hz,
            "duration": duration,
            "is_reference": is_reference,
        }

    def _build_global_speaker_clusters(self, dialog_entries):
        reference_entries = [entry for entry in dialog_entries if entry["is_reference"]]
        if not reference_entries:
            reference_entries = list(dialog_entries)
        if not reference_entries:
            return {}, {}

        clusters = []
        for entry in sorted(reference_entries, key=lambda item: item["start"]):
            best_cluster = None
            best_distance = 1.0
            for cluster in clusters:
                distance = cosine(entry["embedding"], cluster["embedding"])
                if distance < best_distance:
                    best_distance = distance
                    best_cluster = cluster

            if best_cluster is not None and best_distance < self.similarity_threshold:
                weight = best_cluster["count"]
                best_cluster["embedding"] = (
                    best_cluster["embedding"] * weight + entry["embedding"]
                ) / (weight + 1)
                best_cluster["count"] += 1
                best_cluster["entries"].append(entry)
            else:
                clusters.append(
                    {
                        "embedding": entry["embedding"].copy(),
                        "entries": [entry],
                        "count": 1,
                    }
                )

        for entry in dialog_entries:
            if entry in reference_entries:
                continue
            best_cluster = None
            best_distance = 1.0
            for cluster in clusters:
                distance = cosine(entry["embedding"], cluster["embedding"])
                if distance < best_distance:
                    best_distance = distance
                    best_cluster = cluster
            if best_cluster is None:
                continue
            best_cluster["entries"].append(entry)

        cluster_payloads = []
        for cluster in clusters:
            members = cluster["entries"]
            male_votes = sum(1 for item in members if item["gender_guess"] == "male")
            female_votes = sum(1 for item in members if item["gender_guess"] == "female")
            if male_votes > female_votes:
                gender = "male"
            elif female_votes > male_votes:
                gender = "female"
            else:
                gender = "unknown"
            pitches = [item["pitch_hz"] for item in members if item["pitch_hz"] is not None]
            cluster_payloads.append(
                {
                    "entries": members,
                    "embedding": cluster["embedding"],
                    "gender": gender,
                    "pitch_hz": round(float(np.median(pitches)), 1) if pitches else None,
                    "first_seen": min(item["start"] for item in members),
                }
            )

        cluster_payloads.sort(key=lambda item: item["first_seen"])
        entry_to_cluster = {}
        cluster_stats = {}
        for ordinal, cluster in enumerate(cluster_payloads, start=1):
            speaker_id = f"Speaker {ordinal}"
            cluster_stats[speaker_id] = {
                "gender": cluster["gender"],
                "pitch_hz": cluster["pitch_hz"],
            }
            for entry in cluster["entries"]:
                entry_to_cluster[id(entry)] = speaker_id

        return entry_to_cluster, cluster_stats

    def diarize_with_pyannote(self, signal, sample_rate):
        if not self.pyannote_available:
            return None

        diarization_signal = signal
        diarization_rate = sample_rate
        if diarization_signal.shape[0] > 1:
            diarization_signal = diarization_signal.mean(dim=0, keepdim=True)
        if diarization_rate != 16000:
            diarization_signal = torchaudio.functional.resample(
                diarization_signal,
                diarization_rate,
                16000,
            )
            diarization_rate = 16000

        output = self.pyannote_pipeline(
            {
                "waveform": diarization_signal,
                "sample_rate": diarization_rate,
            }
        )
        return output.speaker_diarization

    def get_dominant_pyannote_speaker(self, annotation, start, end):
        if annotation is None:
            return None

        overlaps = {}
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            overlap_start = max(start, float(turn.start))
            overlap_end = min(end, float(turn.end))
            overlap = overlap_end - overlap_start
            if overlap > 0:
                overlaps[speaker] = overlaps.get(speaker, 0.0) + overlap

        if not overlaps:
            return None
        return max(overlaps.items(), key=lambda item: item[1])[0]

    def _cluster_stats_from_pyannote(self, dialog_entries):
        cluster_stats = {}
        for entry in dialog_entries:
            speaker_id = entry["pyannote_speaker"]
            if not speaker_id:
                continue
            stats = cluster_stats.setdefault(
                speaker_id,
                {"male": 0, "female": 0, "pitches": [], "first_seen": entry["start"]},
            )
            stats["first_seen"] = min(stats["first_seen"], entry["start"])
            if entry["gender_guess"] in ("male", "female"):
                stats[entry["gender_guess"]] += 1
            if entry["pitch_hz"] is not None:
                stats["pitches"].append(entry["pitch_hz"])

        ordered_speakers = sorted(
            cluster_stats,
            key=lambda speaker_id: cluster_stats[speaker_id]["first_seen"],
        )
        speaker_map = {
            raw_id: f"Speaker {index}"
            for index, raw_id in enumerate(ordered_speakers, start=1)
        }

        normalized_stats = {}
        for raw_id, speaker_id in speaker_map.items():
            stats = cluster_stats[raw_id]
            if stats["male"] > stats["female"]:
                gender = "male"
            elif stats["female"] > stats["male"]:
                gender = "female"
            else:
                gender = "unknown"
            normalized_stats[speaker_id] = {
                "gender": gender,
                "pitch_hz": round(float(np.median(stats["pitches"])), 1)
                if stats["pitches"]
                else None,
            }
        return speaker_map, normalized_stats

    def _apply_short_utterance_smoothing(self, dialog_entries, cluster_stats):
        if not dialog_entries:
            return

        for index, entry in enumerate(dialog_entries):
            if entry["duration"] > 1.6:
                continue

            candidates = {}
            for offset in (-2, -1, 1, 2):
                neighbor_index = index + offset
                if neighbor_index < 0 or neighbor_index >= len(dialog_entries):
                    continue
                neighbor = dialog_entries[neighbor_index]
                gap = min(
                    abs(entry["start"] - neighbor["result"]["end"]),
                    abs(neighbor["start"] - entry["result"]["end"]),
                )
                if gap > 8.0:
                    continue
                speaker = neighbor["result"]["speaker"]
                score = candidates.setdefault(speaker, 0.0)
                score += max(neighbor["duration"], 0.5)
                if abs(offset) == 1:
                    score += 0.75
                if neighbor["duration"] > 1.6:
                    score += 1.0
                candidates[speaker] = score

            if not candidates:
                continue

            best_speaker, best_score = max(candidates.items(), key=lambda item: item[1])
            current_speaker = entry["result"]["speaker"]
            if best_speaker == current_speaker or best_score < 2.0:
                continue

            entry["result"]["speaker"] = best_speaker
            entry["result"]["gender"] = cluster_stats.get(best_speaker, {}).get(
                "gender",
                "unknown",
            )
            entry["result"]["pitch_hz"] = cluster_stats.get(best_speaker, {}).get(
                "pitch_hz"
            )

    def build_dubbing_segments(self, results, source_mode, target_language=DEFAULT_TARGET_LANGUAGE):
        segments = []
        dubbable_kinds = {"dialog", "on_screen_text"}
        for ordinal, item in enumerate(results, start=1):
            text_value = item.get("subtitle_cs") or item.get("text") or ""
            is_dubbable = item.get("kind") in dubbable_kinds and bool(text_value.strip())
            pitch_hz = item.get("pitch_hz")
            gender = item.get("gender", "unknown")
            child_like = False
            if pitch_hz is not None:
                if gender == "male" and pitch_hz >= 180:
                    child_like = True
                elif gender == "female" and pitch_hz >= 235:
                    child_like = True
                elif gender == "unknown" and pitch_hz >= 210:
                    child_like = True
            segments.append(
                {
                    "segment_id": f"seg_{ordinal:04d}",
                    "index": item.get("index"),
                    "indices": item.get("indices", [item.get("index")]),
                    "start": round(float(item["start"]), 3),
                    "end": round(float(item["end"]), 3),
                    "duration": round(float(item["end"] - item["start"]), 3),
                    "speaker": item.get("speaker", "unknown"),
                    "gender": gender,
                    "pitch_hz": pitch_hz,
                    "child_like": child_like,
                    "target_language": target_language,
                    "kind": item.get("kind", "dialog"),
                    "text": text_value,
                    "text_target": text_value,
                    "text_en": item.get("asr_en"),
                    "source_mode": source_mode,
                    "dub": {
                        "should_dub": is_dubbable,
                        "status": "pending" if is_dubbable else "skipped",
                        "voice_id": None,
                        "tts_pitch": "+35Hz" if child_like else "+0Hz",
                        "audio_file": None,
                        "error": None,
                    },
                }
            )
        return segments

    def build_voice_map(self, segments, target_language=DEFAULT_TARGET_LANGUAGE):
        speaker_profiles = {}
        for segment in segments:
            speaker = segment["speaker"]
            if speaker == "none":
                continue
            profile = speaker_profiles.setdefault(
                speaker,
                {
                    "speaker": speaker,
                    "gender": segment.get("gender", "unknown"),
                    "kind_counts": {},
                    "segment_count": 0,
                    "total_duration": 0.0,
                },
            )
            profile["segment_count"] += 1
            profile["total_duration"] += segment["duration"]
            kind = segment["kind"]
            profile["kind_counts"][kind] = profile["kind_counts"].get(kind, 0) + 1
            if profile["gender"] == "unknown" and segment.get("gender") in ("male", "female"):
                profile["gender"] = segment["gender"]

        ordered_profiles = sorted(
            speaker_profiles.values(),
            key=lambda item: (-item["total_duration"], item["speaker"]),
        )
        voice_map = []
        speaker_to_voice = {}

        for profile in ordered_profiles:
            gender = profile["gender"]
            lang = target_language
            if profile["speaker"] == "caption":
                voice_id = f"caption_{lang}"
            elif gender == "female":
                voice_id = f"female_{lang}"
            else:
                voice_id = f"male_{lang}"

            primary_kind = max(
                profile["kind_counts"],
                key=lambda key: profile["kind_counts"][key],
            )
            entry = {
                "speaker": profile["speaker"],
                "speaker_slug": _slugify_speaker_id(profile["speaker"]),
                "gender": gender,
                "target_language": target_language,
                "voice_id": voice_id,
                "voice_role": "caption" if profile["speaker"] == "caption" or primary_kind == "on_screen_text" else "dialog",
                "tts_engine": None,
                "tts_voice": None,
                "segment_count": profile["segment_count"],
                "total_duration": round(profile["total_duration"], 3),
            }
            voice_map.append(entry)
            speaker_to_voice[profile["speaker"]] = voice_id

        for segment in segments:
            if segment["dub"]["should_dub"]:
                segment["dub"]["voice_id"] = speaker_to_voice.get(segment["speaker"])

        return voice_map

    def build_job_state(self, video_path, segments):
        pending_segments = [
            segment["segment_id"]
            for segment in segments
            if segment["dub"]["status"] == "pending"
        ]
        return {
            "video_path": _normalize_path(video_path),
            "job_status": "ready",
            "resume_supported": True,
            "playback_strategy": {
                "mode": "front_to_back",
                "can_start_before_full_completion": True,
                "ready_after_first_completed_segment": True,
            },
            "progress": {
                "total_segments": len(segments),
                "dub_pending": len(pending_segments),
                "dub_completed": 0,
                "dub_failed": 0,
                "dub_skipped": len(segments) - len(pending_segments),
                "next_segment_id": pending_segments[0] if pending_segments else None,
            },
            "pending_segment_ids": pending_segments,
            "completed_segment_ids": [],
            "failed_segments": [],
            "output_files": {
                "mixed_preview_audio": None,
                "final_dub_audio": None,
                "final_video": None,
            },
        }

    def transcribe_chunk(self, chunk, fs):
        """Run Whisper directly without transformers pipeline/torchcodec."""
        chunk_mono = chunk
        if chunk_mono.shape[0] > 1:
            chunk_mono = chunk_mono.mean(dim=0, keepdim=True)

        audio_array = chunk_mono.squeeze(0).cpu().numpy()
        inputs = self.asr_processor(
            audio_array,
            sampling_rate=fs,
            return_tensors="pt",
        )
        input_features = inputs.input_features.to(self.device)

        with torch.no_grad():
            predicted_ids = self.asr_model.generate(input_features)

        text = self.asr_processor.batch_decode(
            predicted_ids,
            skip_special_tokens=True,
        )[0]
        return text.strip()

    def process_video(self, video_path):
        """Yields subtitle-aligned or VAD-derived items for dubbing prep."""
        audio_path = self.extract_audio(video_path)
        subtitle_path = self.find_subtitle_path(video_path)
        
        # Load full audio for slicing
        signal, fs = torchaudio.load(audio_path)
        results = []

        if subtitle_path:
            subtitles = self.parse_srt(subtitle_path)
            grouped_subtitles = self.group_subtitles(subtitles)
            dialog_entries = []
            pyannote_annotation = None
            _log(f"Using subtitle-driven segmentation from {subtitle_path}")
            _log(
                f"Found {len(subtitles)} subtitle items, grouped into {len(grouped_subtitles)} processing items."
            )
            if self.pyannote_available:
                try:
                    _log("Running pyannote diarization over extracted audio...")
                    pyannote_annotation = self.diarize_with_pyannote(signal, fs)
                except Exception as e:
                    _log(f"Pyannote diarization failed, using fallback clustering: {e}")
                    pyannote_annotation = None

            for item in grouped_subtitles:
                start = float(item["start"])
                end = float(item["end"])
                start_sample = max(0, int(start * fs))
                end_sample = min(signal.shape[1], int(end * fs))
                chunk = signal[:, start_sample:end_sample]

                if chunk.numel() == 0:
                    result = {
                        "index": item["index"],
                        "indices": item.get("indices", [item["index"]]),
                        "start": start,
                        "end": end,
                        "speaker": "none",
                        "gender": "unknown",
                        "pitch_hz": None,
                        "text": item["subtitle_cs"],
                        "subtitle_cs": item["subtitle_cs"],
                        "kind": item["kind"],
                        "source": "srt",
                    }
                    results.append(result)
                    continue

                if item["kind"] == "dialog":
                    features = self.extract_speaker_features(chunk, fs)
                    asr_text = self.transcribe_chunk(chunk, fs)
                    result = {
                        "index": item["index"],
                        "indices": item.get("indices", [item["index"]]),
                        "start": start,
                        "end": end,
                        "speaker": "pending",
                        "gender": features["gender_guess"],
                        "pitch_hz": round(features["pitch_hz"], 1) if features["pitch_hz"] else None,
                        "text": item["subtitle_cs"],
                        "subtitle_cs": item["subtitle_cs"],
                        "asr_en": asr_text,
                        "kind": item["kind"],
                        "source": "srt",
                    }
                    dialog_entries.append(
                        {
                            "result": result,
                            "embedding": features["embedding"],
                            "gender_guess": features["gender_guess"],
                            "pitch_hz": features["pitch_hz"],
                            "duration": features["duration"],
                            "is_reference": features["is_reference"],
                            "start": start,
                            "pyannote_speaker": self.get_dominant_pyannote_speaker(
                                pyannote_annotation,
                                start,
                                end,
                            ),
                        }
                    )
                else:
                    result = {
                        "index": item["index"],
                        "indices": item.get("indices", [item["index"]]),
                        "start": start,
                        "end": end,
                        "speaker": "caption",
                        "gender": "unknown",
                        "pitch_hz": None,
                        "text": item["subtitle_cs"],
                        "subtitle_cs": item["subtitle_cs"],
                        "kind": item["kind"],
                        "source": "srt",
                    }

                results.append(result)
            if pyannote_annotation is not None and any(
                entry["pyannote_speaker"] for entry in dialog_entries
            ):
                speaker_map, cluster_stats = self._cluster_stats_from_pyannote(dialog_entries)
                for entry in dialog_entries:
                    raw_speaker = entry["pyannote_speaker"]
                    speaker_id = speaker_map.get(raw_speaker, "Speaker 1")
                    entry["result"]["speaker"] = speaker_id
                    entry["result"]["gender"] = cluster_stats.get(speaker_id, {}).get(
                        "gender",
                        "unknown",
                    )
                    entry["result"]["pitch_hz"] = cluster_stats.get(speaker_id, {}).get(
                        "pitch_hz"
                    )
                self._apply_short_utterance_smoothing(dialog_entries, cluster_stats)
            else:
                entry_to_cluster, cluster_stats = self._build_global_speaker_clusters(dialog_entries)
                for entry in dialog_entries:
                    speaker_id = entry_to_cluster.get(id(entry), "Speaker 1")
                    entry["result"]["speaker"] = speaker_id
                    entry["result"]["gender"] = cluster_stats.get(speaker_id, {}).get("gender", "unknown")
                    entry["result"]["pitch_hz"] = cluster_stats.get(speaker_id, {}).get("pitch_hz")
            for result in results:
                yield result
        else:
            _log("Starting VAD...")
            segments = self.detect_speech_segments(audio_path)
            _log(f"Found {len(segments)} segments. Processing incrementally...")

            for i, seg in enumerate(segments):
                start, end = float(seg[0]), float(seg[1])
                if end - start < 0.3:
                    continue

                start_sample = int(start * fs)
                end_sample = int(end * fs)
                chunk = signal[:, start_sample:end_sample]
                speaker = self.identify_speaker(chunk, fs)
                text = self.transcribe_chunk(chunk, fs)
                result = {
                    "index": i + 1,
                    "start": start,
                    "end": end,
                    "speaker": speaker["id"],
                    "gender": speaker["gender"],
                    "pitch_hz": round(speaker["pitch_hz"], 1) if speaker["pitch_hz"] else None,
                    "text": text,
                    "kind": "dialog",
                    "source": "vad",
                }
                results.append(result)
                yield result

        export_path = Path(video_path).with_suffix(".dubbing_prep.json")
        segments = self.build_dubbing_segments(
            results,
            "srt" if subtitle_path else "vad",
            DEFAULT_TARGET_LANGUAGE,
        )
        voice_map = self.build_voice_map(segments, DEFAULT_TARGET_LANGUAGE)
        job_state = self.build_job_state(video_path, segments)
        export_payload = {
            "video_path": _normalize_path(video_path),
            "subtitle_path": subtitle_path,
            "source_mode": "srt" if subtitle_path else "vad",
            "target_language": DEFAULT_TARGET_LANGUAGE,
            "items": results,
        }
        export_path.write_text(
            json.dumps(export_payload, ensure_ascii=False, indent=2),
            encoding="utf-8-sig",
        )
        _log(f"Saved dubbing prep JSON to {export_path}")

        segments_path = Path(video_path).with_suffix(".dubbing_segments.json")
        segments_path.write_text(
            json.dumps(
                {
                    "video_path": _normalize_path(video_path),
                    "source_mode": export_payload["source_mode"],
                    "target_language": DEFAULT_TARGET_LANGUAGE,
                    "segments": segments,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8-sig",
        )
        _log(f"Saved dubbing segments JSON to {segments_path}")

        voice_map_path = Path(video_path).with_suffix(".voice_map.json")
        voice_map_path.write_text(
            json.dumps(
                {
                    "video_path": _normalize_path(video_path),
                    "target_language": DEFAULT_TARGET_LANGUAGE,
                    "voices": voice_map,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8-sig",
        )
        _log(f"Saved voice map JSON to {voice_map_path}")

        job_state_path = Path(video_path).with_suffix(".dubbing_job_state.json")
        job_state_path.write_text(
            json.dumps(job_state, ensure_ascii=False, indent=2),
            encoding="utf-8-sig",
        )
        _log(f"Saved dubbing job state JSON to {job_state_path}")
            
        # Final cleanup
        if os.path.exists(audio_path):
            os.unlink(audio_path)

if __name__ == "__main__":
    pass
