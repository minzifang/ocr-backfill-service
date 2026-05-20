# OCR Backfill Service

English | [中文](#中文说明)

OCR Backfill Service is a small HTTP and CLI service for enriching parsed Markdown before it enters a Dify knowledge-base pipeline. It detects Markdown or HTML image references, runs OCR on reachable images, and inserts the recognized text back next to the original image reference.

Typical workflow:

```text
MinerU / Docling parser
  -> OCR Backfill Service
  -> validation
  -> chunking
  -> knowledge-base indexing
```

## Features

- Supports Markdown image syntax and HTML `<img src="...">` tags.
- Supports image URLs, data URIs, local paths with explicit allowed roots, and path maps.
- Provides PaddleOCR, RapidOCR, and Tesseract engine adapters.
- Provides CPU, CPU-fast, RapidOCR, GPU, and GPU-shadow Docker Compose examples.
- Exposes health and readiness endpoints for Docker and Dify integration.

## Quick Start

Start the default CPU PaddleOCR service:

```bash
docker compose -f docker-compose.ocr.yml up -d --build
curl http://127.0.0.1:8018/ready
```

Call the API:

```bash
curl -sS http://127.0.0.1:8018/v1/ocr-backfill \
  -H 'Content-Type: application/json' \
  -d '{
    "markdown": "![](https://example.invalid/test.jpg)",
    "ocr_engine": "paddleocr",
    "lang": "ch",
    "max_images": 1
  }'
```

If Dify and this service share a Docker network, use:

```text
http://ocr-backfill:8018/v1/ocr-backfill
```

If they run on different hosts, replace `<host-ip>` with your own server address:

```text
http://<host-ip>:8018/v1/ocr-backfill
```

## Local Development

```bash
uv sync
uv pip install -e ".[rapid,dev]"
PYTHONPATH=src OCR_BACKFILL_ENGINE=rapidocr uv run python -m ocr_backfill.server
```

Run tests:

```bash
PYTHONPATH=src pytest -q
```

## Security Notes

For local file OCR, always configure `OCR_BACKFILL_ALLOWED_ROOTS` and only point it at directories that are safe for the service to read. Do not expose this service directly to the public internet without authentication, request size limits, and network-level controls.

## License

MIT. See [LICENSE](LICENSE).

## 中文说明

这是从 `SQZSKRAGAS` 拆出的独立 OCR 回填服务，用于放在 Dify 文档解析节点之后、分块入库之前。它扫描 Markdown 中的图片引用，对图片执行 OCR，并把识别结果插回图片原位置后面。

典型链路：

```text
MinerU / Docling 解析
  -> OCR Backfill Service
  -> 解析结果校验
  -> 分块
  -> 知识库入库
```

## 输出格式

输入：

```md
![](images/a.jpg)
```

输出：

```md
![](images/a.jpg)

<!-- image_ocr:start src="images/a.jpg" sha256="..." -->
**【图片OCR】**

这里是图片中识别出的文字
<!-- image_ocr:end -->
```

## Docker 启动

CPU PaddleOCR 正式服务：

```bash
docker compose -f docker-compose.ocr.yml up -d --build
curl http://127.0.0.1:8018/ready
```

CPU fast 影子服务，使用 mobile 模型，端口 `8020`：

```bash
docker compose -f docker-compose.ocr.cpu-fast.yml up -d --build
curl http://127.0.0.1:8020/ready
```

RapidOCR 轻量影子服务，端口 `8021`：

```bash
docker compose -f docker-compose.ocr.rapid.yml up -d --build
curl http://127.0.0.1:8021/ready
```

RTX 2070 等 CUDA 11.8 环境可先启动 GPU 影子服务：

```bash
docker compose -f docker-compose.ocr.gpu-shadow.yml up -d --build
curl http://127.0.0.1:8019/ready
```

确认稳定后再切正式 GPU 服务：

```bash
docker compose -f docker-compose.ocr.gpu.yml up -d --build
curl http://127.0.0.1:8018/ready
```

## 打包部署

```bash
bash scripts/package_ocr_service.sh
```

会生成：

```text
dist/ocr-service-deploy-0.2.10.tar.gz
```

服务器更新示例：

```bash
cd /opt/service/ocr
tar -xzf /path/to/ocr-service-deploy-0.2.10.tar.gz
docker compose -f docker-compose.ocr.yml up -d --build
```

## 本地 Python 启动

基础依赖：

```bash
uv sync
```

CPU 环境建议先装 RapidOCR：

```bash
uv pip install -e ".[rapid]"
PYTHONPATH=src OCR_BACKFILL_ENGINE=rapidocr OCR_BACKFILL_PORT=8018 uv run python -m ocr_backfill.server
```

使用 PaddleOCR：

```bash
uv pip install -e ".[paddle]"
PYTHONPATH=src OCR_BACKFILL_ENGINE=paddleocr OCR_BACKFILL_PORT=8018 uv run python -m ocr_backfill.server
```

健康检查：

```bash
curl http://127.0.0.1:8018/health
curl http://127.0.0.1:8018/ready
```

## API 示例

```bash
curl -sS http://127.0.0.1:8018/v1/ocr-backfill \
  -H 'Content-Type: application/json' \
  -d '{
    "markdown": "![](https://example.invalid/test.jpg)",
    "ocr_engine": "paddleocr",
    "lang": "ch",
    "max_images": 1,
    "download_workers": 8,
    "ocr_workers": 2
  }'
```

如果 Markdown 中的图片是相对路径，例如 `images/a.jpg`，请求体需要提供 `image_base_dir`，并建议通过 `OCR_BACKFILL_ALLOWED_ROOTS` 限制服务可读目录：

```bash
PYTHONPATH=src OCR_BACKFILL_ALLOWED_ROOTS=/tmp/out uv run python -m ocr_backfill.server
```

```json
{
  "markdown": "...",
  "image_base_dir": "/tmp/out/test/office"
}
```

如果图片已经是 Dify/MinerU 可访问 URL，通常不需要 `image_base_dir`。

## Dify 接入

如果 OCR 服务和 Dify 在同一个 Docker network，插件或 HTTP 节点使用：

```text
http://ocr-backfill:8018/v1/ocr-backfill
```

如果不在同一个 Docker network，使用宿主机 IP，把 `<host-ip>` 替换成自己的服务器地址：

```text
http://<host-ip>:8018/v1/ocr-backfill
```

配套 Dify 插件已拆到：

```text
../dify-ocr-backfill-plugin
```
