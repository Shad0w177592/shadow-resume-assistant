# OpenAI API Key 配置

1. 在 OpenAI 平台创建自己的 API Key，并确保账户具有可用额度。
2. 打开“设置 → AI 服务”。
3. 使用官方 OpenAI 时将 Base URL 留空；使用中转网关时填写服务商提供的 API 根地址，例如 `https://gateway.example.com/v1`。
4. 填写该服务对应的 API Key 和模型名称。网关模型名以服务商说明为准。
5. 点击保存。应用会发出一个最小的结构化中文请求；只有测试成功后，新 Key 才会替换原 Key。
6. 保存并返回首页。

应用生产模式使用 OpenAI Responses API，并要求模型返回严格 JSON。中转网关必须兼容 `/responses` 和 Structured Outputs；语音功能还要求兼容 `/audio/transcriptions`。API Key 只存入 Windows 凭据管理器。不要把 Key 写入简历、截图、备份说明或发给他人。

常见错误：

- “未配置 API Key”：进入设置完成配置；
- “API Key 无效”：检查 Key 是否复制完整、是否被撤销；
- “额度或频率限制”：检查账单、额度，稍后重试；
- “模型不可用”：改用账户可访问的模型；
- “网络或超时”：检查网络、代理和防火墙；
- “模型输出无效”：重试；反复发生时保留错误信息用于排查。
