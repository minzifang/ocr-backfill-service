from __future__ import annotations

import argparse
from pathlib import Path

from .core import BackfillConfig, enrich_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill OCR text after Markdown image references.")
    parser.add_argument("--markdown", required=True, help="Input Markdown file.")
    parser.add_argument("--output", required=True, help="Output Markdown file.")
    parser.add_argument("--image-base-dir", default=None, help="Base directory for relative image paths.")
    parser.add_argument("--engine", default="auto", choices=["auto", "rapidocr", "paddleocr", "tesseract"])
    parser.add_argument("--lang", default="ch")
    parser.add_argument("--max-images", type=int, default=80)
    parser.add_argument("--min-width", type=int, default=80)
    parser.add_argument("--min-height", type=int, default=80)
    parser.add_argument("--min-text-chars", type=int, default=5)
    args = parser.parse_args()

    source = Path(args.markdown).read_text(encoding="utf-8")
    config = BackfillConfig(
        image_base_dir=args.image_base_dir,
        ocr_engine=args.engine,
        lang=args.lang,
        max_images=args.max_images,
        min_width=args.min_width,
        min_height=args.min_height,
        min_text_chars=args.min_text_chars,
    )
    result = enrich_markdown(source, config)
    Path(args.output).write_text(result.markdown, encoding="utf-8")
    print(
        f"images={result.image_count} ocr={result.ocr_count} "
        f"skipped={result.skipped_count} failed={result.failed_count}"
    )


if __name__ == "__main__":
    main()
