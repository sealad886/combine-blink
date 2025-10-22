"""
People detection utilities using Hugging Face Transformers (no OpenCV).
Optimized for Apple Silicon: use MPS when available.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Any
import threading
from PIL import Image

try:
    import torch  # type: ignore
    from transformers import AutoImageProcessor, AutoModelForObjectDetection  # type: ignore
except Exception:  # pragma: no cover
    torch = None  # type: ignore
    AutoImageProcessor = None  # type: ignore
    AutoModelForObjectDetection = None  # type: ignore

@dataclass
class PeopleDetectorConfig:
    model_name: str = "hustvl/yolos-tiny"
    revision: Optional[str] = None
    score_threshold: float = 0.7

class PeopleDetector:
    """Counts people in images using a Hugging Face object detection model."""
    def __init__(self, config: Optional[PeopleDetectorConfig] = None) -> None:
        self.config = config or PeopleDetectorConfig()
        self._processor: Any = None
        self._model: Any = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        if AutoImageProcessor is None or AutoModelForObjectDetection is None or torch is None:
            raise RuntimeError("Hugging Face transformers + torch are required for PeopleDetector")
        with self._lock:
            if self._model is not None and self._processor is not None:
                return
            kwargs = {}
            if self.config.revision:
                kwargs["revision"] = self.config.revision
            self._processor = AutoImageProcessor.from_pretrained(self.config.model_name, **kwargs)
            self._model = AutoModelForObjectDetection.from_pretrained(self.config.model_name, **kwargs)
            self._model.eval()
            # Prefer MPS on Apple Silicon
            try:
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    self._model.to("mps")  # type: ignore[arg-type]
                    if hasattr(torch, "set_float32_matmul_precision"):
                        torch.set_float32_matmul_precision("high")
            except Exception:
                pass

    def count_people(self, image: Image.Image) -> int:
        """Return number of detected people (COCO class 'person') in the given image."""
        self._ensure_loaded()
        assert self._processor is not None and self._model is not None

        inputs = self._processor(images=image, return_tensors="pt")
        # Move tensors to model device
        model_device = next(self._model.parameters()).device  # type: ignore[attr-defined]
        for k in list(inputs.keys()):
            try:
                inputs[k] = inputs[k].to(model_device, non_blocking=True)  # type: ignore[assignment]
            except Exception:
                pass

        with torch.inference_mode():  # type: ignore[attr-defined]
            outputs = self._model(**inputs)  # type: ignore[call-arg]

        try:
            import torch as _torch
            target_sizes = _torch.tensor([image.size[::-1]], device=model_device)
        except Exception:
            target_sizes = None

        results = self._processor.post_process_object_detection(
            outputs, target_sizes=target_sizes, threshold=float(self.config.score_threshold)
        )[0]

        id2label = self._model.config.id2label
        count = 0
        for label_id in results.get("labels", []):
            try:
                if id2label[int(label_id)] == "person":
                    count += 1
            except Exception:
                continue
        return count
