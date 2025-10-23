"""
People detection utilities with multiple backends:
- 'huggingface': Hugging Face Transformers (YOLOS/DETR) with MPS support
- 'vision': Apple Vision framework (native, fastest on Apple Silicon)

Optimized for Apple Silicon with automatic backend selection.
"""
from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass
from typing import Any, Literal

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForObjectDetection

# Apple Vision framework (macOS only)
try:
    if sys.platform == "darwin":
        import objc  # type: ignore
        import Vision  # type: ignore
        from Quartz import CIImage  # type: ignore
        VISION_AVAILABLE = True
    else:
        Vision = None  # type: ignore
        CIImage = None  # type: ignore
        objc = None  # type: ignore
        VISION_AVAILABLE = False
except Exception:  # pragma: no cover
    Vision = None  # type: ignore
    CIImage = None  # type: ignore
    objc = None  # type: ignore
    VISION_AVAILABLE = False

@dataclass
class PeopleDetectorConfig:
    backend: Literal["auto", "vision", "huggingface"] = "auto"
    model_name: str = "hustvl/yolos-tiny"
    revision: str | None = None
    score_threshold: float = 0.7

class VisionPeopleDetector:
    """
    People detection using Apple's Vision framework.

    Ultra-fast, native acceleration on Apple Silicon using the Neural Engine.
    No model downloads or GPU memory required. macOS-only.
    """

    def __init__(self, config: PeopleDetectorConfig | None = None) -> None:
        self.config = config or PeopleDetectorConfig()
        if not VISION_AVAILABLE:
            raise RuntimeError(
                "Apple Vision framework is not available. "
                "This backend requires macOS with pyobjc-framework-Vision installed."
            )
        self._lock = threading.Lock()
        logging.info("VisionPeopleDetector initialized (using Apple Neural Engine)")

    def count_people(self, image: Image.Image) -> int:
        """Return number of detected people using Vision framework."""
        import io

        # Convert PIL Image to bytes
        img_bytes = io.BytesIO()
        image.save(img_bytes, format='PNG')
        img_data = img_bytes.getvalue()

        # Create Vision request
        request = Vision.VNDetectHumanRectanglesRequest.alloc().init()
        request.setRevision_(Vision.VNDetectHumanRectanglesRequestRevision2)

        # Create request handler
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
            img_data, None
        )

        # Perform detection
        success = handler.performRequests_error_([request], None)
        if not success[0]:
            logging.warning("Vision framework detection failed")
            return 0

        # Count detections above confidence threshold
        results = request.results()
        if not results:
            return 0

        count = 0
        for observation in results:
            confidence = observation.confidence()
            if confidence >= self.config.score_threshold:
                count += 1

        return count


class HuggingFacePeopleDetector:
    """Counts people in images using a Hugging Face object detection model with MPS support."""

    def __init__(self, config: PeopleDetectorConfig | None = None) -> None:
        self.config = config or PeopleDetectorConfig()
        self._processor: Any = None
        self._model: Any = None
        self._lock = threading.Lock()
        logging.info(
            "HuggingFacePeopleDetector initialized (model=%s)",
            self.config.model_name
        )

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        if AutoImageProcessor is None or AutoModelForObjectDetection is None or torch is None:
            raise RuntimeError(
                "Hugging Face transformers + torch are required for HuggingFacePeopleDetector"
            )
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
                    logging.info("HuggingFacePeopleDetector using MPS acceleration")
                    if hasattr(torch, "set_float32_matmul_precision"):
                        torch.set_float32_matmul_precision("high")
                else:
                    logging.info("HuggingFacePeopleDetector using CPU")
            except Exception:
                logging.warning("Failed to move model to MPS, using CPU", exc_info=True)

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


class PeopleDetector:
    """
    Unified people detector with automatic backend selection.

    Backends:
    - 'vision': Apple Vision framework (fastest on macOS, uses Neural Engine)
    - 'huggingface': Hugging Face transformers (YOLOS/DETR with MPS support)
    - 'auto': Automatically select best available backend

    The 'auto' mode prefers Vision on macOS when available, falls back to HuggingFace.
    """

    def __init__(self, config: PeopleDetectorConfig | None = None) -> None:
        self.config = config or PeopleDetectorConfig()
        self._detector: Any = None
        self._backend: str = ""
        self._init_detector()

    def _init_detector(self) -> None:
        """Initialize the appropriate detector backend."""
        backend = self.config.backend

        # Auto-select backend
        if backend == "auto":
            if VISION_AVAILABLE:
                backend = "vision"
                logging.info(
                    "PeopleDetector: auto-selected 'vision' backend (Apple Neural Engine)"
                )
            else:
                backend = "huggingface"
                logging.info(
                    "PeopleDetector: auto-selected 'huggingface' backend "
                    "(Vision framework not available)"
                )

        # Initialize selected backend
        if backend == "vision":
            if not VISION_AVAILABLE:
                logging.warning(
                    "Vision backend requested but not available, falling back to huggingface"
                )
                backend = "huggingface"
            else:
                try:
                    self._detector = VisionPeopleDetector(self.config)
                    self._backend = "vision"
                    return
                except Exception as e:
                    logging.warning(
                        "Failed to initialize Vision backend: %s, falling back to huggingface",
                        e,
                    )
                    backend = "huggingface"

        if backend == "huggingface":
            try:
                self._detector = HuggingFacePeopleDetector(self.config)
                self._backend = "huggingface"
            except Exception as e:
                raise RuntimeError(
                    f"Failed to initialize people detector: {e}. "
                    "Install transformers+torch or use Vision backend on macOS."
                ) from e
        else:
            raise ValueError(
                f"Unknown people detection backend: {backend}. "
                "Valid options: 'auto', 'vision', 'huggingface'"
            )

    def count_people(self, image: Image.Image) -> int:
        """Return number of detected people in the given image."""
        if self._detector is None:
            raise RuntimeError("Detector not initialized")
        return self._detector.count_people(image)

    @property
    def backend(self) -> str:
        """Return the active backend name."""
        return self._backend
