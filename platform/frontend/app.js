/* Core shell: session, live event stream, inspector, source viewer, routing.
   No system behaviour is modelled here. Everything displayed arrives from the
   backend adapters, which arrive from the source systems. */

import { INSTRUMENTS } from './instruments.js';

export const SESSION =
  new URLSearchParams(location.search).get('session') || 'default';
export const ACCENT = {
  syber_runtime: 'var(--sys-runtime)',
  barn: 'var(--sys-barn)',
  bough: 'var(--sys-bough)',
  osahr: 'var(--sys-osahr)',
  relay: 'var(--sys-relay)',
  cross: 'var(--live)',
};

const state = {
  systems: [],
  events: [],
  filter: null,
  active: null,
  liveInference: false,
};

/* ----------------------------------------------------------------- api */

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { 'content-type': 'application/json', 'x-syber-session': SESSION },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const err = new Error(data?.message || data?.detail || `HTTP ${res.status}`);
    err.status = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

/* ------------------------------------------------------------- helpers */

export const el = (tag, attrs = {}, ...kids) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'style') node.setAttribute('style', v);
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
};

export const short = (s, n = 10) => (typeof s === 'string' && s.length > n ? s.slice(0, n) : s ?? '');
export const num = (v, d = 4) =>
  typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(d)) : String(v ?? '—');

