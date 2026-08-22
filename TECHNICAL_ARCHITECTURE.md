# 影子简历助手技术架构设计 V1

> 状态：已确认（2026-08-22）  
> 适用范围：V1 Windows 本地桌面版  
> 依据：[PRD.md](./PRD.md)、[DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)、[VISUAL_DESIGN_SPEC.md](./VISUAL_DESIGN_SPEC.md)  
> 目标：把产品需求转化为可以直接拆分、编码、测试和打包的技术边界。

---

## 1. 架构结论

V1 采用“Electron 桌面壳 + React 界面 + Python 本地服务 + SQLite 本地数据库”的单机架构：

```text
用户
  │
  ▼
Electron 桌面应用
  ├─ Renderer：React + TypeScript 页面
  ├─ Preload：有限的系统能力桥接
  └─ Main：窗口、文件选择、Python 进程、PDF 打印、应用生命周期
         │
         │ 仅本机 HTTP：127.0.0.1 + 随机端口 + 临时会话令牌
         ▼
Python 本地服务
  ├─ FastAPI：接口与参数校验
  ├─ 应用服务：资料、岗位、简历、版本、备份
  ├─ AI 工作流：解析、匹配、生成、修改、事实检查
  ├─ 文档服务：PDF/DOCX/MD/TXT 导入，DOCX 导出
  └─ 数据层：SQLite + 本地文件目录 + Windows 凭据管理器
         │
         ├─ 本机磁盘：业务数据、附件、草稿、版本、备份
         └─ HTTPS：OpenAI API；V2 可替换 DeepSeek 等提供商
```

关键原则：

- 用户数据默认只保存在本机，不建设账号、云数据库和云端业务服务；
- 只有确实需要 AI 处理的文本才发送给模型服务；
- 界面不直接读写数据库、不直接持有系统权限、不直接调用模型 API；
- Python 服务只监听 `127.0.0.1`，不允许局域网或公网访问；
- 安装包包含 Electron 和 Python 运行时，用户不需要安装 Node.js 或 Python；
- 所有可变数据放在 Windows 用户数据目录，禁止写进安装目录。

---

## 2. 技术栈基线

| 层级 | V1 选择 | 用途 |
|---|---|---|
| 桌面运行时 | Electron | Windows 窗口、系统文件选择、麦克风权限、进程管理、打印 PDF |
| 前端 | React + TypeScript + Vite | 页面与交互 |
| 路由 | React Router | 页面导航与路由保护 |
| 服务端状态 | TanStack Query | 请求、缓存、失效和任务状态刷新 |
| 本地界面状态 | Zustand | 当前岗位、编辑选区、面板开关等短期状态 |
| 表单 | React Hook Form + Zod | 动态表单、校验和错误提示 |
| 后端 | Python + FastAPI + Uvicorn | 本地 API、工作流和文档处理 |
| 数据模型 | Pydantic | 请求、响应及 AI 结构化输出校验 |
| ORM/迁移 | SQLAlchemy + Alembic | SQLite 访问和版本迁移 |
| 数据库 | SQLite，开启 WAL | 单用户结构化数据与事务 |
| Word | python-docx | DOCX 读取与生成 |
| PDF 读取 | PyMuPDF | 文本型 PDF 提取 |
| PDF 导出 | Electron `webContents.printToPDF` | 将统一打印 HTML 生成 PDF |
| 凭据 | Python `keyring` + Windows Credential Manager | API Key 安全保存 |
| 后端打包 | PyInstaller `onedir` | 将 Python 服务及依赖打进应用资源 |
| 应用打包 | electron-builder + NSIS | 生成 Windows x64 安装包 |
| 前端测试 | Vitest + React Testing Library + Playwright | 单元、组件和端到端测试 |
| 后端测试 | pytest | 单元、接口、迁移与工作流测试 |

版本策略：正式建项时锁定经过 Spike 验证的具体版本；依赖升级单独提交，禁止使用浮动的 `latest` 作为可复现构建依据。

---

## 3. 进程职责

### 3.1 Electron Main 主进程

只负责系统级能力：

- 创建与恢复主窗口；
- 启动、监控和关闭 Python 本地服务；
- 打开系统文件/文件夹选择器；
- 校验允许导入的扩展名；
- 管理麦克风权限请求；
- 用隐藏打印窗口生成 PDF；
- 打开导出目录和外部帮助链接；
- 应用退出前通知后端完成事务并安全关闭；
- 写入不含隐私正文的桌面进程日志。

