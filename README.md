# Lean Observatory · 黎曼验证观测台

黎曼猜想 Lean 源码独立复现、审计与实时观测平台。**开发中，尚未完成本地验收；尚未部署，也未执行完整证明验证。**

## 执行门禁

本地开发 → 本地测试 → 服务器检查 → 正式部署及线上验收 → 完整 Lean 验证。服务器尚未购买，预期域名为 `lean.tano.asia`。Mock 仅模拟流程，任何检查完成都不会自动宣告数学证明成立。

## 技术结构

- React / TypeScript / Vite 前端，六个监控与审计视图、深浅主题、SSE。
- Python 标准库 API + 独立 Worker + SQLite WAL，持久化状态、日志、指标与报告。
- 原始归档 14 分卷、字节数/SHA-256 检验、Lean v4.33.1 / Mathlib 锁定、源码重编译、类型/公理审计、`leanchecker --fresh Main`。
- Compose/Nginx 部署及资源隔离（实现中）。

## 本地

```sh
npm ci
npm run build
python3 -m backend.api --port 8787
# Worker、浏览器测试及部署说明随实现补全
npm test
```

完整实施约束见 [docs/PLAN.md](docs/PLAN.md)。不在 Git 中存储令牌、原始归档或运行产物。

## 已核实的来源

- [发布方说明](https://alpo.ge/remark.pdf)：脚注提供 14 个原始分卷。
- [社区归档记录](https://github.com/tamnd/riemann-lean/blob/main/SOURCE.md)：哈希为社区记录，非作者签名。
- [原始定理的社区镜像](https://github.com/leanprover-community/riemann-hypothesis/blob/main/src/Main.lean)。
- [Lean checker 说明](https://github.com/leanprover/lean4checker)：使用同一 Lean 内核重放；不同实现的独立内核检查是另一项检查。

本仓库只提供平台代码，不复制或重新授权原作者证明源码。
