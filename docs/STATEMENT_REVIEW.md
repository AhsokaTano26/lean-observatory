# 五个最终陈述的文本核对

本次只核对公开镜像固定提交与锁定 Mathlib 的定义文本，未下载原始完整分卷，未解析完整项目的实际 Lean 常量，也未完成证明审计。结论不能替代原始归档 SHA-256、全量编译、公理检查和内核重放。

参考镜像：[tamnd/riemann-lean，af705e0d9a5904326eb0693310e36d9484df7f8f](https://github.com/tamnd/riemann-lean/tree/af705e0d9a5904326eb0693310e36d9484df7f8f)。正式运行仍优先采用作者原始归档，不以此镜像替代完整性校验。

| 名称 | 文本所指范围 |
|---|---|
| `riemannHypothesis` | Mathlib 的 `RiemannHypothesis` |
| `riemannZeta_eq_zero_re` | 排除负偶整数平凡零点和 `s=1` 后，ζ 的零点位于临界线 |
| `LFunction_ne_zero_of_half_lt_re` | 所有正模数 Dirichlet 特征的右半平面无零点，排除主特征的 `s=1` |
| `LFunction_eq_zero_re` | 所有 Dirichlet 特征在开临界带 `0 < Re(s) < 1` 内的零点位于临界线 |
| `LFunction_eq_zero_re_of_isPrimitive` | 上述开临界带结论限制到本原特征 |

核对的 Mathlib 为用户指定的 `0df444a360eaa60ab8c11dca51a86af692955474`：[RiemannZeta.lean](https://github.com/leanprover-community/mathlib4/blob/0df444a360eaa60ab8c11dca51a86af692955474/Mathlib/NumberTheory/LSeries/RiemannZeta.lean)、[DirichletContinuation.lean](https://github.com/leanprover-community/mathlib4/blob/0df444a360eaa60ab8c11dca51a86af692955474/Mathlib/NumberTheory/LSeries/DirichletContinuation.lean)。这里的 `LFunction` 为解析延拓后的函数；开临界带条件不覆盖非本原 Euler 因子在边界上的零点，也没有声称覆盖所有类型的 L 函数。

已另行审阅同一固定镜像中 92 个包含扩展语法的文件、135 处扫描命中，记录在 `backend/reviewed_extensions.json`。放行绑定整个文件的 SHA-256、行号及 token；任何字节变化或未知扩展仍阻断，`axiom`、`sorryAx` 等禁止项不可被该清单放行。这只是一项预审；原始完整归档中所有 Lean 文件的扫描仍待正式阶段执行。

正式运行必须重新核对原始归档中的 Statements/Main、实际解析的常量、五个精确类型、每个定理的公理输出及 `leanchecker --fresh Main`。不同实现的独立内核与完整数学语义审阅仍标为待执行。
