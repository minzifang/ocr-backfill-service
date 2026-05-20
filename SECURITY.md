# Security Policy / 安全政策

## English

Please do not report security issues in public issues. Send a private advisory or contact the maintainers through the repository owner.

This service can read local files when `image_base_dir` and `OCR_BACKFILL_ALLOWED_ROOTS` are configured. Treat it as an internal service by default:

- Do not expose it directly to the public internet.
- Restrict readable roots with `OCR_BACKFILL_ALLOWED_ROOTS`.
- Avoid logging secrets, signed URLs, private documents, or customer content.
- Use network controls, authentication, and request limits in production.

## 中文

请不要在公开 Issue 中披露安全问题。请通过 GitHub 私密安全公告或仓库所有者联系维护者。

当配置了 `image_base_dir` 和 `OCR_BACKFILL_ALLOWED_ROOTS` 时，本服务可以读取本地文件。默认应将它视为内网服务：

- 不要直接暴露到公网。
- 使用 `OCR_BACKFILL_ALLOWED_ROOTS` 限制可读目录。
- 避免记录密钥、签名 URL、私有文档或客户内容。
- 生产环境请加网络访问控制、认证和请求大小限制。