主进程不负责业务规则，不直接修改 SQLite，不存储简历正文。

### 3.2 Preload 桥接层

通过 `contextBridge` 只暴露按功能命名的方法，例如：

```ts
window.shadowResume.dialog.selectImportFiles()
window.shadowResume.dialog.selectExportDirectory()
window.shadowResume.pdf.export(request)
window.shadowResume.shell.openDirectory(pathToken)
window.shadowResume.app.getRuntimeInfo()
```

禁止暴露整个 `ipcRenderer`、Node.js `fs`、`child_process` 或任意命令执行能力。IPC 请求必须校验调用来源、参数结构和可访问路径。

### 3.3 React Renderer 渲染进程

负责：

- 页面、表单、工作台和状态反馈；
- 调用本地 FastAPI；
- 呈现 AI 任务进度、对比结果和可恢复错误；
- 草稿编辑状态与服务端数据同步；
- 用户触发的保存、导出、备份、恢复和清除确认。

禁止：

- 启用 Node integration；
- 直接操作文件系统或系统进程；
- 直接连接 OpenAI；
- 在 `localStorage`、前端日志或错误对象中保存 API Key；
- 加载任意远程网页或执行远程脚本。

### 3.4 Python 本地服务

负责所有业务能力：

- CRUD、自动保存、岗位隔离和显式版本保存；
- 文档提取、导入暂存和用户确认后入库；
- JD 分析、证据匹配、简历生成、段落修改和事实检查；
- 隐私字段过滤、AI 请求构造和响应校验；
- Word 导出、备份、恢复、清除与数据迁移；
- API Key 读写和模型连通性测试；
- 长任务进度、取消、失败恢复和审计元数据。

生产环境只启动一个 Uvicorn worker，不启用 `reload`，避免桌面单用户场景出现多进程数据库和任务状态不一致。

---

## 4. 本地服务启动与通信

### 4.1 启动顺序

1. Electron Main 获取应用数据目录并创建必要子目录；
2. 生成 256 位随机会话令牌，不落盘；
3. 启动打包后的 Python 可执行文件，通过标准输入传递令牌和数据目录；
4. Python 绑定 `127.0.0.1:0`，由系统分配空闲端口；
5. Python 完成目录检查、数据库迁移和恢复检查；
6. Python 向标准输出写一行机器可读 readiness JSON：端口、协议版本、进程号；
7. Main 验证 readiness 后再显示主窗口；
8. Renderer 从 Main 获取仅存内存的连接信息并请求 `/api/v1/runtime/health`；
9. 若超时或版本不兼容，显示“本地服务启动失败”恢复页，并允许重试或打开诊断目录。

### 4.2 通信规则

- 地址固定为回环地址，端口每次启动随机；
- 所有 `/api/v1/*` 请求都带 `Authorization: Bearer <session-token>`；
- 后端同时校验 `Origin`，只允许应用自身来源；
- CORS 只允许当前应用来源，不使用 `*`；
- 会话令牌只保存在内存，应用退出即失效；
- 请求和响应统一使用 Pydantic Schema；
- API 前缀固定为 `/api/v1`，破坏性修改使用新版本前缀；
- 开发环境保留 OpenAPI 文档，生产构建关闭 `/docs`、`/redoc` 和公开的 `/openapi.json`；
- 上传接口限制扩展名、文件尺寸和单次文件数，并使用应用自己的暂存目录。

### 4.3 长任务

AI 分析、生成、导入和导出统一建立 `task_run`：

```text
queued → running → succeeded
                 ├→ failed（可重试）
                 └→ cancelled
```

V1 使用“创建任务 REST 接口 + 状态轮询”，默认每 1 秒轮询；任务完成后停止。这样比 WebSocket 更容易打包、测试和恢复。每个任务必须支持：

- 当前步骤和用户可读提示；
- 创建、开始、完成时间；
- 关联岗位、简历或导入批次；
- 可重试错误码；
- 用户取消；
- 应用异常退出后的 `interrupted` 恢复标记。

---

## 5. 后端分层

