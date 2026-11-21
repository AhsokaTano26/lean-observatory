# 助手部署与运行记录规范

本项目由助手负责部署、启动、监控、恢复和备份。用户仅提供可用 SSH 入口和 `lean.tano.asia` 的 DNS 配置；下述命令是助手的操作记录模板，不要求用户自行执行。服务器已购置并部署；当前进展见 [STATUS.md](../reports/STATUS.md)。本地测试与真实证明结论仍严格区分。

目标为 Linode G8 Dedicated：64 vCPU、256 GB 内存、2.6 TB 磁盘，Ubuntu 24.04 x86_64。购机前先完成源码绑定的本地门禁，任何后续源码修改都会使旧门禁失效。本地只运行小型夹具；不提前下载或编译完整原始证明。

## 初装顺序

1. 助手完成 `scripts/accept_local.py`，确认 `reports/local-acceptance.json` 对应当前 `scripts.gates.fingerprint`，再生成并校验发布包。购机之后，助手通过 `scripts/preflight.py` 只读检查目标主机。必须为 Ubuntu 24.04 x86_64、有 root 权限、至少 64 CPU / 240 GiB 实测内存 / 500 GiB 空闲磁盘，且 80、443 无监听冲突。生产主机的 AppArmor 内核功能必须已启用；不支持时停止部署，不以 unconfined 降级。
2. 助手核对服务器身份和发布包 SHA-256，将发布包解至固定 `/opt/lean-observatory`。部署源码归 root 所有，其他用户无写权限。遇到现有安装、项目卷、端口冲突或不符合要求的 Docker，先检查原因；不停止已有服务、不卸载已有 Docker、不清理卷。
3. 助手先运行 `bash scripts/bootstrap_server.sh --dry-run` 阅读计划。该默认模式只校验本地门禁并输出计划，不联网、不写主机。确认目标实测符合后，助手在服务器运行 `bash scripts/bootstrap_server.sh --execute`，可选 `--email ADDRESS` 提供 ACME 联系地址。不得在开发电脑执行 `--execute`。
4. 初装脚本仅在 Docker 缺失时按 [Docker 官方 Ubuntu apt 流程](https://docs.docker.com/engine/install/ubuntu/) 安装 Engine、Buildx 与 Compose；已有可用 Docker 则复用，要求 Compose ≥2.24.4。它创建无登录权限的 `lean-metrics` 用户、宿主指标目录与 systemd 采集服务，将 `.env` 设为 root 所有、`0600`，并写入当前源码 SHA-256、`ENABLE_REAL=0`、`METRICS_DIR=/var/lib/lean-observatory-metrics`、`WORKER_CPUSET=4-63`、`WORKER_CPUS=60`、`WORKER_MEMORY=250000000000`、`APPARMOR_PROFILE=lean-observatory-worker`。脚本安装 `apparmor`（包含 `apparmor_parser`），把经过源码门禁的 `deploy/lean-observatory-worker.apparmor` 安装至 `/etc/apparmor.d/lean-observatory-worker` 并加载，必须确认内核中该 profile 为 enforce；不会使用会阻止 mount 的 `docker-default` 运行正式 Worker。
5. 初装只启动 `lean-observatory` 项目的 API、正式 Worker 和 Nginx；空队列不创建真实任务，也不运行 mock profile。先使用 `compose.acme.yaml` 的 80 端口 webroot 签发 `lean.tano.asia` 证书，再以 `compose.tls.yaml` 切换到正式 HTTPS。用户应将正确 A/AAAA 指向目标主机；没有 IPv6 时移除旧 AAAA。脚本启用 `certbot.timer`，安装仅在本域名证书更新后校验并 reload 本项目 Nginx 的 deploy hook，并执行 ACME staging 的 `certbot renew --dry-run`。完成后助手调用 `online_acceptance.py --worker-fixture-only`，在真实 `ENABLE_REAL=0` Worker 中通过标准输入执行当前 `scripts/container_smoke.py`，验证私有 proc、受限 UID、无外网路由、源码/工具链不可写、小型 Lean 编译与 fresh 内核重放，以及脱离进程/父进程死亡清理。失败保留日志并停止；不下载或编译完整证明。续期机制参见 [Certbot 官方文档](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates)。

初装中途失败时保留输出、日志、证书和卷，不用 `down -v` 或重复覆盖配置“修复”。脚本是首次安装工具，已有 `.env` 或部署状态会拒绝重跑；助手先诊断失败点，再按已完成步骤有针对性地恢复。

## 线上验收与真实任务门禁

助手在部署目录执行 `python3 scripts/online_acceptance.py`。该工具只使用默认 CA 信任链访问 `https://lean.tano.asia`，不允许 HTTP、其他主机、凭据、路径前缀或关闭证书校验。它检查：

- HTTPS 健康页、首页和 JSON 报告实际可读；API、报告与 SSE 首个 snapshot 的源码 SHA-256 一致。
- 当前源码仍通过本地门禁；运行中 API / Worker 实际镜像的 `io.lean-observatory.source-sha256` 标签、容器环境和网页源码标识均一致。只改 `.env` 而没有重建镜像会被拒绝。
- 实际 Docker 容器的 CPU、内存、Worker CPU 绑定、swap 和 PID 限额符合配置，Worker 的 `ENABLE_REAL=0`，且 `/approval` 只读挂载。Worker 的实际 `AppArmorProfile` 必须精确为 `lean-observatory-worker`；空值、`docker-default`、`unconfined` 均拒绝。宿主 AppArmor 必须 enabled、profile 为 enforce，安装的 profile 文件 SHA-256 必须与已验收源码一致。
- 宿主指标来自 `host_agent`，20 秒内更新，至少 64 CPU / 240 GiB 内存 / 500 GiB 空闲磁盘。容器或模拟指标不能替代宿主指标。
- 正式卷为空队列：`run.id=null`、`mode=real`、`status=waiting`，没有任何任务历史、命令或产物；空队列没有 Worker 心跳属正常。
- 页面声明只读；对 `/api/runs` 和 `/api/control` 的 POST、PUT、PATCH、DELETE 均返回 `405` 和 `Allow: GET`。探测体统一使用无效 mode/run/action/jobs，即使误接旧服务也不会创建任务。

每次线上验收都会先在上述正式 Worker 中重新执行 tiny fixture，保存 `.data/approval/worker-fixture.json` 和完整 `.log`。回执必须在 15 分钟内，绑定当前源码、fixture 脚本与 profile 的 SHA-256，以及实际容器 ID、镜像 ID 和 `AppArmorProfile`。`scope=tiny-only`、`proofReproduction=NOT_RUN`、`productionEligible=false` 表示该 fixture 本身不能授权完整任务；只有随后独立通过的线上总验收可以授权。Desktop 无 AppArmor 的本地 fixture 必须标为 `not_production`，无法满足这些生产检查。

全部通过后才原子生成 root 所有、可读的 `.data/approval/online.json`，包含八项检查、时间、目标 URL 和源码指纹。测试夹具只检查纯校验函数，不生成可开启生产任务的线上回执。在线回执有效 24 小时；源码变化、过期或任一检查缺失都要求重验。

此时仍未启动证明。助手完成实际浏览器只读页面检查并记录验收后，才在服务器将 `ENABLE_REAL` 设为 `1`、仅重建 Worker，再通过 `backend.control create --mode real --jobs 60` 创建一次任务。创建前再次检查任务列表为空，创建后记录任务 ID，后续恢复使用同一任务，避免重复创建。控制命令与 Worker 领取任务都会验证线上回执。

运行中助手负责检查宿主指标、磁盘余量、完整命令日志和阶段状态；资源不足、失败或中断时保留证据，按任务检查点恢复。48 个 Lake 调度线程、每个 Lean 子进程 `-j1`；`resource_exhausted` 恢复时调度线程减半。任何通过都只指记录中的检查，不自动宣称数学陈述已经人工复核。

## 一致备份

备份必须先由助手停止本项目 Worker，并确认所有证明子进程已结束。仅暂停任务仍会占用内存且 Worker 持有锁，不能用于备份。保留 API 在线可读；备份时 SQLite 写锁会短暂阻塞 API/CLI 写入。

助手用 `docker volume inspect lean-observatory_verification-data` 获取实际数据卷挂载目录，选择有足够余量的新备份目录，先调用：

```sh
python3 scripts/backup.py --data DATA_VOLUME_MOUNTPOINT --output NEW_BACKUP_DIRECTORY --dry-run
python3 scripts/backup.py --data DATA_VOLUME_MOUNTPOINT --output NEW_BACKUP_DIRECTORY --execute
```

这里的参数由助手填入实测路径。默认 dry-run 只盘点证据，不创建目录、锁文件或 SQLite WAL 文件。`--execute` 先获取 `worker.lock` 的排他锁；锁仍被 Worker 持有则拒绝。它在整个快照期间同时持有 SQLite 写锁，用独立只读连接的 SQLite backup API 捕获已提交 WAL 数据，复制数据卷中的文件证据，并核对源文件、备份文件与数据库登记产物的 SHA-256 和大小。复制前后文件变化、符号链接、特殊文件、已有或嵌套输出目录均拒绝；失败时不发布备份目录。

成功目录包含 `observatory.sqlite3`、完整 `runs/`（包括分卷、归档、日志和证据）及 `manifest.json`。清单记录数据库哈希、每个文件哈希/大小、时间及使用的锁；先在临时目录生成，通过数据库 `integrity_check` 后原子发布。备份目录与数据库只对 root 开放。

`build-data` 通常体积很大，不包含在该备份脚本内。Worker 保持停止时，助手另外取得 `lean-observatory_build-data` 的卷挂载点，以宿主 `tar` 完整保存构建卷（保留所有权、权限、符号链接和时间），生成 SHA-256 清单并核对归档可读性；不在构建卷内部写备份。另记录当前源码 SHA、API/Worker 镜像 ID 和 digest、两个卷名/挂载点、Compose 渲染配置，并将 `.env`、证书与私钥保存到权限 `0700/0600` 的单独安全备份位置。两个快照都完成并经核验后，才可重新启动 Worker。

## 恢复与回滚

恢复由助手完成：先停本项目 Worker，备份当前状态，核对备份数据库与证据文件 SHA-256、SQLite `integrity_check` 和源码/镜像清单，再把数据库与 `runs/` 恢复到新建数据卷、构建归档恢复到配套新建 build 卷。数据库使用 backup API 的产物，不另带旧 `-wal`、`-shm` 或 `worker.lock` 文件。核对数据卷所有权符合容器的 `0:10001` Worker / `10001:10001` API，目录可由所需服务访问；不改变证据内容。

恢复或回滚镜像时先保留 `ENABLE_REAL=0`、重建并启动禁用真实任务的 Worker；它会将旧 running/paused 状态标为 interrupted。助手核对同一任务的源码、镜像和检查点后，执行 `python3 scripts/online_acceptance.py --resume-run RUN_ID` 刷新该任务的验收。此模式只允许指定的真实 paused/interrupted/failed/resource_exhausted 任务，拒绝任何 Mock 历史和其他活动任务，保留日志与产物；API、JSON 报告和 SSE 均指向相同 ID，其余 TLS、源码、资源、只读与宿主指标检查保持一致。回执含 `resumeRun`，不可用于创建或领取其他任务。验收后助手才启用 Worker 并对同一任务执行 `backend.control resume RUN_ID`，不创建新任务。回滚不删除旧数据卷，不使用 `docker compose down -v`，也不清空历史来伪造空卷验收。

## 本地验证边界

购机前可以验证 shell 语法、临时发布包 dry-run、纯验收校验函数和真实 SQLite WAL/文件一致性备份。主机 apt 安装、systemd、实际 Docker 限额、DNS、ACME 签发/续期和可信 HTTPS 必须在购机且授权连接以后验收；这些没有被本地夹具证明。

## 当前实例的运行时配置

地址 `104.105.149.244`，两个入口为 `lean.tano.asia` 与 `lean.lanunion.org.cn`；同一证书 SAN 覆盖两者，自动续期配置保存在现有证书 lineage。后台真实任务 ID 为 `20565ace60c2`，不得为查看进度重复创建任务。

64CPU宿主机上，Nginx `worker_processes auto` 在原有64-PID限制下会使重载失败。已在本地相同限额下验证固定1个Worker及连续重载，再将运行时配置存于部署目录 `.data/ops/nginx-tls.conf`、覆盖文件 `.data/ops/compose.nginx.runtime.yaml`，只重建Nginx，证明Worker未重启。重建Web时必须追加该覆盖文件：

```sh
docker compose -p lean-observatory -f compose.yaml -f compose.tls.yaml -f .data/ops/compose.nginx.runtime.yaml --profile verification up -d --no-deps --wait nginx
```

续期hook的 `exec nginx -t` / `exec nginx -s reload` 会读取当前容器内已修正的配置，无需重建。覆盖配置、局部测试和生产重载证据见 [online/ops](../reports/online/ops)。CPU、内存与PID上限均保留原配置；原验收核心源码保持不变。

纯Python完整性扫描期间，原版本心跳存在更新空档；外部编译命令阶段由CommandRunner持续更新，已恢复正常。该问题记录待后续版本修正，不为消除告警伪造心跳或进度，不为热更新而中断当前编译。
