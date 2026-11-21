# 本地验收报告 · Lean Observatory

本报告只验收平台、本地 Mock 流程及小型 Lean 工具链样例。原始黎曼猜想项目尚未下载、编译或验证。服务器尚未购买，未连接 Linode，未部署生产页面。

## 环境与验证方式

- 原生环境：macOS / ARM64、Node 26、Python 3.15；生产镜像使用 Node 24 构建、Python 3.13 API、Ubuntu 24.04 内的固定 Lean 工具链。
- 实际 Lean：4.33.1 / aarch64-unknown-linux-gnu / commit 819816b2e0a3bf405af45ae5c7af2491d8f5bee6。
- Browser plugin not available；使用本机实际 Playwright Chromium。页面为本地 API 真实渲染的 React 页面，不是静态设计截图。
- 原生浏览器测试入口 http://127.0.0.1:8788；持久的 Compose 本地预览 http://127.0.0.1:8789。
- 桌面 1600×1100、1280×900、平板 768×900、移动端 390×844、320×844；深色与浅色主题。

## 检查矩阵

| 检查 | 结果 | 证据 |
|---|---|---|
| 后端/API/安全/恢复/门禁 | 36 项通过 | unittest，实际 HTTP/SSE、SQLite、命令进程与退出码 |
| 图表计算 | 10 项通过 | 时间轴、缺测、稀疏长中断、30 分钟历史、过期屏蔽、浮层定位 |
| TypeScript / Vite 构建 | 通过 | tsc --noEmit / vite build，退出码 0 |
| 浏览器功能 | 13 项通过 | 六个页面、暂停恢复、失败中断资源场景、下载、主题、移动导航、SSE 离线恢复 |
| 页面身份与有效内容 | 通过 | 标题/主标题/连接状态和可交互主体检查 |
| 框架错误覆盖层 | 未发现 | 生产构建页面与截图 |
| 浏览器控制台 | 无应用错误/警告 | pageerror + console error/warning 收集 |
| 响应式溢出 | 通过 | 320/390/768/1280px document.scrollWidth 检查 |
| Compose | 通过 | API、Nginx、独立 Mock Worker 实际启动并健康 |
| Nginx/SSE/令牌/下载 | 通过 | 经 Nginx 实际 HTTP 请求；未授权写入返回 401 |
| TLS 模板 | 配置测试通过 | 自签名本地测试证书下 nginx -t；不计为可信生产 HTTPS |
| Worker 工具链 | 小样例通过 | 实际 Lean 4.33.1 编译 tiny Main，leanchecker --fresh Main 返回 0 |
| Worker 边界 | 通过 | UID 10002、CapEff=0、无管理令牌、数据库/应用目录不可见、源码与工具链不可写、无外网路由 |
| 子进程清理 | 通过 | 暂停进程组后强杀控制者；另测 setsid 脱离进程组子进程在私有 PID 命名空间退出后停止 |
| 完整原始日志 | 通过 | 24,001-byte 长行保留在日志 tar.gz，附事件流水与状态快照 |
| 原始 175,187 文件复现 | 未开始 | 不以平台或 tiny fixture 测试替代 |

构建器会对 lucide-react 的 `use client` 指令输出两条 module-level directive 提示；这是普通 Vite 客户端应用，无服务端组件边界，构建退出 0，实际浏览器无应用错误。这两条构建提示已记录，没有据此声称“构建输出零警告”。

## 可复查的交互

入口 → SSE 连接 → Mock 编译推进 → 暂停 → 浅色主题 → 五个定理详情 → 服务器/时间线/结果/编译导航 → 日志筛选 → 报告下载 → 恢复 → 检查完成（仍为 MOCK）。失败、中断和资源不足分别持久化，刷新后恢复，进度不倒退；资源不足恢复会把 Lake 并发减半。浏览器断网后显示重连，联网后恢复实时状态。

原生队列还检查了 30 条历史记录之外的旧任务恢复、HTTP 200 伪归档、哈希/路径/链接安全、公理输出伪装/冲突、缺失输出、命令失败、门禁失效及完整日志导出。

## 设计对照

用户后续指定参考 https://bandori.fans/en，已改为暖白纸面 / 暖黑主题、横向编号导航、方角细线面板、大数字与清楚的排版层级。最新实测和截图见 [UI_QA.md](UI_QA.md)，设计说明见 [THEME.md](../docs/THEME.md)。

图表全部改用按真实时间和容器像素计算的 D3 曲线；CPU/内存固定百分比尺度，磁盘为 GiB，网络下载/上传双序列区分线型。指针、触摸、方向键读数和重连均经真实浏览器验证，过期数据不补造为新样本。

## 交付边界

- 当前原始项目的五定理审计与 Main 内核重放均未执行，尚不能提供它们的真实退出码或验证结论。
- tiny fixture 使用 Lean 自身内核，不是不同实现的独立内核。数学陈述语义复核仍待完成。
- 本地镜像为 ARM64；Linode AMD64 环境、真实宿主机指标、可信 HTTPS、目标端口与线上功能必须在购机后验收，成功后才开启真实任务。
- 镜像包含可信控制进程的 SYS_ADMIN，用于隔离命名空间；被验证子进程在 chroot 内降权并清空 capabilities，不挂载 Docker socket或宿主机 PID 命名空间。
- 当前工作区 .git 只读，提交/推送通过独立临时 Git 工作目录完成，见 [GIT.md](../docs/GIT.md)。

本地源码指纹和检查退出码见 [local-acceptance.json](local-acceptance.json)。部署步骤见 [DEPLOYMENT.md](../docs/DEPLOYMENT.md)。

## 截图

![Dark desktop](../docs/screenshots/desktop-dark.png)
![Light desktop](../docs/screenshots/desktop-light.png)
![Mobile results](../docs/screenshots/responsive-390.png)