export function jsonBlock(value) {
  const text = JSON.stringify(value, null, 2) ?? 'null';
  const html = text
    .replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
    .replace(/"([^"\\]*(\\.[^"\\]*)*)":/g, '<span class="k">"$1"</span>:')
    .replace(/: "([^"\\]*(\\.[^"\\]*)*)"/g, ': <span class="s">"$1"</span>')
    .replace(/: (-?\d+\.?\d*(e[-+]?\d+)?)/gi, ': <span class="n">$1</span>')
    .replace(/: (true|false|null)/g, ': <span class="b">$1</span>');
  return el('pre', { class: 'json', html });
}

export function panel(title, bodyNode, { actions = [], flush = false } = {}) {
  const head = el('header', {}, el('h3', {}, title), el('span', { class: 'spacer' }), ...actions);
  return el('div', { class: 'panel' }, head, el('div', { class: `body${flush ? ' flush' : ''}` }, bodyNode));
}

export function kv(pairs) {
  const dl = el('dl', { class: 'kv' });
  for (const [k, v] of pairs) {
    if (v === undefined) continue;
    dl.append(el('dt', {}, k), el('dd', {}, v instanceof Node ? v : String(v ?? '—')));
  }
  return dl;
}

export function notice(kind, title, detail) {
  return el('div', { class: `notice ${kind}` }, el('b', {}, title),
    detail ? el('span', { class: 'code' }, detail) : null);
}

/* Render a refusal from a source system exactly as the system reported it. */
export function refusalNotice(err) {
  const p = err?.payload;
  if (p?.refused) {
    const box = el('div', { class: 'notice refused' },
      el('b', {}, `${p.system} refused: ${p.code || p.kind}`),
      el('span', { class: 'code' }, p.message));
    if (p.provenance?.module) {
      box.append(el('button', {
        class: 'src-link refusal-src',
        onclick: () => showSource(p.provenance),
      }, `${p.provenance.module}${p.provenance.line ? ':' + p.provenance.line : ''} →`));
    }
    return box;
  }
  if (p?.unavailable) {
    return notice('error', `${p.system} unavailable`, p.message);
  }
  return notice('error', err?.message || 'Request failed', p ? JSON.stringify(p).slice(0, 400) : null);
}

/* ------------------------------------------------------------ inspector */

const drawer = document.getElementById('drawer');
const drawerTitle = document.getElementById('drawer-title');
const drawerContent = document.getElementById('drawer-content');
document.getElementById('drawer-close').addEventListener('click', closeDrawer);
drawer.addEventListener('click', (e) => { if (e.target === drawer) closeDrawer(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

export function openDrawer(title, node) {
  drawerTitle.textContent = title;
  drawerContent.replaceChildren(node);
  drawer.classList.add('open');
}
export function closeDrawer() { drawer.classList.remove('open'); }

function section(title, node) {
  return el('div', { class: 'insp-section' }, el('h4', {}, title), node);
}

export function provenanceBlock(prov) {
  if (!prov) return el('div', { class: 'faint' }, 'no provenance recorded');
  const box = el('div', { class: 'prov' });
  const line = (k, v) => el('div', { class: 'line' }, el('span', { class: 'k' }, k), el('span', {}, v ?? '—'));
  box.append(line('system', prov.system));
  if (prov.module) box.append(line('module', prov.module + (prov.line ? `:${prov.line}` : '')));
  if (prov.symbol) box.append(line('symbol', prov.symbol));
  box.append(line('execution', prov.execution));
  if (prov.node) box.append(line('runtime', prov.node));
  if (prov.module && prov.repo_relative !== false && prov.module !== '(external)') {
    box.append(el('button', { class: 'src-link', onclick: () => showSource(prov) },
      'open the source that ran →'));
  }
  return box;
}

export async function showSource(prov) {
  try {
    const data = await api(`/api/source?system=${encodeURIComponent(prov.system)}&path=${encodeURIComponent(prov.module)}`);
    const wrap = el('div', { class: 'src' });
    const table = el('table');
    const focus = prov.line || 0;
    data.lines.forEach((text, i) => {
      const n = i + 1;
      const hit = focus && n >= focus && n < focus + 1;
      table.append(el('tr', { class: hit ? 'hit' : '' },
        el('td', { class: 'ln' }, String(n)),
        el('td', { class: 'code' }, text || ' ')));
    });
    wrap.append(table);
    openDrawer(`${prov.system} · ${prov.module}`, el('div', {},
      section('Source', wrap),
      el('div', { class: 'faint mono', style: 'margin-top:8px;font-size:10.5px' },
        `${data.bytes} bytes · served from the ${prov.system} checkout`)));
    requestAnimationFrame(() => {
      const hit = wrap.querySelector('tr.hit');
      if (hit) hit.scrollIntoView({ block: 'center' });
    });
  } catch (err) {
    openDrawer('Source unavailable', refusalNotice(err));
  }
}

function inspectEvent(ev) {
  const body = el('div', {});
  body.append(section('Event', kv([
    ['system', ev.system],
    ['type', ev.eventType],
    ['status', el('span', { class: `tag ${ev.status}` }, ev.status)],
    ['seq', String(ev.seq)],
    ['timestamp', ev.timestamp],
    ['duration', ev.durationMs !== null && ev.durationMs !== undefined ? `${ev.durationMs} ms` : '—'],
  ])));
  body.append(section('Provenance — what actually ran', provenanceBlock(ev.provenance)));
  if (ev.error) body.append(section('Refusal / error', jsonBlock(ev.error)));
  if (ev.input !== null && ev.input !== undefined) body.append(section('Input', jsonBlock(ev.input)));
  if (ev.stateBefore !== null && ev.stateBefore !== undefined) body.append(section('State before', jsonBlock(ev.stateBefore)));
  if (ev.stateAfter !== null && ev.stateAfter !== undefined) body.append(section('State after', jsonBlock(ev.stateAfter)));
  if (ev.evidence !== null && ev.evidence !== undefined) body.append(section('Evidence', jsonBlock(ev.evidence)));
  if (ev.output !== null && ev.output !== undefined) body.append(section('Output', jsonBlock(ev.output)));
  if (ev.metadata && Object.keys(ev.metadata).length) body.append(section('Metadata', jsonBlock(ev.metadata)));
  openDrawer(`${ev.system} · ${ev.label || ev.eventType}`, body);
}

/* --------------------------------------------------------------- stream */

const streamList = document.getElementById('stream-list');
const pulse = document.getElementById('pulse');
const footEvents = document.getElementById('foot-events');
const clearFilterBtn = document.getElementById('clear-filter');

clearFilterBtn.addEventListener('click', () => { state.filter = null; renderStream(); });

function eventRow(ev) {
  const row = el('div', {
    class: `ev ${ev.status}`,
    style: `--sys:${ACCENT[ev.system] || 'var(--live)'}`,
    onclick: () => inspectEvent(ev),
  });
  row.append(el('div', { class: 'top' },
    el('span', { class: 'sys' }, ev.system),
    ev.status !== 'ok' ? el('span', { class: `tag ${ev.status}` }, ev.status) : null,
    el('span', { class: 'seq' }, `#${ev.seq}`)));
  row.append(el('div', { class: 'label' }, ev.label || ev.eventType));
  const prov = ev.provenance;
  row.append(el('div', { class: 'meta' },
    prov?.module ? `${prov.module}${prov.line ? ':' + prov.line : ''}` : ev.eventType,
    ev.durationMs !== null && ev.durationMs !== undefined ? `  ·  ${ev.durationMs}ms` : ''));
  return row;
}

/* Events are grouped by the action that caused them — one HTTP request, or one
   scenario step — using the operationId the backend attributes at the edge.
   Collapsed groups remember their state across re-renders. */
const collapsed = new Set();

function renderStream() {
  const shown = state.filter ? state.events.filter((e) => e.system === state.filter) : state.events;
  clearFilterBtn.style.display = state.filter ? '' : 'none';
  if (!shown.length) {
    streamList.replaceChildren(el('div', { class: 'empty' },
      state.filter ? `No ${state.filter} events yet.` : 'No events yet. Run something.'));
    return;
  }

  // Preserve arrival order, then group contiguous runs of one operation.
  const groups = [];
  for (const ev of shown) {
    const key = ev.operationId || `solo:${ev.seq}`;
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.events.push(ev);
    else groups.push({ key, events: [ev], action: ev.actionLabel, kind: ev.actionKind, parent: ev.parentId });
  }

  streamList.replaceChildren(...groups.reverse().map(groupRow));
}

function groupRow(g) {
  // A single ungrouped event still reads as one row, without chrome.
  if (!g.action) return eventRow(g.events[0]);

  const isCollapsed = collapsed.has(g.key);
  const worst = g.events.some((e) => e.status === 'error') ? 'error'
    : g.events.some((e) => e.status === 'refused') ? 'refused' : 'ok';

  const node = el('div', { class: `ev-group${isCollapsed ? ' collapsed' : ''}` });
  const head = el('div', {
    class: 'ev-group-head',
    onclick: () => {
      if (collapsed.has(g.key)) collapsed.delete(g.key); else collapsed.add(g.key);
      node.classList.toggle('collapsed');
    },
  },
    el('span', { class: 'caret' }, '▾'),
    g.kind === 'scenario_step' ? el('span', { class: 'scn-badge' }, 'step') : null,
    el('span', { class: 'action' }, g.action),
    worst !== 'ok' ? el('span', { class: `tag ${worst}` }, worst) : null,
    el('span', { class: 'n' }, `${g.events.length}`));

  node.append(head, el('div', { class: 'ev-list' },
    ...g.events.slice().reverse().map(eventRow)));
  return node;
}

function pushEvent(ev) {
  state.events.push(ev);
  if (state.events.length > 1200) state.events.splice(0, state.events.length - 1200);
  footEvents.textContent = state.events.length;
  pulse.classList.remove('beat');
  void pulse.offsetWidth;
  pulse.classList.add('beat');
  renderStream();
}

export function filterStream(system) { state.filter = system; renderStream(); }

function connectStream() {
  const es = new EventSource(`/api/events/stream?session=${SESSION}`);
  es.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === 'connected') return;
    pushEvent(data);
  };
  es.onerror = () => { pulse.style.background = 'var(--refused)'; };
  es.onopen = () => { pulse.style.background = 'var(--ok)'; };
}

/* ----------------------------------------------------------------- rail */

const stage = document.getElementById('stage');

function renderRail() {
  const list = document.getElementById('instrument-list');
  list.replaceChildren(...state.systems.map((sys) => {
    const inst = INSTRUMENTS[sys.id];
    const btn = el('button', {
      class: `instrument${sys.available ? '' : ' down'}${state.active === sys.id ? ' active' : ''}`,
      style: `--accent:${ACCENT[sys.id]}`,
      onclick: () => select(sys.id),
    },
      el('div', { class: 'name' }, el('span', { class: 'dot' }), sys.name),
      el('div', { class: 'prim' }, sys.available ? sys.primitive : 'unavailable'));
    return btn;
  }));
  list.prepend(seamButton('builder', 'Solution Builder', 'compose typed capabilities'));

  const seams = document.getElementById('seam-list');
  seams.replaceChildren(
    seamButton('cross-relay-runtime', 'Relay → SyberRuntime', 'draft becomes an obligation'),
    seamButton('cross-barn-bough', 'Barn → Bough', 'heuristic vs optimal action'),
    seamButton('cross-bough-osahr', 'Bough → OSAHR', 'exact vs kernel schedulers'),
    seamButton('about', 'Fidelity', 'what is real, and how'),
  );
}

function seamButton(id, name, prim) {
  return el('button', {
    class: `instrument${state.active === id ? ' active' : ''}`,
    style: '--accent:var(--live)',
    onclick: () => select(id),
  }, el('div', { class: 'name' }, el('span', { class: 'dot' }), name), el('div', { class: 'prim' }, prim));
}

async function select(id) {
  state.active = id;
  renderRail();
  const inst = INSTRUMENTS[id];
  stage.replaceChildren(el('div', { class: 'stage-head' }, el('h2', {}, el('span', { class: 'spin' }))));
  if (!inst) {
    stage.replaceChildren(el('div', { class: 'stage-head' }, el('h2', {}, 'Not found')));
    return;
  }
  const sys = state.systems.find((s) => s.id === id);
  try {
    const node = await inst.render({ sys, state, api, filterStream });
    stage.replaceChildren(node);
    stage.scrollTop = 0;
  } catch (err) {
    stage.replaceChildren(el('div', { class: 'stage-body' }, refusalNotice(err)));
  }
}

export function reselect() { if (state.active) select(state.active); }
export function goto(id) { select(id); }

/* ----------------------------------------------------------------- boot */

async function boot() {
  const info = await api('/api/systems');
  state.systems = info.systems;
  state.liveInference = info.liveInference;
  document.getElementById('foot-session').textContent = info.sessionId;
  document.getElementById('foot-inference').textContent = info.liveInference ? 'available' : 'no key';
  renderRail();
  connectStream();
  const prior = await api('/api/events');
  prior.events.forEach(pushEvent);
  select('builder');
}

boot().catch((err) => {
  stage.replaceChildren(el('div', { class: 'stage-body' },
    notice('error', 'Platform failed to start', err.message)));
});
