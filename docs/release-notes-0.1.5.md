# 影子简历助手 0.1.5

- 新增 Responses API 与 Chat Completions 两种接口模式；
- OpenAI 官方地址继续默认使用 Responses API 严格结构化输出；
- JUAPI 等兼容网关可选择 Chat Completions 模式；
- Chat Completions 使用精简请求，并在本地继续执行 JSON Schema 校验；
- 首次配置页与设置页新增接口模式选择和 JUAPI 填写说明；
- 中转网关服务端错误现在会显示 HTTP 状态和针对性的排查提示；
- 新增真实 OpenAI SDK 路径拼接测试，确认 JUAPI 请求发送至 `/v1/chat/completions`。
