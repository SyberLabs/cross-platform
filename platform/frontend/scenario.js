/* Guided scenarios.

   The runner streams from the backend, which is executing the real adapter
   calls as it goes. Nothing here decides an outcome; it renders what each step
   actually did, including when a step did something the scenario did not
   predict. */

import {
  el, jsonBlock, notice, openDrawer, showSource, SESSION,
} from './app.js';

let catalog = null;

export async function scenariosFor(systemId) {
  if (catalog === null) {
    const r = await fetch(`/api/scenarios?session=${SESSION}`, {
      headers: { 'x-syber-session': SESSION },
    });
    catalog = (await r.json()).scenarios;
  }
  return catalog.filter((s) => s.system === systemId);
}

/** The strip that sits at the top of an instrument. */
export function scenarioStrip(list, onRun) {
  if (!list.length) return null;

  // Pacing is a reading-speed choice, so it belongs to the viewer.
  const pace = el('select', { class: 'scn-pace' },
    el('option', { value: 'slow', selected: true }, 'Slow'),
    el('option', { value: 'normal' }, 'Normal'),
    el('option', { value: 'fast' }, 'Fast'));

  return el('div', { class: 'scn-strip' },
    el('span', { class: 'scn-strip-label' }, 'Guided'),
    ...list.map((sc) => el('button', {
      class: `act scn-launch${sc.available ? '' : ' unavailable'}`,
      disabled: !sc.available,
      title: sc.available ? sc.thesis : 'This scenario needs a system that is not available.',
      onclick: () => onRun(sc, pace.value),
    }, el('span', { class: 'scn-play' }, '▶'), sc.title,
      el('span', { class: 'scn-count' }, `${sc.stepCount} steps`))),
    el('span', { class: 'scn-pace-wrap' }, el('span', { class: 'scn-pace-label' }, 'Pace'), pace),
    el('span', { class: 'scn-hint' },
      'runs the real systems — nothing here is a recording'));
}

/* ------------------------------------------------------------ value rendering */

const HEX = /^[0-9a-f]{12,}$/i;
const PREFIXED_ID = /^(run|agent|work|artifact|cmd|scn|req)_[0-9a-f]{6,}$/i;

/** Render one value according to what it is, so the meaningful part reads first. */
function value(v) {
  if (v === null || v === undefined) return el('span', { class: 'none' }, 'none');

  if (typeof v === 'boolean') {
    return el('span', { class: v ? 'b-true' : 'b-false' }, v ? '✓ true' : '✗ false');
  }
  if (typeof v === 'number') {
    return el('span', { class: 'n' }, Number.isInteger(v) ? String(v) : v.toFixed(6).replace(/0+$/, ''));
  }
  if (Array.isArray(v)) {
    if (!v.length) return el('span', { class: 'none' }, 'none');
    return el('ul', {}, ...v.map((x) => el('li', {},
      typeof x === 'object' && x !== null ? compactObject(x) : String(x))));
  }
  if (typeof v === 'object') return compactObject(v);

  const text = String(v);
  // Identifiers and digests are context, not content: keep them legible but quiet.
  if (HEX.test(text.replace(/…$/, '')) || PREFIXED_ID.test(text)) {
    return el('span', { class: 'id' }, text);
  }
  return document.createTextNode(text);
}

function compactObject(o) {
  return el('span', {}, Object.entries(o)
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join('  ·  '));
}

function resultGrid(result, skipKey) {
  const entries = Object.entries(result).filter(([k]) => k !== skipKey);
  if (!entries.length) return null;
  const box = el('div', { class: 'scn-kv' });
  for (const [k, v] of entries) {
    box.append(el('span', { class: 'scn-k' }, k), el('span', { class: 'scn-v' }, value(v)));
  }
  return box;
}

/* `requiresVerification` uppercased is unreadable as REQUIRESVERIFICATION. */
function labelize(key) {
  return key.replace(/([a-z0-9])([A-Z])/g, '$1 $2');
}

/** The one value that carries the step's meaning, if the scenario named one. */
function headline(result, key) {
  if (!key || !(key in result)) return null;
  const v = result[key];
  const text = typeof v === 'boolean' ? (v ? 'true' : 'false')
    : typeof v === 'number' ? (Number.isInteger(v) ? String(v) : String(v))
      : Array.isArray(v) ? `${v.length}` : String(v);
  return el('div', { class: 'scn-headline' },
    el('span', { class: 'k' }, labelize(key)),
    el('span', { class: 'v' }, text));
}

/* ------------------------------------------------------------------ the run */

