# Contributing / 贡献指南

## English

Thank you for considering a contribution. Please keep changes focused, include tests for behavior changes, and avoid committing generated artifacts, model files, private endpoints, tokens, or customer data.

Before opening a pull request:

```bash
PYTHONPATH=src pytest -q
python -m py_compile src/ocr_backfill/*.py
```

## 中文

感谢贡献。请尽量保持改动聚焦；如果修改行为，请补充或更新测试；不要提交生成产物、模型文件、私有服务地址、令牌或客户数据。

提交 PR 前建议运行：

```bash
PYTHONPATH=src pytest -q
python -m py_compile src/ocr_backfill/*.py
```
