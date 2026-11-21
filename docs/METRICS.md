# 指标定义

| 字段 | 采集或计算逻辑 |
|---|---|
| mode / source | mock 任务与 mock_host 指标为合成数据；host_agent 来自宿主机文件；local_host 为本机采样 |
| compile.total | 原始 srcDir 的 Lean 文件实际盘点；盘点前为空，175187 仅为预期值 |
| succeeded | 已完成的源码模块去重；排除依赖与 C facets，结束时交叉检查 .olean 覆盖 |
| failed | Lake 明确指出失败的源码模块数；阶段退出失败单独显示，不凭空推断失败文件数 |
| rate | 近期 60 秒的已完成模块数 / 有效采样时长；暂停、完成或没有近期样本时为 0 |
| ETA | 尚未完成/失败的模块数除以近期速率；不可估计时为空，不在前端推算 |
| overallPercent | 六个必需阶段完成数等权；编译阶段额外采用该阶段的文件比例，不是时间消耗比例 |
| CPU | Linux /proc/stat 的差分，扣除 idle+iowait；首次样本为空 |
| 内存 | MemTotal - MemAvailable；不是所有进程 RSS 的简单相加 |
| 磁盘 | 指定文件系统的 statvfs/shutil.disk_usage；默认宿主机 /var/lib |
| 网络 | /proc/net/dev 所有非 lo 接口字节差分的总和，包含虚拟接口；不是仅公网出口，可能重复计算经虚拟接口转发的流量 |
| 负载 | 宿主机 1 / 5 / 15 分钟 loadavg |
| 历史 | 持久化采样，保留最近 7 天；接口当前返回最多 360 个最近样本 |
| 过期 | host_agent 超过 20 秒无新样本时显示 stale；不以容器指标填充宿主机数据 |

CPU/内存/网络在不提供 Linux /proc 的本机上明确为空；真实服务器监控使用独立 systemd 采集器。Mock 资源曲线由后端模拟，始终带 MOCK 标识。

UI 保留 500 行日志窗口；完整下载为 tar.gz，包含原始命令输出、完整事件流水及下载时刻的状态快照。JSON/Markdown 报告中的日志是最近 1000 条摘要，不能替代完整归档。
