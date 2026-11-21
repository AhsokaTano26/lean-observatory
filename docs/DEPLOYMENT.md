# 部署与验收（服务器尚未购买）

域名计划为 `lean.tano.asia`。以下命令均为部署配置和运行手册；尚未对 Linode 执行。禁止在本地门禁通过之前连接服务器。

## 1. 本地验收

```sh
npm ci
npx playwright install chromium  # 若本机没有匹配浏览器
npm test
# 先构建并运行本地 Compose，真实 Lean 仅运行 tiny fixture，不下载作者项目
cp .env.example .env
# Web 为只读服务，无管理员令牌；ENABLE_REAL 保持 0
# macOS 的完整 Worker 冒烟必须使用 compose.smoke.yaml 资源覆盖

docker compose --profile mock up -d --build --wait
```

`python3 scripts/accept_local.py` 在已有本地镜像上执行后端、构建、浏览器、Compose 配置和正式 Worker 的小样例内核重放/权限测试，生成绑定源码指纹的 `reports/local-acceptance.json`。其中任何步骤非零，远程检查脚本均拒绝连接。API 与浏览器测试结果不是完整源码证明的验证结论。

## 2. 购买服务器之后：先只读检查

```sh
python3 scripts/preflight.py --target root@SERVER_IP
```

此工具会先检查本地验收及源码指纹，再通过 SSH 读取 Ubuntu 版本、CPU/内存/磁盘、端口、Docker 和已有服务。报告为 `reports/server-preflight.json`。需要 Ubuntu 24.04、至少 64 vCPU / 240 GiB 实测内存 / 200 GiB 空余磁盘。若 80/443 被占用，先确定与现有反向代理整合的方式；不停止已有服务，不覆盖已有 Nginx 配置。

## 3. 上传与配置（在确认目标后执行）

```sh
python3 scripts/package_release.py
# 输出已验收 bundle 路径与 SHA-256；用 scp 上传，服务器重新核对 SHA-256 后解包。
# 建议目录 /opt/lean-observatory，源码由 root 持有，不让验证子进程写部署目录。
```

在服务器中安装 Docker Engine / Compose 插件（复用已有 Docker，不自动重装或清理），进入平台目录，复制 `.env.example` 为权限 `0600` 的 `.env`，保持 `ENABLE_REAL=0`。设置 `METRICS_DIR=/var/lib/lean-observatory-metrics`。核对实际 CPU 编号后设置 `WORKER_CPUSET=8-55`、`WORKER_CPUS=48`、`WORKER_MEMORY=208g`。API 限额 2 CPU / 2 GiB，Nginx 1 CPU / 256 MiB，给系统和其他服务保留空间。

启动真实 Worker 但不创建真实任务：

```sh
docker compose --profile verification up -d --build --wait
docker compose exec nginx nginx -t
```

不要同时启动 `mock` 和 `verification` 两个 Worker。SQLite WAL、日志与报告位于 `verification-data` 持久卷；隔离编译目录位于 `build-data`。不挂载 Docker socket。正式 Worker 的可信控制进程使用chroot/setuid/chown/kill 与用于每条命令的 PID/挂载/网络命名空间的 SYS_ADMIN 权限；Lean 子进程降为 UID 10002，在每条命令的私有 PID/挂载命名空间及 chroot 中只能写 `.lake` 和独立 HOME/临时目录，不能访问 `/data`、管理令牌或验证程序，也不具有控制进程的任何 capabilities，原始源码与工具链不可写。编译、审计和内核重放阶段使用独立网络命名空间，禁止联网；仅锁定依赖准备可联网。命令退出后 PID 命名空间自动清理，包括 setsid 脱离进程组的子进程。源码在任何 Lake 调用之前进行绕过点扫描；发现疑点会停止等待审查。

## 4. 宿主机指标

将 `deploy/lean-observatory-metrics.service` 复制至 systemd。确认 WorkingDirectory 为实际平台目录；创建无登录权限的 `lean-metrics` 系统用户及由其持有的 `/var/lib/lean-observatory-metrics`，权限 `0755`（指标文件允许 API 只读），启用服务。

采集器直接读取 Ubuntu 宿主机 `/proc`，记录 CPU 差分、MemAvailable、非回环网络字节差分、负载和磁盘使用。容器中的 `/proc` 不冒充宿主机。指标超过 20 秒没有更新时标为过期，不能通过线上验收。

