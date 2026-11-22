# RH / NS 并行启动验收

采样：2026-11-22T05:06:17.994475+00:00。当前 RH 为 `running/replay`，NS 为 `RUNNING/dependencies`。最终验证仍在进行，`proofAccepted=false`。

- 入口：https://lean.tano.asia/ ；RH：https://lean.tano.asia/rh/ ；NS：https://lean.tano.asia/ns/ 。页面仅提供 GET/SSE 观测。
- RH 全量编译 175187/175187、失败 0；五个最终定理类型与公理审计已通过。`leanchecker --fresh Main` 仍在运行，尚未登记最终成功。
- NS 原始归档与源码检查已通过；独立工具构建及上游自检 20/20 通过，命令真实退出码 0。正在准备锁定依赖；全量编译、公理审计、内核重放、独立检查和最终结果归档待完成。

## 运行隔离与调度

管理员显式授权 `parallel_replay`，仅当 RH 的编译、审计和来源版本检查通过且正在内核重放时放行。准入快照单独保存在 `parallelAdmission`，其 `finalSuccess=false`；RH 的最终报告与完整日志未成功归档前，`rhEvidence.persisted=false`。默认新任务仍为串行。

NS 实际限额为 60 vCPU、CPUs 4–63、220000000000 bytes，禁用交换，CPU shares 256、OOM score 1000。RH 保持原有 60 vCPU/250 GB 限额与进程。RH 必要检查和最终证据全部完成后，调度器仅提升 NS 内存上限至 250000000000 bytes，无须重启验证进程。RH 异常时只暂停 NS，并保留日志、检查点和通知。

RH 三个原容器的 ID、PID、启动时间、镜像、挂载、容器配置与运行配置，以及 RH 源码配置文件哈希，在升级前后完全相同。RH 重放进程保持 PID 1117379、startTicks 4110760；CPU ticks 从 840553 持续增加至 1064820。共享 Nginx 使用原配置进行平滑重载以刷新 NS API 地址。

## 验收证据

- 本地：198 项 Python 测试、13 项原 RH 浏览器测试、NS/入口/并行页面测试、真实 Nginx 路由测试、两个受限 Linux 容器测试、资源配置、图表、构建及语法检查全部通过。
- 真实受限容器覆盖无 CAP_FOWNER 的目录恢复，以及依赖解析 socket、离线 AF_UNIX 禁止、嵌套进程无法移除继承 seccomp 限制。
- 服务重启、重复启动接管、RH 异常、NS 已结束后的 RH 归档、资源提升门禁均有回归测试。
- [本地验收回执](ns-local-acceptance.json)、[线上浏览器检查](ns-parallel-online/browser.json)、[脱敏服务器快照](ns-parallel-online/server.json)。
- 线上自检完整日志：`/var/lib/lean-observatory-queue/worker/logs/0003-dependencies.log`；SHA-256 `ecbb0f31d7c73d2066246c504bdccf5ad024ee15f203e05d9e0217a221cfc9f0`。

部署源提交：`2676a5c`。接受并部署的源码指纹：`1c053d36c33c05529bf66e2a1d2bb259bd06a5aa64e90d0eff7f3cec63f444ae`。发布包 SHA-256：`a1155c9c693422b6a174f037e20f4804ab5da93db69ce774c4a6c63e5b904bbc`，76643 bytes。

NS 固定源码：`openai/NavierStokesAndEuler@f9e8bc5b38b6e212696e8a30e3e91517af887bbd`。Lean v4.34.0-rc2 与独立依赖保存在 NS 环境，RH v4.33.1 环境未改变。完整仓库构建包含 Euler；最终独立审计范围为固定清单中的两个 NS 声明。

## 计时与历史恢复

服务器 20 小时总计时从 2026-11-21T14:42:36Z 开始，截止北京时间 11 月 22 日 18:42:36。`notify_only` 到期只告警，由管理员决定何时停止；不会自动关闭服务器或中断 RH。并行任务的时段费用估算存在重叠，以服务器累计费用为总费用估算，项目时段估算不可相加。尚未接入实际云账单。

准备阶段曾因 Docker 插件线程限制、目录 chmod/chown 顺序、Cargo 解析 socket、nanoda 工具别名与替换容器后的 DNS 初始化暂停。相应修复均先写入本地、通过测试、提交推送后部署；历史失败退出码与日志均保留。只替换已退出的 NS 容器，未删除数据卷；实现变化涉及的旧源码检查点移入自己的备份目录后重新核验。全部原始 RH 数据与日志保留。

主机持久目录为 `/var/lib/lean-observatory-queue`，部署快照为 `parallel-deployment.json`，历史容器与检查点位于 `backups/`。后续成功步骤仅凭来源、实现、前置检查点和输出哈希一致才恢复。最终报告由后续实际检查退出码及结果持久化驱动。
