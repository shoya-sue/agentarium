/**
 * Agentarium Dashboard — メインスクリプト
 *
 * - SSE 接続で新規トレースをリアルタイム受信
 * - 30秒ごとに Qdrant 統計・スケジューラ状態をポーリング
 * - Skill タイムライン描画
 * - LLM I/O ビューア（クリックで展開）
 */

'use strict';

// ─── 状態管理 ────────────────────────────────────────────
const state = {
  traces: [],          // 全トレース（新しい順）
  selectedTraceId: null,
  errorCount: 0,
  totalCount: 0,
  maxTraces: 200,      // タイムラインの最大表示件数
};

// ─── DOM 参照 ────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const els = {
  liveDot:        $('live-dot'),
  liveLabel:      $('live-label'),
  statTotal:      $('stat-total'),
  statErrors:     $('stat-errors'),
  statQdrant:     $('stat-qdrant'),
  schedulerCount: $('scheduler-count'),
  schedulerBody:  $('scheduler-body'),
  qdrantBody:     $('qdrant-body'),
  timelineBody:   $('timeline-body'),
  timelineCount:  $('timeline-count'),
  llmBody:        $('llm-body'),
  footer:         $('footer'),
  footerEmpty:    $('footer-empty'),
};

// ─── SSE 接続 ────────────────────────────────────────────
function connectSSE() {
  const es = new EventSource('/api/events');

  es.onopen = () => {
    els.liveDot.classList.add('connected');
    els.liveLabel.textContent = 'LIVE';
  };

  es.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'connected') return;
      if (msg.type === 'new_trace' && msg.data) {
        addTrace(msg.data);
      }
    } catch (_) { /* JSON パースエラーは無視 */ }
  };

  es.onerror = () => {
    els.liveDot.classList.remove('connected');
    els.liveLabel.textContent = 'RECONNECTING...';
    es.close();
    // 5秒後に再接続
    setTimeout(connectSSE, 5000);
  };
}

// ─── トレース追加 ─────────────────────────────────────────
function addTrace(trace) {
  // 重複チェック（同じ trace_id は追加しない）
  const traceId = trace.trace_id || trace.skill_name + '_' + trace.started_at;
  if (state.traces.some(t => (t.trace_id || t.skill_name + '_' + t.started_at) === traceId)) {
    return;
  }

  state.traces.unshift(trace);
  if (state.traces.length > state.maxTraces) {
    state.traces = state.traces.slice(0, state.maxTraces);
  }

  state.totalCount = state.traces.length;
  if (trace.status === 'error' || trace.error) {
    state.errorCount += 1;
    addFooterError(trace);
  }

  renderTimeline();
  updateHeaderStats();
}

// ─── ヘッダー統計更新 ─────────────────────────────────────
function updateHeaderStats() {
  els.statTotal.textContent = state.totalCount;
  els.statErrors.textContent = state.errorCount;
}

// ─── タイムライン描画 ─────────────────────────────────────
function renderTimeline() {
  if (state.traces.length === 0) {
    els.timelineBody.innerHTML = '<div class="empty-state">スキル実行待ち...</div>';
    els.timelineCount.textContent = '0';
    return;
  }

  els.timelineCount.textContent = state.traces.length;
  els.timelineBody.innerHTML = state.traces.map(trace => buildTraceItem(trace)).join('');

  // クリックイベントを再バインド
  els.timelineBody.querySelectorAll('.trace-item').forEach(el => {
    el.addEventListener('click', () => {
      const id = el.dataset.traceId;
      selectTrace(id);
    });
  });

  // 選択中アイテムをハイライト
  if (state.selectedTraceId) {
    const selected = els.timelineBody.querySelector(`[data-trace-id="${state.selectedTraceId}"]`);
    if (selected) selected.classList.add('selected');
  }
}

