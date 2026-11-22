# RH 主动暂停与 NS 自动检查结果

## RH 暂停与大小

2026-11-22 16:27:06（北京时间），按用户指令通过原有管理命令暂停 RH 重放，未取消或重启任务。实际 leanchecker PID1117379、启动ticks4110760 保留，进程为 T（已停止执行），暂停后CPU计数不再增长。编译和审计记录保留，重放未完成，没有改写为通过。

| 测量对象 | 大小 |
| --- | ---: |
| 重放进程常驻内存 VmRSS | 81.17 GiB（87.16 GB） |
| 进程峰值 VmHWM | 82.34 GiB（88.41 GB） |
| 进程虚拟地址空间 VmSize | 116.52 GiB |
| Swap | 0 |
| `.lake/build/lib/lean` 编译库文件逻辑大小 | 100,211,339,672 bytes（100.21 GB） |
| RH 整个项目目录文件逻辑大小，含依赖与构建产物 | 1,270,995,035,409 bytes（1.27 TB） |

内存数值是加载证明后的进程占用。文件逻辑大小由`du --bytes --one-file-system`测得，不等于物理分配磁盘块数。暂停保留进程现场和内存，可恢复运行，不会释放上述RAM。`leanchecker`可执行启动文件本身为50,896 bytes，但它动态链接Lean库，该数值不代表完整内核体积。

[原始暂停与测量记录](rh-user-pause.json)。用户选择采用[Andrew Sutherland公开的外部验证记录](https://math.mit.edu/~drew/grh/)作为依据，不再等待本机重放；该外部结论没有被写成此次本机运行的退出码或成功结果。

## NS 已完成的机器检查

NS run `ns-f9e8bc5b38b6` 于2026-11-22 16:30:56（北京时间）完成并持久化，状态为`CHECKS_COMPLETED`。源码/依赖、2659文件完整编译、两个NS目标的类型与公理审计、fresh Lean内核重放、Comparator独立检查、结果归档七阶段均为`PASSED`且退出码0。

目标为 `NavierStokes.Comparator.navier_stokes_breakdown_R3` 和 `NavierStokes.Comparator.navier_stokes_breakdown_periodic`。二者依赖公理均仅为`propext`、`Classical.choice`、`Quot.sound`。独立Comparator的真实命令退出0，完整日志包含nanoda接受、Lean默认内核接受及`Your solution is okay!`。原生ABI4告警保留5条，实际隔离探针和已记录的补偿控制通过。没有独立验证Euler目标。

通过HTTPS下载并按Dashboard公布的字节数与SHA-256逐个核对：

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| [最终验证报告](ns-final-verification.json) | 119111 | `469b4c2dadd82d8e5748265ef67b21fbb22a3d4c3a914a090b32ecfd8d24c9e0` |
| [独立检查报告](ns-final-independent.json) | 4541 | `260cb1ca8d38a448426ebbb8c95d3783b3483b73a7dc8651427d07910672f38f` |
| [完整Comparator日志](ns-final-comparator.log) | 40997 | `f5e06a5e820d653b009471c25dccea916dae16ba5a8fd0e087e2b22815fc785e` |

最终报告保留`proofAccepted=false`、`semanticReview=NOT_RUN`：上述结论是列明目标与工具链的机器检查结果，没有代替人工数学语义复核。

[线上NS页面](https://lean.tano.asia/ns/)、[原始最终报告下载](https://lean.tano.asia/ns/api/artifacts/verification-result.json)。报告记录固定源码commit `f9e8bc5b38b6e212696e8a30e3e91517af887bbd`，Lean v4.34.0-rc2及锁定依赖；未修改证明源码或伪造结果。

## 调度和进程保留

为避免原有RH暂停联动终止NS，先短暂停止自己的NS调度器，NS验证进程始终保留，再部署经过222项Python测试、全部页面/断线恢复/隔离/构建验收的主动暂停规则。该例外需绑定两个runID、用户授权与不可变历史准入，只允许现有NS继续；不允许启动新任务、伪造RH成功或提升内存上限。RH真实失败、异常停止或证据变化仍阻止继续。

调度器已恢复在线，所有现有Worker/API/Nginx容器ID、PID、启动时间均未变化，NS真实验证进程也没有重启。[部署与保留记录](rh-pause-controller-update.json)。运行中的Worker版本仍为`741d5ac`（源指纹`fb3ba6f…a86973`），仅宿主机调度器更新至`58e998a`（本地验收源指纹`5aea8445…6c4ba`）；其余证明Worker实现逐文件哈希与原容器一致，无需重跑成功检查点。
