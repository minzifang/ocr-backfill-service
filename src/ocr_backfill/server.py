from __future__ import annotations

import os
import tempfile
import logging
import threading
import time
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI
from PIL import Image
from pydantic import BaseModel, Field

from .core import AutoOcrEngine, BackfillConfig, enrich_markdown

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, ""))
        return value if value > 0 else default
    except Exception:
        return default


class OcrBackfillRequest(BaseModel):
    markdown: str = Field(default="", description="Markdown text returned by MinerU/Docling.")
    image_base_dir: str | None = Field(default=None, description="Base directory for relative image paths.")
    image_map: dict[str, str] = Field(default_factory=dict, description="Map markdown image src to URL/path/data URI.")
    download_headers: dict[str, str] = Field(default_factory=dict, description="Optional headers for image URL download.")
    ocr_engine: str = Field(default="auto", description="auto, rapidocr, paddleocr, or tesseract.")
    lang: str = Field(default="ch", description="OCR language hint.")
    max_images: int = 80
    min_width: int = 80
    min_height: int = 80
    min_text_chars: int = 5
    max_text_chars_per_image: int = 4000
    dedupe: bool = True
    keep_failed_notes: bool = False
    marker_title: str = "图片OCR"
    request_timeout: int = 20
    preprocess_images: bool = False
    upscale_factor: float = 1.0
    autocontrast: bool = True
    sharpen: bool = False
    download_workers: int = Field(default_factory=lambda: _env_int("OCR_BACKFILL_DOWNLOAD_WORKERS", 8))
    ocr_workers: int = Field(default_factory=lambda: _env_int("OCR_BACKFILL_OCR_WORKERS", 2))


class OcrBackfillResponse(BaseModel):
    text: str
    markdown: str
    image_count: int
    ocr_count: int
    skipped_count: int
    failed_count: int
    items: list[dict[str, Any]]
    elapsed_seconds: float = 0.0
    queue_wait_seconds: float = 0.0


_REQUEST_WORKERS = _env_int("OCR_BACKFILL_REQUEST_WORKERS", 1)
_REQUEST_SEMAPHORE = threading.BoundedSemaphore(_REQUEST_WORKERS)

app = FastAPI(title="OCR Backfill Service", version="0.2.10")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    return {
        "status": "ok",
        "engine": os.getenv("OCR_BACKFILL_ENGINE", "paddleocr"),
        "device": os.getenv("OCR_PADDLE_DEVICE", "cpu"),
        "text_detection_model": os.getenv("OCR_PADDLE_TEXT_DETECTION_MODEL", ""),
        "text_recognition_model": os.getenv("OCR_PADDLE_TEXT_RECOGNITION_MODEL", ""),
        "textline_orientation": os.getenv("OCR_PADDLE_TEXTLINE_ORIENTATION", "0"),
        "doc_orientation": os.getenv("OCR_PADDLE_DOC_ORIENTATION", "0"),
        "doc_unwarping": os.getenv("OCR_PADDLE_DOC_UNWARPING", "0"),
        "download_workers": os.getenv("OCR_BACKFILL_DOWNLOAD_WORKERS", "8"),
        "ocr_workers": os.getenv("OCR_BACKFILL_OCR_WORKERS", "2"),
        "request_workers": os.getenv("OCR_BACKFILL_REQUEST_WORKERS", "1"),
    }


@app.on_event("startup")
def preload_engine() -> None:
    if os.getenv("OCR_BACKFILL_PRELOAD", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    engine_name = os.getenv("OCR_BACKFILL_ENGINE", "paddleocr")
    lang = os.getenv("OCR_BACKFILL_LANG", "ch")
    engine = AutoOcrEngine(engine_name)
    try:
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            Image.new("RGB", (240, 80), "white").save(tmp.name)
            engine.image_to_text(tmp.name, lang)
    except Exception as exc:
        logger.warning("OCR engine preload failed; service will continue and retry on request: %s", exc)


@app.post("/v1/ocr-backfill", response_model=OcrBackfillResponse)
def ocr_backfill(request: OcrBackfillRequest) -> OcrBackfillResponse:
    queue_started = time.perf_counter()
    with _REQUEST_SEMAPHORE:
        queue_wait_seconds = time.perf_counter() - queue_started
        allowed_roots = [root for root in os.getenv("OCR_BACKFILL_ALLOWED_ROOTS", "").split(os.pathsep) if root]
        configured_engine = os.getenv("OCR_BACKFILL_ENGINE", "").strip()
        request_engine = (request.ocr_engine or "").strip()
        engine_name = configured_engine or request_engine or "paddleocr"
        config = BackfillConfig(
            image_base_dir=request.image_base_dir,
            image_map=request.image_map,
            download_headers=request.download_headers,
            allowed_roots=allowed_roots,
            ocr_engine=engine_name,
            lang=request.lang,
            request_timeout=request.request_timeout,
            max_images=request.max_images,
            min_width=request.min_width,
            min_height=request.min_height,
            min_text_chars=request.min_text_chars,
            max_text_chars_per_image=request.max_text_chars_per_image,
            dedupe=request.dedupe,
            keep_failed_notes=request.keep_failed_notes,
            marker_title=request.marker_title,
            preprocess_images=request.preprocess_images,
            upscale_factor=request.upscale_factor,
            autocontrast=request.autocontrast,
            sharpen=request.sharpen,
            download_workers=request.download_workers,
            ocr_workers=request.ocr_workers,
        )
        result = enrich_markdown(request.markdown, config)
    items = [asdict(item) for item in result.items]
    return OcrBackfillResponse(
        text=result.markdown,
        markdown=result.markdown,
        image_count=result.image_count,
        ocr_count=result.ocr_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
        items=items,
        elapsed_seconds=result.elapsed_seconds,
        queue_wait_seconds=queue_wait_seconds,
    )


def main() -> None:
    import uvicorn

    host = os.getenv("OCR_BACKFILL_HOST", "0.0.0.0")
    port = int(os.getenv("OCR_BACKFILL_PORT", "8018"))
    uvicorn.run("ocr_backfill.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
