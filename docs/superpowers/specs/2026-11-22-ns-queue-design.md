# NS串行队列设计

用户要求RH运行不中断，并在RH全部机器检查及结果持久化成功后才考虑NS。RH原容器/配置/卷/Worker/Dashboard均不改、不重启。当前RH20565ace60c2编译中，固定现有Lean4.33.1环境。

## 实现选择与边界

采用独立附加服务，部署至/opt/lean-observatory-ns、独立Compose项目lean-observatory-ns和独立SQLite/卷。替换现有Worker或改旧Dashboard均会触及运行环境，故不采用。宿主调度器只读RH现有API与Docker进程状态；仅允许操作自己的NS容器。独立只读项目页面在https://lean.tano.asia:9443，复用现有证书只读挂载，不修改原Nginx、证书或DNS。页面提供RH链接和NS进度/日志/资源/结果/估算费用。队列服务最高0.25CPU/256MiB；NS重型工具准备、下载、编译只允许在RH结束和启动门禁通过后执行。

NS固定openai/NavierStokesAndEuler@f9e8bc5b38b6e212696e8a30e3e91517af887bbd，Lean4.34.0-rc2，原锁定manifest。全仓2659个Lean文件（含Euler及官方挑战），真实NS两项定理审计import NavierStokes.ComparatorSolution，不可把含sorry的挑战声明当证明。独立核验按官方ComparatorChallenges/NavierStokes.json，缺少真实工具或结果必须失败/暂停，不能以Mock结果冒充。

## 队列与门禁

初始NS=QUEUED，依赖固定RH ID。RH必须mode=real/status=checks_completed/finishedAt有值；六阶段passed且exitCode为整数0；完整175187编译、失败0；五个声明类型/公理/replay均passed；版本/归档SHA匹配；无活动命令，无其他运行任务。proofAccepted=false与人工语义/不同实现内核未完成单列，不把它们写成数学证明通过。

必须再下载并校验verification-result.json及完整日志归档，原子持久化到NS服务自己的证据目录后才标记RH依赖满足。终态早于finally产物注册的窗口不得启动NS。RH失败/中断/取消/资源耗尽或实际Worker停止时，NS转PAUSED并持久化告警；仅心跳暂时过期不当作失败（既有纯Python扫描阶段有心跳空档）。未知/失联一律不启动。

用户已澄清NS没有额外预算，初值capUsd=0。因此即使RH成功，NS仍必须PAUSED(reason=budget)且发告警，不实际消耗NS重型计算。只允许宿主CLI明确增加预算。默认小时费率3.36美元，费用为任务时段估算，未接入云账单/余额；不冒称实际账单。启动至少预留300秒，预算不足阻断。预算为0不触发任何NS构建/下载/编译。资源启动门禁：64CPU、可用内存至少224GiB（NS限208GiB加系统预留）、空盘至少100GiB、无RH活动验证。NS限48CPU、cpuset8-55、208GiB、禁swap。

服务重启时，SQLite事务和flock保证单调度器；QUEUED/PAUSED持久化；已运行NS容器按固定项目/任务ID检查并接管，不重复启动。NS阶段checkpoint绑定源码/命令/产物哈希，成功阶段验证后跳过；进行中阶段不能伪造退出码。所有日志与结果落独立卷。

## 通知

用户明确授权POST https://uptimepulse.tano.asia/webhook/general。仅title/message/source/level/timestamp/fields/url顶层，fields扁平标量，时区ISO时间，保守限制最终JSON UTF8小于1500字节。200=发送确认，202=服务端已排队（不谎称送达）；持久化outbox、事件去重、失败退避重试，HTTP不确定结果可能至少一次投递。不得发送其他收件人或公开敏感配置。

## 验收

本地TDD：真实SQLite重启/租约、RH各失败与缺失结果、预算0绝不调用执行器、正确源/类型/公理解析、checkpoint跳过/重放、Webhook200/202/失败和长度、HTTP只读/SSE重连、浏览器排队页面。原项目全量npm test保持通过。部署前后对RH容器ID/PID/StartedAt/Image/配置/任务ID比对一致；只启动新服务。NS全量验证状态保持未执行。