export function scenarioRun(sc, { onFinish, pace = 'slow' } = {}) {
  const total = sc.steps.length;
  const progressText = el('span', { class: 'scn-progress-text' }, `0 / ${total}`);
  const bar = el('span', { style: 'width:0%' });

  const head = el('div', { class: 'scn-head' },
    el('div', { class: 'scn-head-top' },
      el('h3', {}, sc.title),
      progressText),
    el('div', { class: 'scn-bar' }, bar),
    el('p', { class: 'scn-thesis' }, sc.thesis));

  const steps = el('div', { class: 'scn-steps' });
  const foot = el('div', { class: 'scn-foot' });

  const stepNodes = sc.steps.map((st, i) => {
    const node = el('div', { class: 'scn-step pending' },
      el('div', { class: 'scn-num' }, String(i + 1)),
      el('div', { class: 'scn-body' },
        el('div', { class: 'scn-title' },
          el('span', { class: 'scn-step-n' }, String(i + 1).padStart(2, '0')),
          st.title,
          st.expect === 'refused' ? el('span', { class: 'tag refused' }, 'expects refusal') : null),
        el('div', { class: 'scn-explain' },
          el('div', { class: 'scn-pane plain' },
            el('div', { class: 'scn-pane-label' }, 'In plain terms'),
            el('div', { class: 'scn-pane-text' }, '')),
          el('div', { class: 'scn-pane tech' },
            el('div', { class: 'scn-pane-label' }, 'What actually ran'),
            el('div', { class: 'scn-pane-text' }, ''))),
        el('div', { class: 'scn-result' })));
    steps.append(node);
    return node;
  });

  const wrap = el('div', { class: 'scn-run' }, head, steps, foot);
  let unexpected = 0;
  let done = 0;

  const src = new EventSource(
    `/api/scenarios/${sc.id}/run?session=${SESSION}&pace=${pace}`);

  src.onmessage = (msg) => {
    const m = JSON.parse(msg.data);

    if (m.type === 'step_start') {
      const node = stepNodes[m.index];
      node.className = 'scn-step running';
      node.querySelector('.plain .scn-pane-text').textContent = m.plain;
      node.querySelector('.tech .scn-pane-text').textContent = m.technical;
      node.querySelector('.scn-num').textContent = '';
      node.querySelector('.scn-num').append(el('span', { class: 'spin' }));
      node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      return;
    }

    if (m.type === 'step_end') {
      const node = stepNodes[m.index];
      const result = node.querySelector('.scn-result');
      const refused = m.outcome === 'refused';
      const state = m.matched ? (refused ? 'refused' : 'ok') : 'unexpected';
      node.className = `scn-step done ${state}`;

      const glyph = { ok: '✓', refused: '⊘', unexpected: '✕' }[state];
      node.querySelector('.scn-num').textContent = glyph;

      done += 1;
      progressText.textContent = `${done} / ${total}`;
      bar.style.width = `${(done / total) * 100}%`;

      if (!m.matched) {
        unexpected += 1;
        result.append(notice('error', 'Not what the scenario predicted', m.verdict));
      }

      if (refused) {
        const r = m.refusal || {};
        const box = el('div', { class: 'notice refused' },
          el('b', {}, `${r.system} refused — ${r.code || r.kind}`),
          r.message && r.message !== (r.code || '')
            ? el('span', { class: 'code' }, r.message) : null);
        if (r.provenance?.module) {
          box.append(el('button', {
            class: 'src-link refusal-src',
            onclick: () => showSource(r.provenance),
          }, `${r.provenance.module}${r.provenance.line ? ':' + r.provenance.line : ''} →`));
        }
        result.append(box);
      } else if (m.outcome === 'error') {
        result.append(notice('error', m.error?.type || 'Failed', m.error?.message));
      } else if (m.result && Object.keys(m.result).length) {
        const hl = headline(m.result, m.headline);
        if (hl) result.append(hl);
        const grid = resultGrid(m.result, m.headline);
        if (grid) result.append(grid);
      }

      if (m.note) result.append(el('div', { class: 'scn-note' }, m.note));
      return;
    }

    if (m.type === 'aborted') {
      foot.append(notice('error', 'Scenario stopped', m.reason));
      src.close(); finish(); return;
    }
    if (m.type === 'failed') {
      foot.append(notice('error', 'Scenario failed to run', m.error));
      src.close(); finish(); return;
    }
    if (m.type === 'end') {
      src.close();
      foot.append(unexpected
        ? notice('error', `${unexpected} step(s) did not match the scenario`,
          'The systems did what they did; the narration above is what was predicted. '
          + 'A mismatch means the scenario is out of date, not that the result was faked.')
        : notice('ok', 'Every step behaved as the scenario said it would',
          'Each refusal above came from the source system, not from this page.'));
      finish();
    }
  };

  src.onerror = () => {
    src.close();
    foot.append(notice('error', 'Lost the scenario stream', 'The run may not have completed.'));
    finish();
  };

  function finish() {
    // Mark anything never reached, so a stopped run does not look complete.
    for (const node of stepNodes) {
      if (node.classList.contains('pending') || node.classList.contains('running')) {
        node.className = 'scn-step pending';
        node.querySelector('.scn-num').textContent = '·';
      }
    }
    foot.append(el('div', { class: 'btn-row' },
      el('button', { class: 'act primary', onclick: () => onFinish?.() },
        'Show me the resulting state →'),
      el('button', { class: 'act', onclick: () => openDrawer('Scenario definition', jsonBlock(sc)) },
        'Inspect the scenario definition')));
  }

  return wrap;
}
