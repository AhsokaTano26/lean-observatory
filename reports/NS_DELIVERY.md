# NS 后续队列部署与验收记录

> 初次部署历史记录。当前20小时提醒、自动衔接及60vCPU/250GB设置见 [最新验收记录](SERVER_HOURS_RESOURCES.md)。

本报告验证的是队列平台及部署行为。**NS 源码编译、定理审计、内核重放和独立检查尚未执行，未宣布任何证明通过。**

- 源码提交：`6a8ca6d`（其后的文档提交不改变部署代码）。
- 部署源码 SHA-256：`36948319c5c0169c1f8ee363ae72b29db487b628823c83d3956be2b7d58931fe`。
- 发布包 SHA-256：`9405925ea36a075b64a144db92fca0c128b52a4da6f304ca9895ef20092939bb`。
- NS 页面：<https://lean.tano.asia:9443/ns/>，别名 <https://lean.lanunion.org.cn:9443/ns/>。
- 原 RH 页面保持在 443 端口，没有重启、重新部署或修改原 Dashboard。

## 本地验收

| 检查 | 结果 |
|---|---|
| 完整 Python 单元与接口测试 | 152 项通过 |
| 图表测试 | 10 项通过 |
| 原 RH 浏览器回归 | 13 项通过 |
| NS 浏览器场景 | 通过；1440、390、320 px，主题、筛选、只读请求、服务中断后重连 |
| TypeScript/Vite 构建 | 退出码 0 |
| 两个新增 Compose 配置校验 | 退出码 0 |
| Python 语法检查 | 退出码 0 |
| Linux 只读容器试运行 | UID10001、只读根目录及数据挂载读取成功；POST 返回405 |
| 独立代码审查 | 两项重要问题已修复，49 项相关测试通过 |

完整命令、源码绑定哈希与原始输出见 `ns-local-acceptance.json` 和 `ns-local/`。源码变动后重新运行了全部验收，才部署修复。

## RH 保护核对

运行 ID 始终为 `20565ace60c2`，状态 `running / compile`。部署前后进度从 **32,681** 增长至 **35,589 / 175,187**，失败数保持 **0**。

三项原容器的 ID、PID、StartedAt、镜像、完整配置哈希、HostConfig 哈希及挂载完全一致。原 `.env`、Compose、运行中 Nginx 配置及 RH AppArmor 配置哈希均一致。新加的是独立 NS 系统组、AppArmor profile、目录、Compose 项目和 systemd 服务。

核对原始数据见 `ns-preservation-before.json`、`ns-preservation-after.json`，布尔判定见 `ns-online-acceptance.json`。

## 线上状态

NS 为 **QUEUED / waiting_rh**，额外预算上限 **USD 0**，`startedAt = null`，七个验证阶段均为 `PENDING`。仅有新的 API 和 Nginx 容器，没有创建 NS 验证容器，也没有执行 NS 重型镜像构建。调度器在线，页面读取真实主机指标。

RH 必要检查成功后，调度器会先校验并持久化最终结果及完整日志，重新确认没有其他 RH 任务运行，再检查预算和资源。当前预算为0，所以届时会 **PAUSED / budget** 并告警；不会自动开始 NS。RH 失败或异常停止也会暂停 NS 并保留证据。预算提高必须由管理员在宿主机明确操作。

队列和通知回执在本次新增服务的多次重启中保持同一任务 ID、创建时间和记录，没有重复创建任务或重发已确认通知。公共接口拒绝控制操作，POST 返回405。

告警接口最初拒绝 urllib 默认标识（403）；带上 `LeanObservatory/1.0` 请求头后返回 **HTTP200 / forwarded**，原排队通知已确认发送并持久化为 `sent`。正式通知模块已采用该标识并通过回归测试。HTTP202仍单独显示为等待投递。

两个域名的服务端 HTTPS、证书校验、页面、API及只读检查通过。生产页面经 SSH 隧道的桌面/手机浏览器测试通过，未出现脚本错误或写请求。**当前本机直接访问公网9443出现TLS连接关闭，因此公网直连可达性未标记通过。**原443页面仍正常；没有为此更改原RH代理或DNS。

## 固定源码和未执行范围

NS 固定版本为 `openai/NavierStokesAndEuler@f9e8bc5b38b6e212696e8a30e3e91517af887bbd`，其独立 Lean、Mathlib、Comparator 和工具快照见 `ns_queue/manifest.json`。完整仓库构建包含2659个Lean文件和Euler库；最终定理审计与独立检查只针对NS的两个指定声明。

正式 NS 下载、依赖准备、全量编译、公理审计、fresh 内核重放和 Comparator/nanoda 独立验证均为 **NOT_RUN**。外部工具兼容性和 Linux 沙箱实际强制执行仍待将来获预算后验证；失败会阻塞阶段。`proofAccepted = false`。操作说明见 `docs/NS_QUEUE.md`。
