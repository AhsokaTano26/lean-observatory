# NS 独立检查隔离兼容性恢复记录

采样：2026-11-22T08:13:49Z。NS 为 `RUNNING/independent`，实际 Comparator 命令已启动；独立检查与最终持久化尚未完成，`proofAccepted=false`。RH 原 `leanchecker --fresh Main` 仍在执行。

## 原因与修复

原 `0054-independent.log` 的文件写入拦截已成功、退出码为0，平台却因其中包含 Landrun 的原生 ABI 4 功能告警而暂停。此次修复仅接受锁定 Landrun 版本的完整、精确 ABI 4 告警，并要求真实测量的补偿隔离条件全部通过。其他告警、失败的隔离条件、非零退出码或缺失的内核接受标记仍然阻止通过，原始告警始终保留。

服务器 Ubuntu 内核提供 Landlock ABI 4。实际固定 Landrun 探针退出码0，测得文件写入被拒、UID/GID10002、能力为0、no-new-privileges、seccomp、私有 PID 根与网络、无路由、IPv4/IPv6 TCP/UDP 阻断、AF_UNIX socket/socketpair 阻断、用户命名空间创建被拒、无sys、仅null/urandom设备与安全继承描述符。配置名称为 `landlock+namespaces+seccomp`。

该配置不宣称提供原生 ABI 5+ 的全部能力：ioctl 系统调用没有被整体禁用，可接触设备仅null/urandom，继承描述符仅pipe/null；信号边界来自私有 PID 命名空间，并非Landlock域间信号隔离。对应 ABI 功能见[Linux Landlock 文档](https://docs.kernel.org/userspace-api/landlock.html)。[实际探针与原始告警](ns-independent-sandbox.json)保留完整条件和限制。

## 无损恢复与线上检查

- 原源码、依赖、2659/2659完整编译、两项NS定理审计、fresh Lean内核重放均为真实退出码0。五个成功步骤的全部输出、原始日志和55条历史命令均保留；恢复后五阶段均为 `restored=true`。
- `independent-policy-v1`迁移核验两次历史迁移的完整父链、所有原始/提议回执、输出字节数/SHA-256、精确代码变化与批准策略哈希。保留不可变写前事务，成功后才恢复自己的NS调度器。
- 新旧NS镜像的可信运行环境层完全相同；原已退出NS容器保留为`-before-independent`，此前两代及持久数据卷也保留。
- RH容器ID、PID15538、启动时间、镜像、配置及挂载哈希与部署前一致；实际leanchecker PID1117379、启动ticks4110760相同，CPU时间继续增长。没有重启或暂停RH。
- NS实际60vCPU；与RH并行期间为220GB内存保护上限，RH成功归档后按既有策略提升至250GB。原20小时租赁预算起点、截止时间及仅告警策略未改。
- `https://lean.tano.asia/`、`/rh/`、`/ns/`均返回200；公开只读API返回新源指纹、在线调度器和真实运行状态；HTTPS SSE收到snapshot事件。迁移清单和内核报告可通过公开证据接口下载，清单SHA-256与迁移账本一致。
- Comparator命令`lake env /work/ns/tools/comparator/.lake/build/bin/comparator ComparatorChallenges/NavierStokes.json`已运行。它在独立的全新目录构建检查输入；此前编译阶段的成功回执不因此重复执行。

## 测试与版本

本地213项Python测试、真实Linux Landlock/namespace/seccomp正负测试、真实Lean内核与审计测试、页面/响应式/断线恢复/只读接口、资源与Nginx路由、构建及语法检查均通过。移除Landlock或AF_UNIX过滤的真实负例均被拒绝。完整本地验收先通过，才更新服务器NS。

源码提交`741d5ac`；部署源指纹`fb3ba6f729a1907d154a15bde7afb39f329ca21a65d37b6691fdbe8939a86973`；发布包85876 bytes，SHA-256 `16083af5d046666755e8a5257ceb98d10208b10ee714dd41ca609df5ea6a0b30`。

[完整部署与保留证据](ns-independent-deployment.json)、[恢复后真实进程/检查点/命令快照](ns-independent-recovery.json)、[本地验收](ns-local-acceptance.json)。这些记录中的成功仅限已完成的步骤，不代表NS或RH最终证明已获确认。
