from __future__ import annotations

from pathlib import Path

from PIL import Image

from ocr_backfill.core import BackfillConfig, OcrEngine, enrich_markdown


class DummyEngine(OcrEngine):
    def image_to_text(self, image_path: str, lang: str) -> str:
        return "识别文本\n识别文本\n第二行"


def test_enrich_markdown_inserts_ocr_after_markdown_image(tmp_path: Path, monkeypatch) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_path = image_dir / "a.png"
    Image.new("RGB", (200, 100), "white").save(image_path)

    import ocr_backfill.core as core

    monkeypatch.setattr(core, "_load_engine", lambda preferred, lang: DummyEngine())
    result = enrich_markdown(
        "前文\n\n![](images/a.png)\n\n后文",
        BackfillConfig(image_base_dir=str(tmp_path), ocr_engine="dummy"),
    )

    assert result.ocr_count == 1
    assert "<!-- image_ocr:start" in result.markdown
    assert "**【图片OCR】**" in result.markdown
    assert "识别文本\n第二行" in result.markdown


def test_enrich_markdown_skips_small_images(tmp_path: Path, monkeypatch) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    Image.new("RGB", (20, 20), "white").save(image_dir / "small.png")

    import ocr_backfill.core as core

    monkeypatch.setattr(core, "_load_engine", lambda preferred, lang: DummyEngine())
    result = enrich_markdown(
        "![](images/small.png)",
        BackfillConfig(image_base_dir=str(tmp_path), min_width=80, min_height=80),
    )

    assert result.ocr_count == 0
    assert result.skipped_count == 1
    assert result.items[0].reason == "image_too_small"


def test_enrich_markdown_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    Image.new("RGB", (200, 100), "white").save(image_dir / "a.png")

    import ocr_backfill.core as core

    monkeypatch.setattr(core, "_load_engine", lambda preferred, lang: DummyEngine())
    first = enrich_markdown("![](images/a.png)", BackfillConfig(image_base_dir=str(tmp_path)))
    second = enrich_markdown(first.markdown, BackfillConfig(image_base_dir=str(tmp_path)))

    assert first.markdown == second.markdown
    assert second.ocr_count == 0
    assert second.skipped_count == 1
    assert second.items[0].reason == "already_backfilled"
