# 主题及图表验收 · 2026-11-21

视觉参考：https://bandori.fans/en。已实看页面、深浅色截图及公开 CSS；借鉴暖纸色、细线网格、方角、标题比例和导航节奏，未复制其品牌或站点内容。

本次把全部图表替换为 D3 时间曲线，坐标按实际容器像素计算。资源读数、编译吞吐、历史、缺测和过期状态均来自后端数据及可复查的计算逻辑。当前本地演示仍是明确标记的 Mock。

## QA Evidence

- Rubric score: 15/16。产品适配、层级、状态、响应式、视觉、性能、验证各 2；无障碍 1（已检查键盘、语义、焦点与文字对比，未做完整读屏器验收）。
- Surface inspected: 实际 Playwright Chromium 页面与截图。Browser 插件不可用，因此使用本机 Playwright。
- Viewports checked: 320、360、390、768、1024、1280、1440、1600px；深色和浅色。手机图表另使用真实触控上下文。
- Interaction path tested: 六页导航、移动菜单、主题切换/刷新持久化、独立 CLI 驱动的 Mock 暂停恢复、失败/中断/资源不足、审计展开、日志筛选/下载、指针/触摸/方向键读数、时间范围、断网及恢复。
- Commands run: `npm test` → 72 个后端 + 10 个图表计算 + 构建 + 13 个浏览器测试通过。跳转链接样式调整另用 `npm test -- --grep 'editorial|geometry|touch|responsive'` 复查相关页面；原始输出保存在 native-tests.log 与 ui-revision.log。
- Audit scripts: 未运行启发式样式扫描器；使用实际 DOM 几何、溢出、SVG 变换比例和交互断言，并逐张检查关键截图。
- Visual revision loop: 修正 SVG 字体/曲线拉伸与时间比例；手机审计状态改为名称下方显示；修正离屏跳转链接在全页截图中的绘制及点击误触路由；证明审计的移动布局规则限定到自身，结果中心保留命令与退出码。同步修正资源过期值、断线“实时”标记、30 分钟历史长度和稀疏长中断连线问题。取消 Mock 任务与 Worker 调度交错可能复活任务的问题，也已确定性复现并修复。
- Remaining gaps: 正式服务器及可信 HTTPS 尚未部署；完整原始证明仍未运行。相关本地容器测试只涉及平台及 tiny Lean fixture。

## 证据

- [浅色桌面](../docs/screenshots/desktop-light.png)
- [深色桌面](../docs/screenshots/desktop-dark.png)
- [服务器图表](../docs/screenshots/server-light.png)
- [320px 页面](../docs/screenshots/responsive-320.png)
- [390px 触控图表](../docs/screenshots/server-mobile-390.png)
- [测试日志](native-tests.log)
- [机器可读门禁](local-acceptance.json)

本轮进一步按用户要求去除管理员和任务控制，浏览器交互仅产生 GET 请求；POST/PUT/PATCH/DELETE 即使携带旧令牌也返回 405。后台 CLI 控制与 Web 展示完全分开。

参考设计和本地平台测试不构成数学证明通过的证据。
