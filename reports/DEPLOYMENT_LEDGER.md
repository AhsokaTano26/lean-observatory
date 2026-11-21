# 部署记录 — root@104.105.149.244

- 用户已明确授权助手部署与运行，并于本轮提供 SSH 入口。
- 本地门禁已重新核对，与当前源码指纹 07b2cd8f2c01a6c87406dc2b03667d3ee5de415e3a9682e35ddcb9dbe184d85a 一致。
- 当前阶段：只读服务器预检；尚未修改目标服务器或启动验证。

- 只读预检通过：Ubuntu24.04.5 x86_64，64 vCPU，251.68 GiB RAM，2.39 TiB 空闲磁盘；80/443空闲，Docker未安装，无已有平台。
- 为执行预检仅上传临时只读检查脚本到 /tmp；尚未修改服务配置。
- 域名尚无A/AAAA；用户选择自行添加 A lean → 104.105.149.244，仅DNS。

- 服务器 AppArmor enabled=Y；开始上传并校验已测试发布包，部署脚本独立记录完整日志与退出码，ENABLE_REAL 保持0。

- HTTPS已签发，可信CA访问/healthz返回200；真实host_agent指标64CPU/251.68GiB RAM，无Mock任务。
- 生产Worker专用AppArmor enforce下 tiny Lean/fresh/文件网络边界/子进程清理通过，真实证明未开始。
- 实际HTTPS浏览器六页、1440/390px、主题、只读交互、控制台通过；Browser plugin not available，使用现有Playwright Chromium。
- Certbot续期演练日志显示正常随机延迟329秒，等待完成；继续执行八项线上验收。

- 初装脚本退出0；Certbot续期演练成功，线上八项门禁通过，浏览器验收通过。
- 用户补充第二入口 lean.lanunion.org.cn；A已指向同一服务器、无AAAA，正在扩展同一证书SAN。
- Ruling: 第二入口使用现有默认TLS虚拟主机与多域名SAN证书，保持已验收源码不变；分别验证两个域名的TLS、页面、API及SSE，主任务门禁继续固定lean.tano.asia。若默认主机行为不符合预期，别名访问测试将阻断启动。

- 已启动唯一真实任务20565ace60c2，原始14分卷239275554 bytes，实际SHA256与9631b4f020199e580ba86178cb56c6e9b09f690c2369a80dc4334aa93f49c7fc一致。
- Nginx重载超时根因：64CPU自动生成Worker触及64-PID上限；局部重启仅短暂恢复。已本地以相同CPU/内存/PID限额测试1个Worker配置，连续两次重载/HTTPS fixture均0，再部署独立 .data/ops runtime override，仅重建Nginx，证明Worker未重启。
- 两个域名可信HTTPS healthz均200。运行时覆盖配置与测试证据位于reports/online/ops；原验收平台源码指纹保持不变。以后重建Nginx应带 .data/ops/compose.nginx.runtime.yaml；续期hook的exec reload读取容器当前配置。
- Worker在完整性阶段纯Python操作期间心跳更新有空档；实际进程CPU活跃且任务继续，在外部命令阶段恢复。待后续版本改为独立心跳；不注入虚假心跳或伪造进度。

- 编译阶段真实心跳恢复，已采集618/175187、失败0的实际快照；未推断完成。
- Web运行时配置已在生产执行reload并对两个域名CA验证healthz均200；Worker任务ID及进程未中断。
