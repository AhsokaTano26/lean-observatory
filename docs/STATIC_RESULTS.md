# 静态结果存档

所有展示数据都来自已取回并校验的证据。网页不使用API、WebSocket、CDN或数据库；双击导出目录的`index.html`即可离线打开，也可把整个目录上传到任意静态托管。

- RH：175,187文件编译和五个定理类型/公理审计通过；本机内核重放由用户主动暂停，未完成。MIT的Andrew Sutherland公开记录作为外部依据单列。
- NS：固定版本的2,659文件编译、两个NS目标审计、fresh Lean内核重放、nanoda及Comparator检查、最终归档通过。`proofAccepted=false`、`semanticReview=NOT_RUN`保留，未宣称完成了人工数学语义复核。
- 费用、耗时、日志均为采样时的静态记录，不随浏览时间增长。费用是共享服务器估算，不是最终账单。

源码模板：`static_results/`。精简数据及原始API快照：`result_snapshots/2026-11-22/`。完整证据和日志放在本地忽略目录`artifacts/verification-results-2026-11-22/`，包含169份原始证据、RH全部22条命令日志归档、NS全部日志事件、依赖锁、审计脚本与校验清单。大型编译产物、证明导出、工具链和运行内存不在此结果备份中。

在项目根目录重新生成已解压的结果包（不需要服务器）：

```sh
python3 scripts/build_static_results.py \
  --root artifacts/verification-results-2026-11-22 \
  --rh-logs artifacts/verification-results-2026-11-22/downloads/rh-complete-logs.tar.gz \
  --ns-events artifacts/verification-results-2026-11-22/downloads/ns-complete-events.ndjson.gz
```

查看或校验：

```sh
cd artifacts/verification-results-2026-11-22
shasum -a 256 -c SHA256SUMS
python3 -m http.server 8890 --bind 127.0.0.1
```

`data/results.json`是可供其他静态页面读取的结构化数据；同内容的`data.js`支持file://直接打开。日志页面只显示最近300条，完整日志有单独下载入口。大文件保留在结果包内，没有提交到Git。

测试：`python3 -m unittest tests.test_static_results -q`；`node --test tests/static-results-browser.test.mjs`。浏览器回归默认使用版本化快照和真实报告构造临时fixture，设置`STATIC_RESULTS_ROOT`可验证完整导出目录。覆盖1440/390/320视口、主题、项目切换、日志筛选、下载哈希、HTTP和file://，并禁止API、外部资源和写请求。