function buildTraceItem(trace) {
  const traceId = trace.trace_id || trace.skill_name + '_' + (trace.started_at || '');
  const status = trace.status || (trace.error ? 'error' : 'success');
  const skillName = trace.skill_name || '(unknown)';
  const startedAt = formatTime(trace.started_at);
  const durationMs = trace.duration_ms != null
    ? `${trace.duration_ms}ms`
    : (trace.elapsed_seconds != null ? `${(trace.elapsed_seconds * 1000).toFixed(0)}ms` : '');

  // サマリー（エラーメッセージ or 出力の最初の部分）
  let summary = '';
  if (trace.error) {
    summary = trace.error;
  } else if (trace.output && typeof trace.output === 'object') {
    const firstVal = Object.values(trace.output)[0];
    summary = firstVal ? String(firstVal).slice(0, 80) : '';
  }

  return `
    <div class="trace-item" data-trace-id="${escHtml(traceId)}">
      <div class="trace-status-bar ${escHtml(status)}"></div>
      <div class="trace-content">
        <div class="trace-header-row">
          <span class="trace-skill-name">${escHtml(skillName)}</span>
          <span class="status-pill ${escHtml(status)}">${escHtml(status)}</span>
          <span class="trace-duration">${escHtml(durationMs)}</span>
        </div>
        <div class="trace-time">${escHtml(startedAt)}</div>
        ${summary ? `<div class="trace-summary">${escHtml(summary)}</div>` : ''}
      </div>
    </div>
  `;
}

// ─── トレース選択 → LLM I/O ビューア ────────────────────
function selectTrace(traceId) {
  state.selectedTraceId = traceId;
  const trace = state.traces.find(t =>
    (t.trace_id || t.skill_name + '_' + t.started_at) === traceId
  );

  // 選択ハイライト更新
  els.timelineBody.querySelectorAll('.trace-item').forEach(el => {
    el.classList.toggle('selected', el.dataset.traceId === traceId);
  });

  if (!trace) {
    els.llmBody.innerHTML = '<div class="llm-empty">データなし</div>';
    return;
  }

  els.llmBody.innerHTML = buildLLMView(trace);
}

function buildLLMView(trace) {
  const parts = [];

  // メタ情報
  const model = trace.model || trace.llm_model || '—';
  const tokens = trace.token_count || trace.tokens || '—';
  const duration = trace.duration_ms != null
    ? `${trace.duration_ms}ms`
    : (trace.elapsed_seconds != null ? `${(trace.elapsed_seconds * 1000).toFixed(0)}ms` : '—');
  const status = trace.status || (trace.error ? 'error' : 'success');

  parts.push(`
    <div class="llm-meta">
      <div class="llm-meta-item">
        <div class="label">Skill</div>
        <div class="val">${escHtml(trace.skill_name || '—')}</div>
      </div>
      <div class="llm-meta-item">
        <div class="label">Status</div>
        <div class="val"><span class="status-pill ${escHtml(status)}">${escHtml(status)}</span></div>
      </div>
      <div class="llm-meta-item">
        <div class="label">Model</div>
        <div class="val model">${escHtml(model)}</div>
      </div>
      <div class="llm-meta-item">
        <div class="label">Duration</div>
        <div class="val">${escHtml(duration)}</div>
      </div>
      <div class="llm-meta-item">
        <div class="label">Tokens</div>
        <div class="val">${escHtml(String(tokens))}</div>
      </div>
      <div class="llm-meta-item">
        <div class="label">Time</div>
        <div class="val">${escHtml(formatTime(trace.started_at))}</div>
      </div>
    </div>
  `);

  // Input (prompt)
  if (trace.prompt || trace.input) {
    const content = trace.prompt || trace.input;
    parts.push(`
      <div class="llm-section">
        <div class="llm-section-title">Input / Prompt</div>
        <pre class="llm-code-block">${escHtml(toStr(content))}</pre>
      </div>
    `);
  }

  // Output
  if (trace.output) {
    parts.push(`
      <div class="llm-section">
        <div class="llm-section-title">Output</div>
        <pre class="llm-code-block">${escHtml(toStr(trace.output))}</pre>
      </div>
    `);
  }

  // Error
  if (trace.error) {
    parts.push(`
      <div class="llm-section">
        <div class="llm-section-title">Error</div>
        <pre class="llm-code-block" style="color:var(--accent-red)">${escHtml(toStr(trace.error))}</pre>
      </div>
    `);
  }

  // Raw JSON（折り畳み可能）
  parts.push(`
    <div class="llm-section">
      <div class="llm-section-title">Raw JSON</div>
      <pre class="llm-code-block">${escHtml(JSON.stringify(trace, null, 2))}</pre>
    </div>
  `);

  return parts.join('');
}

