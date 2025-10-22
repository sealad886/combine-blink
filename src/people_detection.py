"""
People detection utilities using Hugging Face Transformers (no OpenCV).

This module provides a lightweight wrapper to count the number of people
in an image using a Hugging Face object detection model. It defaults to
YOLOS-tiny (hustvl/yolos-tiny) for faster CPU inference. You can switch to
DETR (e.g., facebook/detr-resnet-50) if preferred; when using DETR, you may
optionally set `revision="no_timm"` to avoid the extra `timm` dependency.

Design goals:
- Lazy model loading (first use) to keep startup fast
- CPU-friendly by default
- Minimal API surface area (count people in a PIL image)
- Configurable score threshold

Dependencies:
- transformers
- torch
- Pillow
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any

import threading

from PIL import Image

# Heavy imports guarded for lazy initialization
try:
    import torch  # type: ignore
    from transformers import (  # type: ignore
        AutoImageProcessor,
        AutoModelForObjectDetection,
    )
except Exception:  # pragma: no cover - optional at import, enforced at runtime
    torch = None  # type: ignore
    AutoImageProcessor = None  # type: ignore
    AutoModelForObjectDetection = None  # type: ignore


@dataclass
class PeopleDetectorConfig:
    # Default to a light, CPU-friendly model. DETR is supported as well.
    model_name: str = "hustvl/yolos-tiny"
    # For DETR you can set revision="no_timm" to avoid timm; for YOLOS keep None.
    revision: Optional[str] = None
    score_threshold: float = 0.7


class PeopleDetector:
    """Counts people in images using a Hugging Face object detection model."""

    def __init__(self, config: Optional[PeopleDetectorConfig] = None) -> None:
        self.config = config or PeopleDetectorConfig()
        # Help static analyzers; prevents misinference that can cause init return-type errors.
        self._processor: Any = None
        self._model: Any = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        if AutoImageProcessor is None or AutoModelForObjectDetection is None or torch is None:
            raise RuntimeError(
                "Hugging Face transformers + torch are required for PeopleDetector"
            )
        with self._lock:
            if self._model is not None and self._processor is not None:
                return
            # Load processor and model lazily
            kwargs = {}
            if self.config.revision:
                kwargs["revision"] = self.config.revision
            # Auto* works across DETR, YOLOS, and other object detection backbones
            self._processor = AutoImageProcessor.from_pretrained(self.config.model_name, **kwargs)
            self._model = AutoModelForObjectDetection.from_pretrained(self.config.model_name, **kwargs)
            self._model.eval()

    def count_people(self, image: Image.Image) -> int:
        """Return number of detected people (COCO class 'person') in the given image.

        Uses score threshold from config to filter detections.
        """
        self._ensure_loaded()
        assert self._processor is not None and self._model is not None

        inputs = self._processor(images=image, return_tensors="pt")
        with torch.no_grad():  # type: ignore[attr-defined]
            outputs = self._model(**inputs)
        target_sizes = None
        try:
            import torch as _torch  # local alias to please type checkers
            target_sizes = _torch.tensor([image.size[::-1]])
        except Exception:
            target_sizes = None

        results = self._processor.post_process_object_detection(
            outputs,
            target_sizes=target_sizes,
            threshold=float(self.config.score_threshold),
        )[0]

        id2label = self._model.config.id2label
        count = 0
        for label_id in results.get("labels", []):
            try:
                label_name = id2label[int(label_id)]
            except Exception:
                continue
            if str(label_name).lower() == "person":
                count += 1
        return int(count)
