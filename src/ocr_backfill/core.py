from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import io
import mimetypes
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from PIL import Image, ImageFilter, ImageOps

os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

_OCR_EXECUTORS: dict[int, ThreadPoolExecutor] = {}
_OCR_EXECUTORS_LOCK = threading.Lock()


MARKDOWN_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<src><[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
HTML_IMAGE_RE = re.compile(
    r"<img\b[^>]*\bsrc=[\"'](?P<src>[^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
OCR_BLOCK_RE = re.compile(
    r"\n\s*<!--\s*image_ocr:start\b.*?<!--\s*image_ocr:end\s*-->\s*",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class BackfillConfig:
    image_base_dir: str | None = None
    image_map: dict[str, str] = field(default_factory=dict)
    download_headers: dict[str, str] = field(default_factory=dict)
    allowed_roots: list[str] = field(default_factory=list)
    ocr_engine: str = "auto"
    lang: str = "ch"
    request_timeout: int = 20
    max_images: int = 80
    min_width: int = 80
    min_height: int = 80
    min_text_chars: int = 5
    max_text_chars_per_image: int = 4000
    dedupe: bool = True
    keep_failed_notes: bool = False
    marker_title: str = "图片OCR"
    preprocess_images: bool = False
    upscale_factor: float = 1.0
    autocontrast: bool = True
    sharpen: bool = False
    download_workers: int = 8
    ocr_workers: int = 2


@dataclass
class ImageOcrItem:
    src: str
    status: str
    text: str = ""
    reason: str = ""
    sha256: str = ""
    width: int = 0
    height: int = 0
    elapsed_seconds: float = 0.0
    ocr_seconds: float = 0.0


@dataclass
class BackfillResult:
    markdown: str
    image_count: int
    ocr_count: int
    skipped_count: int
    failed_count: int
    items: list[ImageOcrItem]
    elapsed_seconds: float = 0.0


@dataclass
class _PreparedImage:
    index: int
    match: dict[str, Any]
    image_bytes: bytes
    suffix: str
    sha256: str
    width: int
    height: int
    started_at: float


class OcrEngine:
    def image_to_text(self, image_path: str, lang: str) -> str:
        raise NotImplementedError


class AutoOcrEngine(OcrEngine):
    _engine: OcrEngine | None = None
    _lock = threading.Lock()

    def __init__(self, preferred: str = "auto") -> None:
        self.preferred = preferred

    def image_to_text(self, image_path: str, lang: str) -> str:
        with self._lock:
            if self._engine is None:
                self._engine = _load_engine(self.preferred, lang)
        return self._engine.image_to_text(image_path, lang)


class RapidOcrEngine(OcrEngine):
    _instances: dict[str, Any] = {}
    _lock = threading.Lock()

    def image_to_text(self, image_path: str, lang: str) -> str:
        instance_key = f"rapid:{threading.get_ident()}"
        with self._lock:
            engine = self._instances.get(instance_key)
            if engine is None:
                try:
                    from rapidocr import RapidOCR
                except Exception:
                    from rapidocr_onnxruntime import RapidOCR
                engine = RapidOCR()
                self._instances[instance_key] = engine

        result = engine(image_path)
        return _rapidocr_text(result)


class PaddleOcrEngine(OcrEngine):
    _instances: dict[str, Any] = {}
    _lock = threading.Lock()

    def image_to_text(self, image_path: str, lang: str) -> str:
        paddle_lang = _paddle_lang(lang)
        device = os.getenv("OCR_PADDLE_DEVICE", "cpu").strip() or "cpu"
        text_detection_model = os.getenv("OCR_PADDLE_TEXT_DETECTION_MODEL", "").strip()
        text_recognition_model = os.getenv("OCR_PADDLE_TEXT_RECOGNITION_MODEL", "").strip()
        textline_orientation = _env_bool("OCR_PADDLE_TEXTLINE_ORIENTATION", False)
        doc_orientation = _env_bool("OCR_PADDLE_DOC_ORIENTATION", False)
        doc_unwarping = _env_bool("OCR_PADDLE_DOC_UNWARPING", False)
        instance_key = (
            f"{paddle_lang}:{device}:{text_detection_model}:{text_recognition_model}:"
            f"{textline_orientation}:{doc_orientation}:{doc_unwarping}:{threading.get_ident()}"
        )
        with self._lock:
            engine = self._instances.get(instance_key)
            if engine is None:
                from paddleocr import PaddleOCR

                common_kwargs: dict[str, Any] = {
                    "lang": paddle_lang,
                    "use_doc_orientation_classify": doc_orientation,
                    "use_doc_unwarping": doc_unwarping,
                    "use_textline_orientation": textline_orientation,
                    "enable_mkldnn": False,
                    "device": device,
                }
                if text_detection_model:
                    common_kwargs["text_detection_model_name"] = text_detection_model
                if text_recognition_model:
                    common_kwargs["text_recognition_model_name"] = text_recognition_model

                constructors = [
                    common_kwargs,
                    {k: v for k, v in common_kwargs.items() if k != "device"},
                    {"lang": paddle_lang, "use_textline_orientation": textline_orientation, "enable_mkldnn": False},
                    {"lang": paddle_lang, "use_angle_cls": textline_orientation, "enable_mkldnn": False},
                    {"lang": paddle_lang, "use_angle_cls": textline_orientation},
                ]
                last_error: Exception | None = None
                for kwargs in constructors:
                    try:
                        engine = PaddleOCR(**kwargs)
                        break
                    except TypeError as exc:
                        last_error = exc
                if engine is None:
                    raise last_error or RuntimeError("failed to initialize PaddleOCR")
                self._instances[instance_key] = engine

        try:
            result = engine.ocr(image_path)
        except TypeError:
            result = engine.predict(image_path)
        return _paddleocr_text(result)


class TesseractOcrEngine(OcrEngine):
    def image_to_text(self, image_path: str, lang: str) -> str:
        import pytesseract

        tess_lang = "chi_sim+eng" if lang.startswith("ch") else lang
        with Image.open(image_path) as image:
            return pytesseract.image_to_string(image, lang=tess_lang)


def enrich_markdown(markdown: str, config: BackfillConfig | None = None) -> BackfillResult:
    started_at = time.monotonic()
    config = config or BackfillConfig()
    source = markdown or ""
    refs = _collect_image_refs(source)
    engine = AutoOcrEngine(config.ocr_engine)

    replacements: list[tuple[int, int, str]] = []
    items_by_index: dict[int, ImageOcrItem] = {}
    seen_hashes: set[str] = set()
    load_candidates: list[tuple[int, dict[str, Any], float]] = []

    for index, match in enumerate(refs):
        if index >= config.max_images:
            items_by_index[index] = ImageOcrItem(src=match["src"], status="skipped", reason="max_images_reached")
            continue

        src = match["src"]
        if _has_existing_ocr_block(source, match["end"]):
            items_by_index[index] = ImageOcrItem(src=src, status="skipped", reason="already_backfilled")
            continue

        load_candidates.append((index, match, time.monotonic()))

    loaded_by_index = _load_images_concurrently(load_candidates, config)
    prepared_images: list[_PreparedImage] = []

    for index, match, item_started_at in load_candidates:
        loaded = loaded_by_index.get(index)
        if isinstance(loaded, ImageOcrItem):
            items_by_index[index] = loaded
            continue

        image_bytes, suffix = loaded
        src = match["src"]
        try:
            digest = hashlib.sha256(image_bytes).hexdigest()
            if config.dedupe and digest in seen_hashes:
                items_by_index[index] = ImageOcrItem(src=src, status="skipped", reason="duplicate", sha256=digest)
                continue
            seen_hashes.add(digest)

            width, height = _image_size(image_bytes)
            if width < config.min_width or height < config.min_height:
                items_by_index[index] = (
                    ImageOcrItem(
                        src=src,
                        status="skipped",
                        reason="image_too_small",
                        sha256=digest,
                        width=width,
                        height=height,
                    )
                )
                continue

            prepared_images.append(
                _PreparedImage(
                    index=index,
                    match=match,
                    image_bytes=image_bytes,
                    suffix=suffix,
                    sha256=digest,
                    width=width,
                    height=height,
                    started_at=item_started_at,
                )
            )
        except Exception as exc:
            reason = str(exc)
            items_by_index[index] = ImageOcrItem(
                src=src,
                status="failed",
                reason=reason,
                elapsed_seconds=round(time.monotonic() - item_started_at, 3),
            )
            if config.keep_failed_notes:
                block = _format_failed_block(src, reason, config.marker_title)
                replacements.append((match["end"], match["end"], block))

    ocr_results = _ocr_images_concurrently(prepared_images, engine, config)
    for prepared in prepared_images:
        item, block = ocr_results[prepared.index]
        items_by_index[prepared.index] = item
        if block:
            replacements.append((prepared.match["end"], prepared.match["end"], block))

    items = [items_by_index[index] for index in sorted(items_by_index)]
    enriched = _apply_replacements(source, replacements)
    ocr_count = sum(1 for item in items if item.status == "ok")
    failed_count = sum(1 for item in items if item.status == "failed")
    skipped_count = sum(1 for item in items if item.status == "skipped")
    return BackfillResult(
        markdown=enriched,
        image_count=len(refs),
        ocr_count=ocr_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        items=items,
        elapsed_seconds=round(time.monotonic() - started_at, 3),
    )


def _load_images_concurrently(
    candidates: list[tuple[int, dict[str, Any], float]], config: BackfillConfig
) -> dict[int, tuple[bytes, str] | ImageOcrItem]:
    if not candidates:
        return {}

    workers = _bounded_workers(config.download_workers, len(candidates), upper=32)
    results: dict[int, tuple[bytes, str] | ImageOcrItem] = {}

    def load(candidate: tuple[int, dict[str, Any], float]) -> tuple[int, tuple[bytes, str] | ImageOcrItem]:
        index, match, item_started_at = candidate
        try:
            return index, _load_image_bytes(match["src"], config)
        except Exception as exc:
            return (
                index,
                ImageOcrItem(
                    src=match["src"],
                    status="failed",
                    reason=str(exc),
                    elapsed_seconds=round(time.monotonic() - item_started_at, 3),
                ),
            )

    if workers <= 1:
        for candidate in candidates:
            index, value = load(candidate)
            results[index] = value
        return results

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ocr-download") as executor:
        future_map = {executor.submit(load, candidate): candidate[0] for candidate in candidates}
        for future in as_completed(future_map):
            index, value = future.result()
            results[index] = value
    return results


def _ocr_images_concurrently(
    prepared_images: list[_PreparedImage], engine: OcrEngine, config: BackfillConfig
) -> dict[int, tuple[ImageOcrItem, str | None]]:
    if not prepared_images:
        return {}

    workers = _bounded_workers(config.ocr_workers, len(prepared_images), upper=8)
    results: dict[int, tuple[ImageOcrItem, str | None]] = {}

    def run_ocr(prepared: _PreparedImage) -> tuple[int, ImageOcrItem, str | None]:
        src = prepared.match["src"]
        try:
            ocr_started_at = time.monotonic()
            text = _ocr_bytes(prepared.image_bytes, prepared.suffix, engine, config)
            ocr_seconds = round(time.monotonic() - ocr_started_at, 3)
            text = _normalize_ocr_text(text, config.max_text_chars_per_image)
            if len(text.replace(" ", "").replace("\n", "")) < config.min_text_chars:
                return (
                    prepared.index,
                    ImageOcrItem(
                        src=src,
                        status="skipped",
                        reason="ocr_text_too_short",
                        sha256=prepared.sha256,
                        width=prepared.width,
                        height=prepared.height,
                        elapsed_seconds=round(time.monotonic() - prepared.started_at, 3),
                        ocr_seconds=ocr_seconds,
                    ),
                    None,
                )

            return (
                prepared.index,
                ImageOcrItem(
                    src=src,
                    status="ok",
                    text=text,
                    sha256=prepared.sha256,
                    width=prepared.width,
                    height=prepared.height,
                    elapsed_seconds=round(time.monotonic() - prepared.started_at, 3),
                    ocr_seconds=ocr_seconds,
                ),
                _format_ocr_block(text, src, prepared.sha256, config.marker_title),
            )
        except Exception as exc:
            reason = str(exc)
            block = _format_failed_block(src, reason, config.marker_title) if config.keep_failed_notes else None
            return (
                prepared.index,
                ImageOcrItem(
                    src=src,
                    status="failed",
                    reason=reason,
                    sha256=prepared.sha256,
                    width=prepared.width,
                    height=prepared.height,
                    elapsed_seconds=round(time.monotonic() - prepared.started_at, 3),
                ),
                block,
            )

    if workers <= 1:
        for prepared in prepared_images:
            index, item, block = run_ocr(prepared)
            results[index] = (item, block)
        return results

    executor = _get_ocr_executor(workers)
    future_map = {executor.submit(run_ocr, prepared): prepared.index for prepared in prepared_images}
    for future in as_completed(future_map):
        index, item, block = future.result()
        results[index] = (item, block)
    return results


def _get_ocr_executor(workers: int) -> ThreadPoolExecutor:
    with _OCR_EXECUTORS_LOCK:
        executor = _OCR_EXECUTORS.get(workers)
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"ocr-worker-{workers}")
            _OCR_EXECUTORS[workers] = executor
        return executor


def _bounded_workers(value: int, item_count: int, upper: int) -> int:
    try:
        workers = int(value)
    except Exception:
        workers = 1
    return max(1, min(workers, item_count, upper))


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _collect_image_refs(markdown: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []

    for match in MARKDOWN_IMAGE_RE.finditer(markdown):
        src = match.group("src").strip()
        if src.startswith("<") and src.endswith(">"):
            src = src[1:-1]
        refs.append({"src": html.unescape(src), "start": match.start(), "end": match.end()})
        occupied.append((match.start(), match.end()))

    for match in HTML_IMAGE_RE.finditer(markdown):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        refs.append({"src": html.unescape(match.group("src").strip()), "start": match.start(), "end": match.end()})

    refs.sort(key=lambda item: item["start"])
    return refs


def _has_existing_ocr_block(markdown: str, image_end: int) -> bool:
    tail = markdown[image_end : image_end + 800]
    return bool(OCR_BLOCK_RE.match(tail))


def _load_image_bytes(src: str, config: BackfillConfig) -> tuple[bytes, str]:
    mapped = config.image_map.get(src) or config.image_map.get(src.lstrip("./"))
    if mapped:
        return _load_mapped_image(mapped, config)

    if src.startswith("data:image/"):
        return _load_data_uri(src)

    parsed = urlparse(src)
    if parsed.scheme in {"http", "https"}:
        response = requests.get(src, headers=config.download_headers, timeout=config.request_timeout)
        response.raise_for_status()
        suffix = _suffix_from_content_type(response.headers.get("content-type")) or Path(parsed.path).suffix or ".png"
        return response.content, suffix

    path = _resolve_local_path(src, config)
    return path.read_bytes(), path.suffix or ".png"


def _load_mapped_image(mapped: str, config: BackfillConfig) -> tuple[bytes, str]:
    if mapped.startswith("data:image/"):
        return _load_data_uri(mapped)
    if mapped.startswith("http://") or mapped.startswith("https://"):
        response = requests.get(mapped, headers=config.download_headers, timeout=config.request_timeout)
        response.raise_for_status()
        suffix = _suffix_from_content_type(response.headers.get("content-type")) or Path(urlparse(mapped).path).suffix or ".png"
        return response.content, suffix
    path = _resolve_local_path(mapped, config)
    return path.read_bytes(), path.suffix or ".png"


def _load_data_uri(uri: str) -> tuple[bytes, str]:
    header, payload = uri.split(",", 1)
    mime = header.split(";", 1)[0].replace("data:", "")
    suffix = mimetypes.guess_extension(mime) or ".png"
    return base64.b64decode(payload), suffix


def _resolve_local_path(src: str, config: BackfillConfig) -> Path:
    if not config.image_base_dir and not Path(src).is_absolute():
        raise ValueError(f"relative image path requires image_base_dir: {src}")

    decoded = unquote(src)
    path = Path(decoded)
    if not path.is_absolute():
        path = Path(config.image_base_dir or ".") / path
    path = path.resolve()

    roots = [Path(root).resolve() for root in config.allowed_roots]
    if config.image_base_dir:
        roots.append(Path(config.image_base_dir).resolve())
    env_roots = [root for root in os.getenv("OCR_BACKFILL_ALLOWED_ROOTS", "").split(os.pathsep) if root]
    roots.extend(Path(root).resolve() for root in env_roots)

    if roots and not any(path == root or root in path.parents for root in roots):
        raise ValueError(f"image path is outside allowed roots: {path}")
    if not path.exists():
        raise FileNotFoundError(f"image not found: {path}")
    return path


def _image_size(image_bytes: bytes) -> tuple[int, int]:
    with tempfile.NamedTemporaryFile(suffix=".img") as tmp:
        tmp.write(image_bytes)
        tmp.flush()
        with Image.open(tmp.name) as image:
            return image.size


def _ocr_bytes(image_bytes: bytes, suffix: str, engine: OcrEngine, config: BackfillConfig) -> str:
    with tempfile.NamedTemporaryFile(suffix=".png" if config.preprocess_images else (suffix or ".png")) as tmp:
        tmp.write(_preprocess_image_bytes(image_bytes, config) if config.preprocess_images else image_bytes)
        tmp.flush()
        return engine.image_to_text(tmp.name, config.lang)


def _preprocess_image_bytes(image_bytes: bytes, config: BackfillConfig) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        processed = image.convert("RGB")
        if config.upscale_factor and config.upscale_factor > 1:
            width, height = processed.size
            new_size = (max(1, int(width * config.upscale_factor)), max(1, int(height * config.upscale_factor)))
            processed = processed.resize(new_size, Image.Resampling.LANCZOS)
        if config.autocontrast:
            processed = ImageOps.autocontrast(processed)
        if config.sharpen:
            processed = processed.filter(ImageFilter.SHARPEN)
        output = io.BytesIO()
        processed.save(output, format="PNG", optimize=True)
        return output.getvalue()


def _load_engine(preferred: str, lang: str) -> OcrEngine:
    candidates = [preferred] if preferred != "auto" else ["rapidocr", "paddleocr", "tesseract"]
    errors: list[str] = []
    for name in candidates:
        try:
            if name == "rapidocr":
                engine = RapidOcrEngine()
            elif name == "paddleocr":
                engine = PaddleOcrEngine()
            elif name == "tesseract":
                engine = TesseractOcrEngine()
            else:
                raise ValueError(f"unsupported OCR engine: {name}")
            # Smoke-test imports lazily enough to fail before processing many images.
            if isinstance(engine, RapidOcrEngine):
                try:
                    import rapidocr  # noqa: F401
                except Exception:
                    import rapidocr_onnxruntime  # noqa: F401
            elif isinstance(engine, PaddleOcrEngine):
                import paddleocr  # noqa: F401
            elif isinstance(engine, TesseractOcrEngine):
                import pytesseract  # noqa: F401
            return engine
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("No OCR engine is available. Install rapidocr, paddleocr, or pytesseract. " + "; ".join(errors))


def _rapidocr_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, tuple):
        result = result[0]
    if hasattr(result, "txts"):
        txts = getattr(result, "txts", None)
        if not txts:
            return ""
        return "\n".join(str(x) for x in txts if x)
    lines: list[str] = []
    for item in result or []:
        if isinstance(item, dict):
            value = item.get("text") or item.get("rec_text") or item.get("txt")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            value = item[1][0] if isinstance(item[1], (list, tuple)) else item[1]
        else:
            value = item
        if value:
            lines.append(str(value))
    return "\n".join(lines)


def _paddleocr_text(result: Any) -> str:
    lines: list[str] = []

    def walk(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for key in ("rec_texts", "texts"):
                if key in value and isinstance(value[key], list):
                    lines.extend(str(x) for x in value[key] if x)
                    return
            text = value.get("text") or value.get("rec_text")
            if text:
                lines.append(str(text))
            return
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and isinstance(value[1], (list, tuple)) and value[1]:
                maybe_text = value[1][0]
                if isinstance(maybe_text, str):
                    lines.append(maybe_text)
                    return
            for child in value:
                walk(child)

    walk(result)
    return "\n".join(lines)


def _paddle_lang(lang: str) -> str:
    if lang in {"ch", "zh", "zh-cn", "ch_sim", "chinese"}:
        return "ch"
    if lang in {"en", "english"}:
        return "en"
    return lang or "ch"


def _normalize_ocr_text(text: str, max_chars: int) -> str:
    lines = []
    previous = ""
    for raw in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    normalized = "\n".join(lines).strip()
    if max_chars and len(normalized) > max_chars:
        normalized = normalized[:max_chars].rstrip() + "\n...（图片 OCR 结果过长，已截断）"
    return normalized


def _format_ocr_block(text: str, src: str, digest: str, title: str) -> str:
    safe_src = html.escape(src, quote=True)
    return (
        "\n\n"
        f"<!-- image_ocr:start src=\"{safe_src}\" sha256=\"{digest}\" -->\n"
        f"**【{title}】**\n\n"
        f"{text}\n"
        "<!-- image_ocr:end -->"
    )


def _format_failed_block(src: str, reason: str, title: str) -> str:
    safe_src = html.escape(src, quote=True)
    safe_reason = html.escape(reason[:300], quote=False)
    return (
        "\n\n"
        f"<!-- image_ocr:start src=\"{safe_src}\" status=\"failed\" -->\n"
        f"**【{title}失败】** {safe_reason}\n"
        "<!-- image_ocr:end -->"
    )


def _apply_replacements(text: str, replacements: list[tuple[int, int, str]]) -> str:
    if not replacements:
        return text
    result = text
    for start, end, value in sorted(replacements, key=lambda item: item[0], reverse=True):
        result = result[:start] + value + result[end:]
    return result


def _suffix_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