## 5. HTTPS 与域名

将 A/AAAA 记录指向实际服务器；若仅有 IPv4，不保留失效 AAAA。优先复用现有受信任的 TLS 入口。新主机可使用 Certbot 的 webroot/standalone 或 DNS challenge 签发证书，证书路径为 `/etc/letsencrypt/live/lean.tano.asia/`；创建 `/opt/lean-observatory/acme` 作为续期 webroot。证书存在且端口无冲突后：

```sh
docker compose -f compose.yaml -f compose.tls.yaml --profile verification up -d --wait
docker compose -f compose.yaml -f compose.tls.yaml exec nginx nginx -t
```

`compose.tls.yaml` 使用 Compose 2.24.4+ 的 `!override` 清除 loopback HTTP 端口，启用公网 80→443 跳转、TLS 1.2/1.3。SSE 禁用代理缓冲并保留一小时读取超时。证书续期完成后执行 `nginx -s reload`。自签名测试证书只用于本地配置测试，不计为生产 HTTPS 验收。

## 6. 线上验收后才启用真实任务

先以 `ENABLE_REAL=0` 验证页面、SSE、实际 host_agent 指标、下载、HTTP 写入均返回 405 和资源限制。用隔离的 Mock 数据卷演练故障，不在正式验证卷留模拟结论。

```sh
python3 scripts/online_acceptance.py --url https://lean.tano.asia
```

线上报告通过且实际页面功能已检查后，才将 `.env` 的 `ENABLE_REAL` 改为 `1`，重建 Worker 容器（保留卷）。然后仅在服务器命令行创建一次真实任务：

```sh
docker compose exec worker python3 -m backend.control --data /data create --mode real --jobs 48
# 查询任务编号与状态
docker compose exec worker python3 -m backend.control --data /data list
# 需要时从命令行暂停、恢复或取消
docker compose exec worker python3 -m backend.control --data /data pause RUN_ID
docker compose exec worker python3 -m backend.control --data /data resume RUN_ID
docker compose exec worker python3 -m backend.control --data /data cancel RUN_ID
```

Web 服务仅提供 GET/SSE 与下载，创建、暂停、恢复、取消均不暴露为 HTTP 操作。默认 48 个 Lake 调度线程，各 Lean 子进程 `-j1`，根据实测资源调整。资源不足后的恢复会把该任务的 Lake 并发减半（最低为 1），保留已有模块进度，并在新命令记录中保留生效线程数。暂停并不释放已有内存；取消会终止任务，取消状态不可恢复；需要保留检查点释放内存时，应停止 Worker，重启后从中断状态显式恢复。

## 7. 正式复现

Worker 从作者站点下载 14 分卷，逐卷检查字节数，合并后检查 gzip、239,275,554 bytes 和 SHA-256；原始哈希来源为用户/社区记录，尚无作者签名。安全解包后核对源码数量、原始配置和源码逐文件哈希；不修改原始提交文件。

在受限环境准备锁定的 Mathlib 缓存，禁止 root 项目产物缓存，首次编译拒绝已有项目 `.olean`。运行时单独记录只追加 `-j1` 的配置副本。完整编译后检查产物数量和源码不变性，五个 theorem 的精确期望类型及传递公理白名单，最后 `lake env leanchecker --fresh Main`。每个命令保留实际参数、退出码、完整原始输出与文件哈希。

任一必需检查失败、中断、资源不足或输出缺失时停止后续阶段；恢复先重新核对已下载归档、源码清单及原始配置。检查全部完成的状态名称为 `checks_completed`，永不自动宣称数学证明通过。数学陈述语义复核与不同实现的独立内核检查保持单独状态。

## 8. 备份与回滚

备份前暂停/停止 Worker。用 SQLite backup API 复制数据库，同时保存 runs 目录、原始分卷和 build-data 卷；不要直接复制正在写入的 SQLite 主文件而遗漏 WAL。记录镜像 digest、源码指纹及 `.env` 的安全备份位置。回滚镜像时保留两个数据卷，禁止 `docker compose down -v`。完整日志可能很大，应提前监控磁盘并将完成的证据归档至专用存储。
