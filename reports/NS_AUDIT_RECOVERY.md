# NS 审计与内核重放脚本修复记录

采样：2026-11-22T07:37:58.993975+00:00。NS `RUNNING/kernel`，RH `running/replay`。最终验证仍在进行，`proofAccepted=false`。

原错误是验证平台生成的 Lean 脚本接口不兼容：审计脚本的两处 `logInfo` 未限定命名空间；重放脚本把纯函数 `IO.FS.Stream.ofBuffer` 当成 IO、文件路径参数推导失败，且缺少常量比较实例。已修复限定名、路径构造和纯函数调用，并从锁定的 [Comparator.Compare](https://github.com/leanprover/comparator/blob/19e111e2141cf333c7daff0f64c5f24acc91dd2e/Comparator/Compare.lean) 导入其常量比较实例。[Lean 固定版本声明接口](https://github.com/leanprover/lean4/blob/v4.34.0-rc2/src/Lean/Declaration.lean) 与服务器真实类型检查作为接口依据。

## 已核实的状态

- 完整编译 2659/2659，失败0；原 `lake build` 记录、退出码0、原始日志及全部编译产物保留，没有重编。
- 两个 NS 定理的类型与公理审计已通过，真实退出码0；依赖仅为 propext、Classical.choice、Quot.sound。
- 新重放脚本在服务器 Lean v4.34.0-rc2 的类型检查退出码0。实际源码导出已成功，当前 `lean --run replay.lean solution.ndjson` 正在执行，尚无退出码或最终通过结论。
- RH 原容器ID、PID、启动时间、镜像、配置与挂载哈希保持一致，RH仍运行原内核重放。
- 已通过 HTTPS 下载验证：当前 `compile.json` 检查点与 `audit-report.json` 可读取；检查点替换保持0644，历史备份0444、事务目录0755，UID10001只读API可正常提供证据。

## 检查点复用

恢复前逐一验证源码、依赖、编译、审计四阶段所有输出的字节数、SHA-256、路径、原始退出码及完整父链，并核验上次命名空间修复的原始/提议回执和持久化清单。两次迁移只允许对应的精确脚本修改；其他代码或产物变化一律拒绝复用。

先保存不可变原始回执与提议回执，再提交新输入链和迁移记录；保留原执行时间、命令与输出哈希。先停止自己的 NS 调度器，队列保持暂停，迁移成功且账本完整后才恢复。源码、依赖、编译、审计均通过原检查点恢复。旧 NS 已退出容器分别保留为 `-before-audit`、`-before-kernel`；数据卷和历史失败日志全部保留。新旧镜像的可信工具链层完全一致。

## 测试与版本

本地206项Python测试、真实Lean审计诊断、真实内核有效/无效证明与四种商类型篡改负向测试、页面、Nginx路由、资源配置、构建及语法检查均通过。迁移测试包含篡改拒绝、断电恢复、幂等与文件权限。缓存的本地Lean v4.33.1内核测试明确使用原生回放API的版本适配；生产脚本另在真实v4.34.0-rc2环境中完整类型检查，未用模拟检查器替代生产验证。

源码提交：`b34452b`；接受并部署的源指纹 `47d3350cc2e4c5a0a20fb25e26aa323ef93f649e1583d434d50a7f328dc1fc61`。发布包SHA-256 `33036b099671fbf739a686c3aa3bff0dce85767644fdb496cd3c78e5f90c1f7a`（81841 bytes）。[本地验收](ns-local-acceptance.json)、[真实恢复快照](ns-kernel-recovery.json)。

原NS证明源码与依赖配置均未修改；RH环境未改。独立检查与最终结果持久化仍待执行，报告中的成功仅限列出的已完成检查。