```text
API Router
  ↓ 参数校验、鉴权、错误映射
Application Service / Use Case
  ↓ 一个完整用户操作的事务与编排
Domain
  ↓ 业务规则、状态转换、真实性约束
Repository / Gateway
  ↓
SQLite | 文件系统 | Windows Credential Manager | OpenAI
```

建议模块：

| 模块 | 主要职责 |
|---|---|
| `profile` | 个人资料栏目、经历、技能、照片元数据 |
| `imports` | 文件解析、导入批次、字段候选、确认合并 |
| `jobs` | 目标岗位、JD 原文、岗位状态 |
| `matching` | 要求拆解、证据候选、匹配报告 |
| `resumes` | 配置、草稿、栏目顺序、版面结构 |
| `revisions` | 段落级 AI 建议、差异、接受/拒绝 |
| `versions` | 显式保存的历史版本与对比 |
| `exports` | Word/PDF 导出记录和布局检查 |
| `ai` | 提供商适配、提示词、Schema、重试、评测 |
| `privacy` | 字段过滤、脱敏预览、发送范围 |
| `backup` | 备份、校验、恢复、清除 |
| `settings` | 非敏感设置；密钥只存凭据管理器 |
| `tasks` | 长任务、取消、恢复和进度 |

规则：API Router 不写业务逻辑；Repository 不调用 AI；AI Provider 不直接写数据库；跨模块流程由 Application Service 编排。

---

## 6. 前端模块与路由

| 路由 | 页面 | 主要后端模块 |
|---|---|---|
| `/welcome` | 首次启动 | settings、runtime |
| `/home` | 首页 | jobs、resumes、tasks |
| `/profile` | 个人资料 | profile、imports |
| `/imports/:batchId` | 导入确认 | imports、profile |
| `/jobs` | 目标岗位列表 | jobs |
| `/jobs/:jobId` | 岗位详情与匹配 | jobs、matching |
| `/resume/new/:jobId` | 简历配置 | resumes、matching |
| `/workbench/:resumeId` | 简历工作台 | resumes、revisions、tasks |
| `/versions/:resumeId` | 历史版本 | versions |
| `/settings` | 设置与数据管理 | settings、backup、runtime |

路由进入前只判断“是否完成首次启动”；资料为空不拦截，因为 PRD 已确认所有资料栏目均可选填。生成前只提示证据不足，不强迫用户补齐固定字段。

---

## 7. API 边界草案

API 只列资源边界，字段在下一份《本地数据结构设计》中定稿。

```text
GET    /api/v1/runtime/health
GET    /api/v1/runtime/info

GET    /api/v1/profile
PATCH  /api/v1/profile
POST   /api/v1/profile/sections
PATCH  /api/v1/profile/sections/{id}
DELETE /api/v1/profile/sections/{id}

POST   /api/v1/imports
GET    /api/v1/imports/{id}
POST   /api/v1/imports/{id}/confirm
DELETE /api/v1/imports/{id}

GET    /api/v1/jobs
POST   /api/v1/jobs
GET    /api/v1/jobs/{id}
PATCH  /api/v1/jobs/{id}
POST   /api/v1/jobs/{id}/analyze
GET    /api/v1/jobs/{id}/match-report

POST   /api/v1/resumes
GET    /api/v1/resumes/{id}
PATCH  /api/v1/resumes/{id}/draft
POST   /api/v1/resumes/{id}/generate
POST   /api/v1/resumes/{id}/revisions
POST   /api/v1/resumes/{id}/revisions/{revisionId}/accept
POST   /api/v1/resumes/{id}/revisions/{revisionId}/reject
POST   /api/v1/resumes/{id}/versions
GET    /api/v1/resumes/{id}/versions

POST   /api/v1/exports/docx
POST   /api/v1/exports/pdf/prepare

GET    /api/v1/tasks/{id}
POST   /api/v1/tasks/{id}/cancel
POST   /api/v1/tasks/{id}/retry

GET    /api/v1/settings
PATCH  /api/v1/settings
POST   /api/v1/settings/ai-key
POST   /api/v1/settings/ai-connection-test

POST   /api/v1/backups
POST   /api/v1/backups/inspect
POST   /api/v1/backups/restore
POST   /api/v1/data/clear-preview
POST   /api/v1/data/clear-confirm
```

删除或清除接口必须采用显式确认令牌，防止前端重复点击或错误调用直接执行不可恢复操作。

---

## 8. AI 架构边界

