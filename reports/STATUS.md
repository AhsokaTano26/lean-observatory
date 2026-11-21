# 执行状态

- 本地平台验收：通过，72 个后端、10 个图表、13 个浏览器测试及构建、容器与真实小型 Lake 流水线。
- 正式部署：完成，root@104.105.149.244；Ubuntu24.04 x86_64，64 vCPU / 251.68 GiB RAM。
- 页面：https://lean.tano.asia / https://lean.lanunion.org.cn，可信多域名 HTTPS、真实 host_agent 指标、纯展示。
- 线上八项门禁、实际 AppArmor enforce 隔离夹具、浏览器验收及证书续期演练：通过。
- 正式任务：20565ace60c2，正在完整编译，48 并发，每个 Lean 子进程 -j1。
- 原始14分卷：239275554 bytes；SHA-256实测与给定9631b4f020199e580ba86178cb56c6e9b09f690c2369a80dc4334aa93f49c7fc一致。
- 源码清单：175187个Lean文件；Lean4.33.1、Mathlib0df444a360eaa60ab8c11dca51a86af692955474实测匹配。
- 五个真实定理审计、原始Main内核重放：尚未执行，排在完整编译之后。
- 不同实现的独立内核、完整数学语义复核：未完成。
- proofAccepted=false，不宣布证明通过。

本状态是部署及启动记录，实时进度与退出码请查看线上页面。Nginx 必须使用 reports/online/ops 中记录的运行时覆盖配置，避免64CPU自动派生进程触及PID上限。