// ─── フッター: エラーチップ追加 ─────────────────────────
function addFooterError(trace) {
  if (els.footerEmpty) {
    els.footerEmpty.remove();
    // 参照を無効化
    els.footerEmpty = null;
  }

  const chip = document.createElement('div');
  chip.className = 'error-chip';
  chip.innerHTML = `
    <span class="err-time">${escHtml(formatTime(trace.started_at))}</span>
    <span>${escHtml(trace.skill_name || '?')}: ${escHtml((trace.error || 'error').slice(0, 60))}</span>
  `;
  els.footer.appendChild(chip);
}

// ─── REST ポーリング ──────────────────────────────────────
async function fetchInitialTraces() {
  try {
    const res = await fetch('/api/traces?limit=50');
    if (!res.ok) return;
    const data = await res.json();
    (data.traces || []).reverse().forEach(addTrace);
  } catch (_) { /* ネットワークエラーは無視 */ }
}

async function pollQdrant() {
  try {
    const res = await fetch('/api/qdrant/stats');
    if (!res.ok) return;
    const data = await res.json();
    renderQdrant(data);
  } catch (_) { /* 無視 */ }
}

async function pollScheduler() {
  try {
    const res = await fetch('/api/scheduler/states');
    if (!res.ok) return;
    const data = await res.json();
    renderScheduler(data);
  } catch (_) { /* 無視 */ }
}

// ─── Qdrant 描画 ─────────────────────────────────────────
function renderQdrant(data) {
  if (data.error) {
    els.qdrantBody.innerHTML = `<div class="empty-state" style="color:var(--accent-red)">${escHtml(data.error)}</div>`;
    els.statQdrant.textContent = 'ERROR';
    return;
  }

  const collections = data.collections || {};
  const names = Object.keys(collections);

  if (names.length === 0) {
    els.qdrantBody.innerHTML = '<div class="empty-state">コレクションなし</div>';
    els.statQdrant.textContent = '0';
    return;
  }

  let totalPoints = 0;
  const rows = names.map(name => {
    const col = collections[name];
    const count = col.points_count ?? col.vectors_count ?? '—';
    if (typeof count === 'number') totalPoints += count;
    return `
      <div class="qdrant-collection">
        <span class="collection-name">${escHtml(name)}</span>
        <span class="collection-count">${escHtml(String(count))} pts</span>
      </div>
    `;
  });

  els.qdrantBody.innerHTML = rows.join('');
  els.statQdrant.textContent = totalPoints;
}

// ─── スケジューラ描画 ─────────────────────────────────────
function renderScheduler(data) {
  const sources = data.sources || [];
  els.schedulerCount.textContent = sources.length;

  if (sources.length === 0) {
    els.schedulerBody.innerHTML = '<div class="empty-state">ソースなし</div>';
    return;
  }

  const rows = sources.map(src => {
    const dotClass = !src.enabled ? 'disabled'
      : src.consecutive_failures > 0 ? 'error'
      : 'enabled';

    const lastRun = src.last_run_at ? formatTime(src.last_run_at) : '未実行';
    const interval = src.interval_min ? `${src.interval_min}m` : '—';

    return `
      <div class="source-row">
        <div class="source-dot ${escHtml(dotClass)}"></div>
        <span class="source-name">${escHtml(src.source_id || '?')}</span>
        <span class="source-interval">${escHtml(interval)}</span>
        <span class="source-last-run">${escHtml(lastRun)}</span>
      </div>
    `;
  });

  els.schedulerBody.innerHTML = rows.join('');
}

// ─── ユーティリティ ───────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function toStr(val) {
  if (typeof val === 'string') return val;
  return JSON.stringify(val, null, 2);
}

function formatTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch (_) {
    return String(iso);
  }
}

// ─── 初期化 ──────────────────────────────────────────────
(async function init() {
  // SSE 接続
  connectSSE();

  // 既存トレースを取得
  await fetchInitialTraces();

  // Qdrant・スケジューラの初期ポーリング
  await Promise.all([pollQdrant(), pollScheduler()]);

  // 30秒ごとに定期ポーリング
  setInterval(() => {
    pollQdrant();
    pollScheduler();
  }, 30_000);
})();