### 8.1 提供商接口

业务代码只能依赖统一接口：

```python
class AIProvider(Protocol):
    def test_connection(...): ...
    def generate_structured(...): ...
    def transcribe_audio(...): ...
```

V1 实现 OpenAI Provider；模型名、基础地址、超时和重试由 Provider 配置承担。V2 接入 DeepSeek 时新增适配器，不修改岗位匹配和简历生成业务代码。语音能力单独声明，不能假设所有文本模型提供商都有转写接口。

### 8.2 工作流而非单次大提示词

```text
输入预处理
  → 隐私过滤
  → 结构化解析
  → 证据检索与引用
  → 生成或修改
  → Schema 校验
  → 事实/数字/经历检查
  → 版面约束检查
  → 用户确认
```

每一步都有独立输入输出 Schema、提示词版本、错误类型和测试样例。模型不得直接写数据库；只有校验通过且用户触发确认的结果才能进入草稿或资料库。

### 8.3 真实性控制

- 每个生成要点保存 `source_evidence_ids`；
- 姓名、联系方式、组织名、时间、技能、数字成果等受保护事实只能来自用户资料或明确输入；
- 无证据时允许概括和改善表达，不允许补造新经历、技能或数字；
- 事实检查失败时保留原草稿并显示问题，不静默覆盖；
- 用户可继续编辑自己的内容，但 AI 生成链路始终执行不可关闭的真实性检查。

详细 Schema、提示词、模型参数和评测集在《AI 工作流与提示词设计》中确认。

---

## 9. 文件导入与导出

### 9.1 导入

```text
系统文件选择器
  → Electron 校验扩展名
  → 后端复制到 imports/staging/{batch_id}
  → 本地提取纯文本
  → AI 结构化归类
  → 用户逐项确认
  → 事务写入资料库
  → 删除暂存副本或按用户选择保留原附件
```

V1 支持文本型 PDF、DOCX、MD、TXT；扫描 PDF 返回“暂不支持图片型/扫描型 PDF”，不做 OCR。提取失败不得产生半条资料记录。

### 9.2 Word 导出

Python 根据统一 `ResumeDocument` 中间模型和 DOCX 模板生成文件。业务内容与版式分离，模板不得自行改写文字。导出采用临时文件写完、校验可打开后再原子移动到用户选择位置。

### 9.3 PDF 导出

Python 生成与预览一致的打印 HTML/CSS；Electron Main 在隔离的隐藏窗口加载本地内容，通过 `printToPDF` 输出。PDF 与 Word 共用同一个 `ResumeDocument`，避免两套内容逻辑。

打印窗口不加载网络资源；字体和图标随安装包提供。导出完成后记录文件名、模板、页数、时间和结果状态，不保存第二份无必要的正文副本。

---

## 10. 本地数据与目录边界

建议根目录：

```text
%APPDATA%/ShadowResumeAssistant/
├─ data/
│  └─ shadow_resume.db
├─ files/
│  ├─ profile/
│  ├─ imports/staging/
│  ├─ imports/originals/
│  ├─ audio/temp/
│  └─ exports/temp/
├─ backups/
├─ logs/
├─ recovery/
└─ runtime/
```

约束：

- 数据库只存结构化数据、文件相对路径、哈希和元数据；
- 附件不以 BLOB 存进 SQLite；
- API Key 不存 SQLite、配置 JSON、备份或日志；
- 所有业务文件名使用内部 UUID，原始文件名仅作为安全处理后的显示元数据；
- 临时音频完成转写或取消后立即删除；启动时清理过期临时文件；
- SQLite 开启外键、WAL 和合理的 busy timeout；写操作保持短事务；
- 每次 Schema 变更由 Alembic 迁移，恢复备份时先检查数据版本。

具体表、字段、索引、外键、JSON Schema 与备份清单在下一份《本地数据结构设计》中定稿。

---

## 11. 安全与隐私

### 11.1 Electron 安全基线

- `nodeIntegration: false`；
- `contextIsolation: true`；
- `sandbox: true`；
- 使用严格 CSP，禁止内联脚本和远程脚本；
- 生产界面使用受控的本地自定义协议，不直接使用任意 `file://` 导航；
- 阻止未允许的导航和新窗口；
- 外部链接仅允许 `https` 且经过域名/协议校验；
- 校验 IPC sender；
- 不向 Renderer 暴露危险 Electron API；
- 只加载随应用打包的界面代码。

