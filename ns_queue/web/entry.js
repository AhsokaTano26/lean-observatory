(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const themeButton = $('entry-theme');
  const connection = $('entry-connection');
  let connected = false;
  let lastReceivedAt = 0;
  let lastData = null;
  let polling = false;

  function applyTheme(theme) {
    const dark = theme === 'dark';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    themeButton.setAttribute('aria-label', dark ? '切换浅色主题' : '切换深色主题');
    themeButton.setAttribute('aria-pressed', String(dark));
  }
  let savedTheme;
  try { savedTheme = localStorage.getItem('ns-theme'); } catch {}
  applyTheme(savedTheme === 'dark' || savedTheme === 'light' ? savedTheme : 'light');
  themeButton.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(theme);
    try { localStorage.setItem('ns-theme', theme); } catch {}
  });

  const statusLabels = {
    queued: '排队中', running: '运行中', starting: '启动中', pending: '待执行',
    paused: '已暂停', pausing: '暂停中', blocked: '等待处理', failed: '失败', error: '异常',
    cancelled: '已取消', completed: '所列检查完成', checks_completed: '所列检查完成',
    succeeded: '所列检查完成', passed: '所列检查完成', success: '所列检查完成',
    retrying: '重试中', verifying: '核验中', timeout: '已超时', interrupted: '已中断'
  };
  const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  const count = value => number(value) ? Math.trunc(value).toLocaleString('en-US') : '—';
  function percent(compile) {
    return number(compile?.succeeded) && number(compile?.total) && compile.total > 0
      ? Math.min(100, Math.max(0, compile.succeeded / compile.total * 100)) : null;
  }
  function dateText(value) {
    if (!number(value)) return null;
    const date = new Date(value * 1000);
    return Number.isNaN(date.getTime()) ? null : date.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    }).replaceAll('/', '.');
  }
  function setHours(id, value) {
    const node = $(id);
    node.replaceChildren(document.createTextNode(number(value) ? value.toFixed(2) : '—'));
    if (number(value)) {
      const unit = document.createElement('span');
      unit.className = 'entry-unit';
      unit.textContent = '小时';
      node.append(unit);
    }
  }
  function badge(id, value) {
    const raw = typeof value === 'string' ? value : '';
    const normalized = raw.toLowerCase();
    $(id).textContent = statusLabels[normalized] || raw || '等待采集';
    $(id).dataset.state = ['running', 'starting', 'verifying'].includes(normalized) ? 'running'
      : ['queued', 'pending'].includes(normalized) ? 'queued'
      : ['failed', 'error', 'timeout', 'interrupted'].includes(normalized) ? 'failed'
      : normalized === 'paused' || normalized === 'blocked' ? 'paused' : 'unknown';
  }
  function renderConnection() {
    const stale = lastReceivedAt && Date.now() - lastReceivedAt > 15000;
    const online = Boolean(connected && !stale && lastData?.controllerOnline);
    connection.dataset.online = String(online);
    connection.hidden = online;
    connection.dataset.warning = String(Boolean(lastData && !online));
    if (!connected) connection.textContent = lastData ? '连接中断 · 保留上次快照，自动重连' : '连接中断 · 等待数据，自动重连';
    else if (stale) connection.textContent = '数据快照待更新 · 保留上次记录';
    else if (!lastData?.controllerOnline) connection.textContent = '数据已连接 · 调度器心跳待更新';
    else connection.textContent = '实时数据已连接';
  }
  function render(data) {
    if (!data || typeof data !== 'object' || !data.queue || typeof data.queue !== 'object') return;
    lastData = data;
    lastReceivedAt = Date.now();
    const rh = data.rh || {};
    const queue = data.queue;
    const rhCompile = rh.compile || {};
    const nsCompile = queue.compile || {};
    const rhPercent = percent(rhCompile);
    const budget = queue.budget || {};
    const nsStatus = String(queue.status || '').toLowerCase();
    badge('entry-rh-status', rh.status);
    badge('entry-ns-status', queue.status);
    $('entry-rh-progress').textContent = rhPercent === null ? '—' : rhPercent.toFixed(1) + '%';
    $('entry-rh-bar').value = rhPercent ?? 0;
    $('entry-rh-count').textContent = count(rhCompile.succeeded) + ' / ' + count(rhCompile.total);
    $('entry-ns-count').hidden = nsStatus === 'queued' || !number(nsCompile.total);
    $('entry-ns-count').textContent = count(nsCompile.succeeded) + ' / ' + count(nsCompile.total);

    setHours('entry-budget-cap', budget.capHours);
    setHours('entry-budget-used', budget.usedHours);
    setHours('entry-budget-remaining', budget.remainingHours);
    $('entry-budget-remaining').parentElement.dataset.expired = String(number(budget.remainingHours) && budget.remainingHours <= 0);
    const deadline = dateText(budget.deadlineAt);
    $('entry-budget-deadline').textContent = deadline || '等待配置';
    if (deadline) $('entry-budget-deadline').dateTime = new Date(budget.deadlineAt * 1000).toISOString();
    else $('entry-budget-deadline').removeAttribute('datetime');
    renderConnection();
  }
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch('/ns/api/state', { cache: 'no-store' });
      if (!response.ok) throw new Error('State unavailable');
      const data = await response.json();
      connected = true;
      render(data);
    } catch {
      connected = false;
      renderConnection();
    } finally { polling = false; }
  }
  poll();
  if ('EventSource' in window) {
    const stream = new EventSource('/ns/api/events');
    stream.addEventListener('snapshot', event => {
      try { connected = true; render(JSON.parse(event.data)); } catch { connected = false; renderConnection(); }
    });
    stream.onerror = () => { connected = false; renderConnection(); };
  }
  setInterval(() => {
    renderConnection();
    if (!connected || Date.now() - lastReceivedAt > 15000) poll();
  }, 5000);
})();
