# 影子简历助手 0.1.2

- 修复 Electron 初始化完成前读取 `localAppData` 导致的主进程 JavaScript 异常；
- 正常运行时使用 Electron 默认的本地、按用户隔离的数据目录；
- 仅在自动化测试明确传入目录时覆盖 `userData`；
- 安装测试新增普通用户数据路径启动与 React 渲染验证。