### 11.2 网络边界

- 本地 FastAPI 只监听回环地址；
- OpenAI 请求只从 Python 发出，强制 HTTPS；
- Renderer 不允许访问任意公网 API；
- 请求超时、有限重试，禁止无限等待；
- 日志记录请求 ID、耗时、模型和 token 用量，不记录完整简历、JD、录音或 API Key；
- 设置页在真正发送前说明将发送的资料类型，受保护字段默认排除。

### 11.3 文件与路径

- 不接受 Renderer 任意传入路径执行读写；
- Electron 文件选择结果转换成一次性 `pathToken`，后端只处理已授权文件；
- 校验规范化后的绝对路径仍位于允许目录或本次用户选择范围内；
- 解压、恢复和导入时防止路径穿越；
- 单文件、单批次和备份总体积均设置上限。

---

## 12. 一致性、恢复与生命周期

### 12.1 自动保存

- 表单停止输入 800 毫秒后保存；
- 同一记录只保留一个在途 PATCH，后续修改合并；
- 使用 `updated_at` 或递增 `revision` 做乐观并发检查；
- UI 明确显示“保存中 / 已保存 / 保存失败”；
- 保存失败不清空本地表单，允许重试。

### 12.2 草稿与历史版本

- 草稿持续自动保存；
- 段落级 AI 修改只进入当前草稿，不创建历史版本；
- 只有点击“保存版本”或“保存并导出”才创建不可变版本快照；
- 版本快照引用当时的岗位、简历配置、模板版本和提示词版本。

### 12.3 备份与恢复

- 备份先执行 SQLite 一致性快照，再复制所需附件并生成 manifest 和校验和；
- 恢复前验证格式版本、必需文件和哈希；
- 恢复前自动备份当前数据；
- 在临时目录完成恢复和迁移验证后再原子切换；
- 失败时回滚到恢复前状态；
- 清除全部数据前展示范围、要求二次确认，并关闭数据库连接后执行。

### 12.4 应用退出

1. 阻止新增长任务；
2. 等待短事务和自动保存完成，最长等待有限；
3. 取消可取消的 AI 请求；
4. 调用后端 shutdown；
5. 超时后终止由本应用启动的 Python 进程树；
6. 下次启动把遗留的 `running` 任务标记为 `interrupted`。

---

## 13. 错误模型与日志

统一错误结构：

```json
{
  "error": {
    "code": "AI_RATE_LIMITED",
    "message": "AI 服务暂时繁忙，请稍后重试",
    "retryable": true,
    "request_id": "...",
    "details": {}
  }
}
```

错误分组：`VALIDATION_*`、`FILE_*`、`AI_*`、`DATA_*`、`EXPORT_*`、`BACKUP_*`、`RUNTIME_*`。界面依据 `code` 决定重试、返回修改、打开设置或联系诊断，不解析后端英文异常文本。

日志要求：

- Electron 和 Python 分文件、按大小滚动；
- 默认保留 7 天并设总容量上限；
- 正文、JD、联系方式、API Key、录音不得进入日志；
- 用户可在设置页打开日志目录或清除日志；
- 诊断导出前再次脱敏。

---

## 14. 打包和发布

### 14.1 后端

- PyInstaller 使用 `onedir`，便于排查缺失依赖且启动速度优于单文件自解压模式；
- 构建产物包含 Python 解释器、业务代码、文档依赖、数据库迁移和必要资源；
- 后端产物先独立执行接口、导入和 Word 导出冒烟测试。

### 14.2 桌面应用

- electron-builder 将 Python `onedir`、字体和模板通过 `extraResources` 放入应用 `resources`；
- Main 通过 `process.resourcesPath` 定位资源，开发环境使用单独路径适配器；
- Windows V1 只构建 x64 NSIS 安装包；
- 使用 assisted installer，默认按当前用户安装，不要求管理员权限；
- V1 不做自动更新、不做静默在线下载、不做应用商店发布；
- V1 暂不签名，安装时可能出现“未知发布者”提示，发布页需明确说明文件来源与 SHA-256；
- 卸载默认不删除用户数据，提供单独勾选项；应用内“清除全部数据”仍是主要清除入口。

### 14.3 可复现构建

