# Changelog

## 0.2.10 - 2026-05-20

- 从 `SQZSKRAGAS` 拆出为独立 `ocr-backfill-service` 项目，放到 `Www` 目录下维护。
- 新增独立 `pyproject.toml`、README 和服务级变更记录，保留 Docker Compose、Dockerfile、requirements、测试与打包脚本。
- 补齐开源仓库配置：MIT License、双语 README、贡献指南、安全政策、行为准则、Issue/PR 模板和 GitHub Actions CI。
- 清理公开文档中的内网地址示例，改用占位符地址。

## 0.2.9 - 2026-05-13

- OCR 图片识别线程池改为按 worker 数常驻复用，避免批量入库时每个请求反复创建线程并重新初始化 PaddleOCR 模型。

## 0.2.8 - 2026-05-13

- OCR 服务新增全局请求限流 `OCR_BACKFILL_REQUEST_WORKERS`，批量入库时多个文档会排队执行，避免每个文档内部并发叠加后把 CPU OCR 服务打满。
- OCR 服务响应新增 `queue_wait_seconds`，用于观察批量入库时请求在 OCR 队列中等待了多久。
- CPU 与 CPU fast Docker 配置默认 `OCR_BACKFILL_REQUEST_WORKERS=1`，保留单文档内部 `OCR_BACKFILL_OCR_WORKERS=2`。

## 0.2.7 - 2026-05-13

- OCR 服务端优先使用容器环境变量 `OCR_BACKFILL_ENGINE`，避免旧版 Dify 插件硬编码 `paddleocr` 导致 RapidOCR 服务被错误强制走 PaddleOCR。

## 0.2.6 - 2026-05-13

- RapidOCR 空识别结果现在返回空字符串，不再因为 `txts=None` 导致服务启动失败。
- OCR 服务预热失败不再中断容器启动，会记录 warning 并在真实请求时继续重试。

## 0.2.5 - 2026-05-13

- RapidOCR 快速服务显式加入 `onnxruntime` 依赖，修复启动时报 `ImportError: onnxruntime is not installed`。

## 0.2.4 - 2026-05-13

- 新增 RapidOCR 快速影子服务：`docker-compose.ocr.rapid.yml`、`deploy/ocr-service/Dockerfile.rapid`、`requirements-ocr-service-rapid.txt`，默认映射到 `8021`。
- Dify OCR 插件调用外部服务失败或超时时不再抛 RuntimeError，改为返回原文和结构化失败 JSON，避免错误文本直接进入后续节点。

## 0.2.3 - 2026-05-13

- PaddleOCR 初始化新增环境变量：`OCR_PADDLE_TEXT_DETECTION_MODEL`、`OCR_PADDLE_TEXT_RECOGNITION_MODEL`、`OCR_PADDLE_TEXTLINE_ORIENTATION`、`OCR_PADDLE_DOC_ORIENTATION`、`OCR_PADDLE_DOC_UNWARPING`。
- CPU 正式版默认关闭文本行方向分类、文档方向分类和文档矫正，但不强制切换轻量模型，避免默认降低准确率。
- 新增 `docker-compose.ocr.cpu-fast.yml`，可在 `8020` 启动 mobile 模型 CPU 影子服务，用于单独压测速度。

## 0.2.2 - 2026-05-13

- OCR 服务新增 `download_workers` 和 `ocr_workers`，支持图片下载并发和多图 OCR 并发。
- PaddleOCR / RapidOCR 实例改为按 worker 线程隔离，避免并发 OCR 时多个线程抢同一个推理实例。
- OCR 服务响应新增 `elapsed_seconds`，Dify 插件同步透传总耗时与并发参数。
- Docker 默认使用 `OCR_BACKFILL_DOWNLOAD_WORKERS=8`、`OCR_BACKFILL_OCR_WORKERS=2`，可按机器配置调高或调低。
- 新增 RTX 2070 可用的 GPU 部署文件：`docker-compose.ocr.gpu.yml`、`deploy/ocr-service/Dockerfile.gpu`、`requirements-ocr-service-gpu-cu118.txt`。
- 新增 `docker-compose.ocr.gpu-shadow.yml`，可在 `8019` 启动 GPU 影子服务，不影响当前 `8018` CPU 服务；影子服务默认 `OCR_BACKFILL_OCR_WORKERS=1`，便于和现有 MinerU GPU 服务共存测试。

## 0.2.1 - 2026-05-13

- OCR 服务返回每张图片的 `elapsed_seconds` 和 `ocr_seconds`，便于排查慢图和整体耗时。
- OCR 服务新增可选图片预处理参数：`preprocess_images`、`upscale_factor`、`autocontrast`、`sharpen`。
- Dify OCR 插件透传上述预处理参数，并重新生成 `ocr_backfill-0.2.1.signed.difypkg`。
- 新增 `scripts/package_ocr_service.sh`，将 OCR Docker 服务相关文件打成单个部署包。

## 0.2.0 - 2026-05-13

- 新增独立 PaddleOCR 常驻服务 Docker 部署文件：`requirements-ocr-service.txt`、`deploy/ocr-service/Dockerfile`、`docker-compose.ocr.yml`。
- OCR 服务启动时可通过 `OCR_BACKFILL_PRELOAD=1` 预加载 PaddleOCR 模型，供 Dify HTTP 节点调用。
- 服务端 PaddleOCR 初始化支持 `OCR_PADDLE_DEVICE`，并默认禁用 MKL-DNN/PIR 路径。
- Dify OCR 插件改为外部 OCR 服务客户端，不再在 plugin-daemon 中安装或运行 PaddleOCR。
- 重新生成 `ocr_backfill-0.2.0.signed.difypkg`。
