import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from pyannote.audio import Inference, Model

from blink_pipeline.media_utils import extract_audio_segment


@dataclass
class SpeakerEmbeddingSettings:
    model_id: str
    auth_token: str
    similarity_threshold: float
    device: str


class SpeakerIdentifier:
    """Resolves diarized speaker labels to persistent identities and saves samples."""

    def __init__(self, config: dict[str, Any]):
        if Inference is None or Model is None:
            raise RuntimeError(
                "pyannote.audio must be installed to enable speaker identification."
            )

        self.config = config
        self.output_dir = config["paths"]["output_dir"]
        self.speakers_dir = os.path.join(self.output_dir, config["paths"]["speakers_dir"])
        os.makedirs(self.speakers_dir, exist_ok=True)

        self.settings = self._parse_settings(config.get("speaker_identification", {}))

        # Make HF token available to downstream loaders as a convenience
        # without overriding already-set env vars.
        os.environ.setdefault("HF_TOKEN", self.settings.auth_token)
        os.environ.setdefault("HUGGINGFACE_TOKEN", self.settings.auth_token)

        # Load embedding model with authentication (supports both legacy and new API)
        model = None
        load_error: Exception | None = None
        try:
            # pyannote.audio >= 3.1 used `use_auth_token`
            model = Model.from_pretrained(
                self.settings.model_id,
                use_auth_token=self.settings.auth_token,
            )
        except TypeError as exc:
            # pyannote.audio >= 4 switched to `token`
            load_error = exc
            try:
                model = Model.from_pretrained(
                    self.settings.model_id,
                    token=self.settings.auth_token,
                )
            except Exception as exc2:  # pragma: no cover - defensive logging
                load_error = exc2
        if model is None:
            raise RuntimeError(
                f"Failed to load speaker embedding model '{self.settings.model_id}': {load_error}"
            )

        # Use whole-file embeddings for stable single-vector voiceprints
        self.embedding_model = Inference(model, window="whole")
        # Place model on the requested device (CUDA > MPS > CPU)
        try:  # pragma: no cover - depends on runtime availability
            if self.settings.device == "cuda" and torch is not None:
                if torch.cuda.is_available():
                    self.embedding_model.to(torch.device("cuda"))
                    logging.info("SpeakerIdentifier using CUDA acceleration")
                else:
                    logging.warning("Requested CUDA device, but CUDA is not available. Falling back to CPU")
            elif self.settings.device == "mps" and torch is not None:
                # Prefer Apple Silicon MPS when available
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    self.embedding_model.to(torch.device("mps"))
                    logging.info("SpeakerIdentifier using MPS acceleration (Apple Silicon)")
                    # Improve matmul perf/precision on MPS if supported
                    if hasattr(torch, "set_float32_matmul_precision"):
                        torch.set_float32_matmul_precision("high")
                else:
                    logging.warning("Requested MPS device, but MPS is not available. Falling back to CPU")
            else:
                logging.info("SpeakerIdentifier using CPU")
        except Exception:  # silently fall back to CPU if accel unavailable
            logging.warning(
                "Falling back to CPU for speaker embeddings due to device initialization error",
                exc_info=True,
            )

        self.voiceprints: dict[str, np.ndarray] = {}
        self.label_aliases: dict[str, str] = {}
        self.known_speakers_map = (
            (config.get("speakers", {}) or {}).get("known_speakers", {})
        )
        self.next_index = 1

        self._load_existing_voiceprints()

    def process_transcript(
        self, transcript: list[dict[str, Any]], timeline: list[dict[str, Any]]
    ) -> None:
        """Mutates transcript entries to use persistent speaker IDs and stores samples."""

        if not transcript:
            return

        unique_diar_labels = set()
        for entry in transcript:
            diar_label = entry.get("speaker")
            if not diar_label:
                continue

            if diar_label in self.label_aliases:
                entry["speaker"] = self.label_aliases[diar_label]
                continue

            unique_diar_labels.add(diar_label)
            global_id = self._resolve_speaker_identity(entry, timeline)
            if global_id is None:
                logging.warning(
                    "Unable to resolve speaker %s; leaving diarization label untouched.",
                    diar_label,
                )
                continue

            entry["speaker"] = global_id
            self.label_aliases[diar_label] = global_id

        if unique_diar_labels:
            logging.info(f"    → Processed {len(unique_diar_labels)} unique speaker(s) in this clip")
            logging.info(f"    → Total known speakers: {len(self.voiceprints)}")

    def substitute_names_in_transcript(self, transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace speaker IDs with configured human-readable names where available."""

        named_transcript: list[dict[str, Any]] = []
        for entry in transcript:
            speaker_id = entry.get("speaker")
            speaker_name = self.known_speakers_map.get(speaker_id, speaker_id)
            new_entry = entry.copy()
            new_entry["speaker"] = speaker_name
            named_transcript.append(new_entry)
        return named_transcript

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _parse_settings(self, config: dict[str, Any]) -> SpeakerEmbeddingSettings:
        model_id = config.get("embedding_model_id", "pyannote/wespeaker-voxceleb-resnet34-LM")
        token = config.get("auth_token")
        token_env = config.get("auth_token_env", ["HUGGINGFACE_TOKEN", "HF_TOKEN"])
        if isinstance(token_env, str):
            env_candidates = [token_env]
        else:
            env_candidates = list(token_env)

        if token is None:
            for env_name in env_candidates:
                token = os.getenv(env_name)
                if token:
                    break
        if not token:
            raise RuntimeError(
                "Speaker identification requires a Hugging Face token. Set 'auth_token' in config "
                "or export one of the environment variables: "
                + ", ".join(env_candidates)
                + "."
            )

        device = config.get("device", "auto")
        prefer_mps_on_mac = bool(config.get("prefer_mps_on_mac", True))
        if device == "auto":
            # On macOS, optionally prefer MPS first when available
            if (
                prefer_mps_on_mac
                and sys.platform == "darwin"
                and torch is not None
                and hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available()
            ):
                device = "mps"
            elif torch is not None and torch.cuda.is_available():
                device = "cuda"
            elif (
                torch is not None
                and hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available()
            ):
                device = "mps"
            else:
                device = "cpu"
        logging.info(
            "Speaker identification: selected device=%s (prefer_mps_on_mac=%s, platform=%s)",
            device,
            prefer_mps_on_mac,
            sys.platform,
        )

        similarity_threshold = float(config.get("similarity_threshold", 0.68))

        return SpeakerEmbeddingSettings(
            model_id=model_id,
            auth_token=token,
            similarity_threshold=similarity_threshold,
            device=device,
        )

    def _load_existing_voiceprints(self) -> None:
        for entry in os.listdir(self.speakers_dir):
            if not entry.lower().endswith(".wav"):
                continue
            speaker_id = os.path.splitext(entry)[0]
            audio_path = os.path.join(self.speakers_dir, entry)
            embedding = self._embed_file(audio_path)
            if embedding is None:
                logging.warning("Skipping voice sample %s due to embedding failure.", audio_path)
                continue
            self.voiceprints[speaker_id] = embedding

        indices = [
            int(part)
            for speaker_id in self.voiceprints
            if speaker_id.startswith("speaker_")
            for part in [speaker_id.split("_", 1)[1]]
            if part.isdigit()
        ]
        if indices:
            self.next_index = max(indices) + 1

    def _resolve_speaker_identity(
        self, segment: dict[str, Any], timeline: list[dict[str, Any]]
    ) -> str | None:
        for clip in timeline:
            if not clip.get("has_audio"):
                continue

            clip_start = clip["offset"]
            clip_end = clip_start + clip.get("duration", 0.0)
            overlap_start = max(segment["start"], clip_start)
            overlap_end = min(segment["end"], clip_end)

            if overlap_end <= overlap_start:
                continue

            relative_start = max(0.0, overlap_start - clip_start)
            relative_end = relative_start + (overlap_end - overlap_start)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                temp_path = tmp_file.name

            try:
                # Prefer repaired/used path when available
                source_path = clip.get("used_path") or clip.get("path") or clip.get("original_path")
                if not extract_audio_segment(
                    source_path, temp_path, start=relative_start, end=relative_end
                ):
                    logging.error(
                        "Failed to extract audio for diarized speaker from %s", source_path
                    )
                    os.remove(temp_path)
                    continue

                embedding = self._embed_file(temp_path)
                if embedding is None:
                    logging.error("Could not compute embedding for %s", temp_path)
                    os.remove(temp_path)
                    continue

                existing_id, score = self._match_voiceprint(embedding)
                if existing_id and score >= self.settings.similarity_threshold:
                    logging.debug(
                        "      Matched to existing speaker %s (similarity=%.3f)", existing_id, score
                    )
                    os.remove(temp_path)
                    return existing_id

                new_id = self._generate_speaker_id()
                destination = os.path.join(self.speakers_dir, f"{new_id}.wav")
                shutil.move(temp_path, destination)
                self.voiceprints[new_id] = embedding
                logging.info("      ✓ New speaker %s - saved voice sample: %s", new_id, os.path.basename(destination))
                return new_id

            except Exception as exc:  # pragma: no cover - defensive logging
                logging.error("Speaker identification failed: %s", exc)
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        return None

    def _embed_file(self, audio_path: str) -> np.ndarray | None:
        try:
            embedding = self.embedding_model(audio_path)
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.error("Embedding model failed for %s: %s", audio_path, exc)
            return None

        # Inference(window="whole") should return (1, D) numpy array.
        # Handle unexpected shapes defensively.
        try:
            vector = np.asarray(embedding, dtype=np.float32)
        except Exception:
            # Try attribute `.data` for SlidingWindowFeature-like objects
            vector = np.asarray(getattr(embedding, "data", None), dtype=np.float32)
        if vector is None or vector.size == 0:
            return None
        if vector.ndim == 0:
            return None
        if vector.ndim > 1:
            # Expect (1, D); average along first axis as a fallback
            vector = vector.mean(axis=0)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm == 0.0:
            return None
        return vector / norm

    def _match_voiceprint(self, embedding: np.ndarray) -> tuple[str | None, float]:
        best_id: str | None = None
        best_score: float = -1.0
        for speaker_id, stored_embedding in self.voiceprints.items():
            score = float(np.dot(embedding, stored_embedding))
            if score > best_score:
                best_id, best_score = speaker_id, score
        return best_id, best_score

    def _generate_speaker_id(self) -> str:
        while True:
            candidate = f"speaker_{self.next_index:04d}"
            self.next_index += 1
            if candidate not in self.voiceprints:
                return candidate