- Node 与 Python 依赖均锁定；
- 构建脚本记录应用版本、Git commit 和构建时间；
- CI 或固定 Windows 构建机从干净目录生成安装包；
- 安装包、解包应用和后端可执行文件分别做冒烟测试。

---

## 15. 开发环境与建议目录

```text
shadow-resume-assistant/
├─ apps/
│  ├─ desktop/
│  │  ├─ src/main/
│  │  ├─ src/preload/
│  │  └─ src/renderer/
│  └─ backend/
│     ├─ app/api/
│     ├─ app/application/
│     ├─ app/domain/
│     ├─ app/infrastructure/
│     ├─ app/ai/
│     ├─ app/documents/
│     ├─ migrations/
│     └─ tests/
├─ packages/
│  ├─ contracts-generated/
│  ├─ resume-renderer/
│  └─ design-tokens/
├─ templates/
│  ├─ docx/
│  └─ print/
├─ prompts/
├─ evals/
├─ scripts/
└─ docs/
```

`contracts-generated` 从开发环境的 OpenAPI Schema 生成 TypeScript 类型。生成文件只读，不手工修改；CI 检查后端 Schema 变化后是否重新生成。

---

## 16. 架构测试重点

### 16.1 必须先做的技术 Spike

1. Electron 启动 PyInstaller 后端、随机端口握手、异常退出清理；
2. 安装后从 `resources` 正确定位 Python、字体和模板；
3. Windows Credential Manager 写入、读取、覆盖和删除；
4. DOCX/PDF/MD/TXT 提取，扫描 PDF 明确失败；
5. 同一份 `ResumeDocument` 输出 DOCX 和 PDF，两者内容一致；
6. 麦克风录音、临时文件、OpenAI 转写、取消后清理；
7. SQLite 备份、恢复失败回滚和旧版本迁移；
8. 长 AI 任务在关闭应用后被标记为 interrupted。

### 16.2 架构验收标准

- 安装包在一台未安装 Node.js/Python 的 Windows 10/11 x64 电脑上可运行；
- `netstat` 检查后端只监听 `127.0.0.1`，且端口非固定；
- 未带正确会话令牌访问本地 API 返回 401；
- Renderer 无法直接访问 Node.js、文件系统或启动进程；
- 断网时本地资料编辑、查看草稿和版本仍可用，AI 操作给出可恢复提示；
- API Key 不出现在 SQLite、普通配置、备份、前端存储和日志中；
- 强制结束应用后重新打开，已保存资料完整，未完成任务可识别；
- 导入失败、AI Schema 错误和导出失败均不会留下半成品业务记录；
- 恢复失败后仍能打开恢复前数据；
- 卸载应用后用户数据是否保留与安装器选项一致；
- 安装包中的生产界面不加载远程代码，CSP 和 Electron 安全开关通过自动检查。

---

## 17. 已确认决策与后续设计

本文件确认以下架构决策：

1. 本地桌面应用，不建设云端业务后端；
2. Electron + React 负责桌面体验，Python + FastAPI 负责业务和 AI；
3. Electron 管理 Python sidecar 生命周期；
4. 后端仅回环监听、随机端口、临时令牌；
5. SQLite 与附件分离，API Key 进入 Windows Credential Manager；
6. OpenAI 调用只发生在 Python；
7. 使用统一 `ResumeDocument` 驱动预览、Word 和 PDF；
8. V1 使用轮询管理长任务，不引入 WebSocket；
9. PyInstaller `onedir` + electron-builder NSIS x64；
10. V1 不签名、不自动更新、不要求管理员安装。

设计阶段的下一项是《本地数据结构设计》，它需要在本架构边界内确定：实体、字段、可选性、关系、索引、版本快照、附件 manifest、备份 manifest 和迁移策略。随后再确认《AI 工作流与提示词设计》和《Word / PDF 模板设计》。

---

## 18. 设计依据

本方案采用了 Electron 官方对进程模型、上下文隔离、沙箱和安全清单的建议；本地 API 使用 FastAPI/Pydantic 的请求响应校验与 OpenAPI 契约能力；应用启动清理使用 FastAPI lifespan；Python 使用 PyInstaller 打包为无需用户另装解释器的 Windows 产物；Electron 安装包通过 electron-builder `extraResources` 携带本地后端，并使用 Windows 默认 NSIS 目标。
