(() => {
  'use strict';

  const get = id => document.getElementById(id);
  const theme = get('theme');
  const themeKey = 'lean-observatory-archive-theme';

  function applyTheme(value) {
    document.documentElement.dataset.theme = value;
    const label = value === 'dark' ? '切换浅色主题' : '切换深色主题';
    theme.setAttribute('aria-label', label);
    theme.title = label;
    theme.textContent = value === 'dark' ? '☀' : '◐';
  }

  let savedTheme;
  try { savedTheme = localStorage.getItem(themeKey); } catch {}
  applyTheme(['light', 'dark'].includes(savedTheme) ? savedTheme :
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  theme.addEventListener('click', () => {
    const value = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(value);
    try { localStorage.setItem(themeKey, value); } catch {}
  });

  const archive = window.LEAN_OBSERVATORY_RESULTS;
  if (archive?.schemaVersion !== 1 || archive.static !== true || !archive.projects?.length) {
    get('loading').textContent = '无法读取结果存档。请解压完整存档，并在原目录中打开 index.html。';
    return;
  }

  let currentProject = archive.projects[0];
  const search = get('log-search');
  const stageFilter = get('log-stage');
  const number = new Intl.NumberFormat('en-US');
  const date = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'medium',
  });
  const logTime = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai', timeStyle: 'medium',
  });
  const money = new Intl.NumberFormat('en-US', {
    style: 'currency', currency: archive.cost.currency || 'USD', currencyDisplay: 'code',
  });
  const states = {
    passed: '通过', paused: '已暂停', failed: '失败', pending: '未完成',
    skipped: '未执行', running: '执行中', not_run: '未执行',
  };

  function element(tag, value, classes) {
    const node = document.createElement(tag);
    if (classes) node.className = classes;
    if (value != null) node.textContent = value;
    return node;
  }

  function timestamp(value) {
    return new Date(typeof value === 'number' ? value * 1000 : value);
  }

  function time(value) {
    return value == null ? '未记录' : date.format(timestamp(value)) + ' (UTC+8)';
  }

  function duration(seconds) {
    if (seconds == null) return '未记录';
    if (seconds < 60) return number.format(seconds) + ' 秒';
    const whole = Math.floor(seconds);
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor(whole / 60) % 60;
    return hours ? hours + ' 小时 ' + minutes + ' 分' : minutes + ' 分 ' + whole % 60 + ' 秒';
  }

  function stageState(status) {
    return String(status ?? '').toLowerCase();
  }

  function stateText(status) {
    return states[stageState(status)] ?? status ?? '无记录';
  }

  function markState(node, status) {
    node.dataset.state = stageState(status);
    return node;
  }

  function detailsRow(label, content) {
    const row = element('div');
    const definition = element('dd');
    definition.append(content);
    row.append(element('dt', label), definition);
    return row;
  }

  function citation(label, url) {
    const link = element('a', label);
    if (/^https?:\/\//i.test(url)) {
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    }
    return link;
  }

  function stageCount(project) {
    return project.passedStages + ' / ' + project.totalStages;
  }

  function projectCard(project) {
    const card = element('article', null, 'project');
    const summary = element('p', null, 'project-summary');
    const state = markState(element('strong', project.headline), project.localReplay);
    summary.append(state, element('span', stageCount(project) + ' 阶段通过'));

    const meter = element('div', null, 'project-meter');
    meter.setAttribute('aria-hidden', 'true');
    meter.append(...project.stages.map(stage => markState(element('span'), stage.status)));

    const open = element('button', '查看详情', 'project-open');
    open.type = 'button';
    open.setAttribute('aria-label', '查看 ' + project.name + ' 详情');
    const arrow = element('span', '↘');
    arrow.setAttribute('aria-hidden', 'true');
    open.append(arrow);
    open.addEventListener('click', () => {
      renderProject(project);
      get('project-name').focus({ preventScroll: true });
      get('detail').scrollIntoView({ block: 'start' });
    });
    card.append(element('h2', project.name), element('p', project.englishName, 'meta'), summary, meter, open);
    return card;
  }

  function metric(label, value, detail) {
    const block = element('div', null, 'metric');
    block.append(element('span', label, 'meta'), element('strong', value));
    if (detail) block.append(element('p', detail, 'meta'));
    return block;
  }

  function stageItem(stage) {
    const item = markState(element('li', null, 'stage'), stage.status);
    item.append(element('strong', stage.label), element('span', stateText(stage.status)));
    const detail = [];
    if (stage.exitCode != null) detail.push('退出码 ' + stage.exitCode);
    if (stage.restored) detail.push('恢复自检查点');
    if (stage.commandSeconds != null) detail.push('命令 ' + duration(stage.commandSeconds));
    if (detail.length) item.append(element('span', detail.join(' · '), 'meta'));
    return item;
  }

  function auditCard(audit) {
    const card = element('article', null, 'audit');
    const heading = element('h4');
    heading.append(element('code', audit.name));
    card.append(heading);
    if (audit.expectedType) {
      const type = element('p', '预期类型 ', 'audit-type meta');
      type.append(element('code', audit.expectedType));
      card.append(type);
    }
    const statuses = element('dl', null, 'audit-status');
    for (const [label, value] of [
      ['类型', audit.type], ['公理', audit.axioms],
      ['内核重放', audit.kernel ?? audit.replay], ['独立检查', audit.independent],
    ]) {
      statuses.append(detailsRow(label, markState(element('span', stateText(value)), value)));
    }
    card.append(statuses);
    if (audit.dependencies?.length) {
      const dependencies = element('p', '公理依赖 ', 'axioms meta');
      dependencies.append(element('code', audit.dependencies.join(' · ')));
      card.append(dependencies);
    }
    return card;
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return number.format(bytes) + ' B';
    if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + ' KiB';
    return (bytes / 1024 ** 2).toFixed(1) + ' MiB';
  }

  function downloadItem(file) {
    const listItem = element('li', null, 'download');
    const title = element('p', null, 'download-name');
    const link = element('a', file.title);
    link.href = './' + file.path.split('/').map(encodeURIComponent).join('/');
    link.download = '';
    title.append(link, element('span', formatBytes(file.bytes), 'meta'));
    const hash = element('p', 'SHA-256 ', 'download-meta');
    hash.append(element('code', file.sha256));
    listItem.append(title, hash);
    return listItem;
  }

  function renderLogs() {
    const query = search.value.trim().toLowerCase();
    const rows = currentProject.logs.filter(row => {
      const content = [row.stage, row.level, row.message].join(' ').toLowerCase();
      return (!stageFilter.value || stageFilter.value === row.stage) && content.includes(query);
    });
    get('log-count').textContent = rows.length + ' / ' + currentProject.logs.length + ' 条 · 时间为 UTC+8';
    const entries = rows.map(row => {
      const entry = element('div', null, 'log-row');
      entry.dataset.level = stageState(row.level);
      const clock = element('time', row.ts == null ? '未记录' : logTime.format(timestamp(row.ts)), 'meta');
      entry.append(clock, element('span', [row.stage, row.level].filter(Boolean).join(' · '), 'meta'),
        element('code', row.message));
      return entry;
    });
    const list = get('log-rows');
    list.replaceChildren(...(entries.length ? entries : [element('p', '没有符合条件的日志', 'log-empty')]));
    list.scrollTop = 0;
  }

  function renderProject(project) {
    currentProject = project;
    get('project-name').textContent = project.name;
    markState(get('project-status'), project.localReplay).textContent = project.headline;
    for (const button of get('project-switch').children) {
      button.setAttribute('aria-pressed', String(button.dataset.project === project.id));
    }

    const compiled = project.compile;
    get('metrics').replaceChildren(
      metric('阶段通过', stageCount(project)),
      metric('模块编译成功', number.format(compiled.succeeded),
        '共 ' + number.format(compiled.total) + ' · ' + number.format(compiled.failed) + ' 失败'),
      metric('定理审计', number.format(project.audits.length)),
      metric('记录耗时', duration(project.elapsedSeconds)),
    );
    get('review').textContent = project.semanticReview === 'NOT_RUN'
      ? '人工数学语义复核未进行。' : '人工数学语义复核状态 ' + project.semanticReview;

    const external = get('external');
    const reference = project.externalVerification;
    external.hidden = !reference;
    external.replaceChildren();
    if (reference) {
      external.append(citation(reference.name, reference.url), element('p',
        '外部验证依据 · 页面更新于 ' + time(reference.pageUpdatedAt) + '。本机内核重放未完成。', 'meta'));
    }

    const stages = get('stages');
    stages.style.setProperty('--stage-count', project.stages.length);
    stages.replaceChildren(...project.stages.map(stageItem));
    get('audit-count').textContent = project.audits.length + ' 项';
    get('audits').replaceChildren(...project.audits.map(auditCard));

    const source = project.source;
    get('source').replaceChildren(
      detailsRow('上游来源', citation(source.url, source.url)),
      ...(source.commit ? [detailsRow('源码提交', element('code', source.commit))] : []),
      detailsRow('源码归档 SHA-256', element('code', source.archiveSha256 ?? '未记录')),
      detailsRow('编译并行任务', String(compiled.jobs ?? '未记录')),
      detailsRow('Lean', element('code', source.lean ?? '未记录')),
      detailsRow('Mathlib', element('code', source.mathlib ?? '未记录')),
      detailsRow('运行 ID', element('code', project.runId)),
      detailsRow('项目采样时间', time(project.capturedAt)),
    );

    search.value = '';
    const options = new Map(project.stages.map(stage => [stage.id, stage.label]));
    for (const row of project.logs) {
      if (row.stage && !options.has(row.stage)) options.set(row.stage, row.stage);
    }
    stageFilter.replaceChildren(new Option('全部阶段', ''),
      ...Array.from(options, ([id, label]) => new Option(label, id)));
    renderLogs();
    get('downloads').replaceChildren(...project.downloads.map(downloadItem));
  }

  document.title = archive.title;
  get('snapshot').textContent = '静态快照 · ' + time(archive.capturedAt);
  const cost = archive.cost;
  get('cost-amount').textContent = cost.serverEstimatedUsd == null ? '未记录' : money.format(cost.serverEstimatedUsd);
  const hourly = cost.hourlyUsd == null ? '' : ' · ' + money.format(cost.hourlyUsd) + ' / 小时';
  get('cost-note').textContent = time(cost.capturedAt) + hourly + ' · 最终账单未归档';
  get('projects').replaceChildren(...archive.projects.map(projectCard));
  get('project-switch').replaceChildren(...archive.projects.map(project => {
    const button = element('button', project.id.toUpperCase());
    button.type = 'button';
    button.dataset.project = project.id;
    button.addEventListener('click', () => renderProject(project));
    return button;
  }));
  search.addEventListener('input', renderLogs);
  stageFilter.addEventListener('change', renderLogs);
  renderProject(currentProject);
  get('loading').hidden = true;
  get('archive').hidden = false;
})();
