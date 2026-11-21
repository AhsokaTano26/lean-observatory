# 部署与验收

部署和启动由助手负责，用户不需要执行这些操作。完整且当前有效的步骤见 [助手部署与运行规范](ASSISTANT_DEPLOYMENT.md)。

严格顺序为：本地开发 → 全部本地测试 → 服务器只读检查 → 初装和可信 HTTPS → 线上验收 → 创建真实验证任务。

## 交付组件

| 文件 | 用途 |
|---|---|
| `scripts/accept_local.py` | 后端、图表、构建、浏览器、Compose、ARM/AMD64 小样例及真实 Lake 管线验收 |
| `scripts/gates.py` | 将本地验收绑定到准确源码字节；源码变化即关闭远程门禁 |
| `scripts/preflight.py` | 购机后由助手只读检查 OS、架构、权限、资源、Docker 与端口 |
| `scripts/package_release.py` | 生成含验收记录的发布包与 SHA-256，规范 root 所有权及安全权限 |
| `scripts/bootstrap_server.sh` | 默认无写入演练；明确执行时仅初装本项目，不替换现有服务 |
| `compose.acme.yaml` / `compose.tls.yaml` | 初次 ACME webroot 与正式 HTTPS |
| `deploy/lean-observatory-worker.apparmor` | 只允许隔离所需私有 proc 挂载的 Worker 配置 |
| `scripts/online_acceptance.py` | 检查可信 HTTPS、准确源码/镜像、实际限额、宿主指标、只读接口、SSE、真实 AppArmor 小样例 |
| `backend/control.py` / `backend/readiness.py` | 只在主机 CLI 管理任务；无有效线上验收不能创建/领取真实任务 |
| `scripts/backup.py` | Worker 停止后的 SQLite backup API 与完整文件证据一致性快照 |

## 服务器阶段

目标为 Ubuntu 24.04 x86_64、64 vCPU、256 GB RAM、2.6 TB SSD，计划域名 `lean.tano.asia`。助手实际检查至少 240 GiB 内存和 500 GiB 空余磁盘；80/443 冲突、既有部署或不适配的 Docker 会先停止初装检查，不停止用户其他服务。

正式 Worker 使用 48 CPU、CPU 8–55、208 GiB 内存上限，与 2 CPU/2 GiB 的 API、1 CPU/256 MiB 的 Nginx 分离。宿主机 systemd 指标直接读取 `/proc`，不把容器指标当宿主机。数据与构建输出分卷持久化，不挂载 Docker socket 或宿主 PID namespace。

AppArmor 必须在真实 Ubuntu 上启用并加载专用 enforce profile。Docker Desktop 的本地 namespace 小样例和 AppArmor 语法编译不等于生产内核策略验收。正式线上门禁会在准确 Worker、准确 profile 内重新执行小型 Lean 编译、fresh replay 与隔离检查，失败不生成任务授权。

## 真实复现

原始归档只在部署和线上验收通过后下载。14 分卷分别检查大小，合并检查 gzip、239,275,554 bytes 和指定 SHA-256，再安全解包。坏归档会留下拒绝证据并失效不可信分卷，显式恢复后重新下载。

原始 Lean/Mathlib 配置保持不变。已审阅扩展必须同时匹配文件 SHA-256 与具体 token/行号；未审阅扩展、任意公理或其他禁止能力仍停止执行。所有源文件最终仍必须通过正常类型检查、五定理传递公理白名单和 `leanchecker --fresh Main`，不能用扩展审查清单替代。

完整编译逐个统计源模块与实际产物，记录真实命令、退出码和完整原始日志。失败、中断与资源不足停止后续阶段；重启后的旧命令保留未知退出码，不能伪造成功。24 小时后的恢复需要助手对同一任务重新线上验收，恢复回执不能用于新任务。

备份、恢复、回滚和证书续期均按 [助手规范](ASSISTANT_DEPLOYMENT.md) 处理。原始证明、目标主机、可信证书和不同实现的独立内核状态，在实际完成前始终保留未验证标记。
