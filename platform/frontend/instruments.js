/* One instrument per system, shaped by that system's own primitive.
   Nothing here computes a system's answer; every value rendered arrived from
   an adapter call whose provenance is attached to the event it emitted. */

import {
  ACCENT, api, el, jsonBlock, kv, notice, num, openDrawer, panel,
  provenanceBlock, refusalNotice, short, filterStream,
} from './app.js';
import { scenariosFor, scenarioStrip, scenarioRun } from './scenario.js';
import { networkView, timeline, statsView, eventFeed } from './osahr6g.js';
import { SESSION as SESSION_ID } from './app.js';

function head({ id, title, badge, lede, origin }) {
  return el('div', { class: 'stage-head', style: `--accent:${ACCENT[id] || 'var(--live)'}` },
    el('h2', {}, title, badge ? el('span', { class: 'badge' }, badge) : null),
    lede ? el('p', { class: 'lede' }, lede) : null,
    origin ? el('div', { class: 'origin', html: origin }) : null);
}

function stage(id, headNode, ...panels) {
  return stageScoped(id, id, headNode, ...panels);
}

/* `scope` selects which scenarios belong to this page. Pages that are reference
   material rather than instruments pass null and get no guided strip. */
function stageScoped(id, scope, headNode, ...panels) {
  const body = el('div', { class: 'stage-body' }, ...panels);
  const root = el('main', { class: 'stage-inner', style: `--accent:${ACCENT[id] || 'var(--live)'}` },
    headNode, body);

  // The guided strip is resolved asynchronously and inserted above the
  // instrument's own controls, so the instrument renders immediately either way.
  if (scope === null) return root;

  scenariosFor(scope).then((list) => {
    const strip = scenarioStrip(list, (sc, pace) => {
      body.replaceChildren(scenarioRun(sc, {
        pace,
        onFinish: () => import('./app.js').then((m) => m.reselect()),
      }));
      root.scrollIntoView({ block: 'start' });
    });
    if (strip) body.prepend(strip);
  }).catch(() => { /* scenarios are an aid; their absence must not break an instrument */ });

  return root;
}

const out = (node) => el('div', { id: 'out', style: 'margin-top:12px' }, node);
function say(host, node) { host.replaceChildren(node); }

/* A notice raised by an action must survive the re-render that action triggers,
   otherwise the user sees the state change but never the reason for it. */
let pending = null;
function reloadWith(node) {
  pending = node;
  import('./app.js').then((m) => m.reselect());
}
function resultHost() {
  const host = el('div');
  if (pending) { host.append(pending); pending = null; }
  return host;
}

/* =================================================================
   SyberRuntime — operation ledger, debt ledger, evidence
   ================================================================= */

async function runtimeInstrument() {
  const data = await api('/api/runtime/state');
  const st = data.state;
  const result = resultHost();

  const threads = Object.keys(st.threads || {});
  const artifacts = Object.entries(st.artifacts || {});
  const obligations = Object.entries(st.debt.obligations || {});

  // -- controls
  const intent = el('input', { type: 'text', value: 'Add a billing guard', placeholder: 'intent' });
  const threadSel = el('select', {}, ...threads.map((t) => el('option', { value: t }, short(t, 16) + '…')));
  const artName = el('input', { type: 'text', value: 'billing.py' });
  const content = el('textarea', {}, 'def charge(amount_cents):\n    if amount_cents <= 0:\n        raise ValueError("amount must be positive")\n    return amount_cents\n');
  const gm = el('input', { type: 'number', value: '2', step: '0.5', min: '0' });
  const br = el('input', { type: 'number', value: '1.5', step: '0.5', min: '0' });
  const cr = el('input', { type: 'number', value: '1', step: '0.5', min: '0' });
  const profile = el('select', {},
    ...['exploratory', 'production', 'research-grade', 'safety-critical'].map((p) =>
      el('option', { value: p, selected: p === st.policy.profile }, p)));
  const maxDebt = el('input', { type: 'number', value: String(st.policy.maxDebt), step: '1' });

  const controls = el('div', {},
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'rigor profile'), profile),
      el('div', { class: 'field' }, el('label', {}, 'center debt budget'), maxDebt),
      el('button', {
        class: 'act', onclick: async () => {
          const r = await api('/api/runtime/policy', {
            method: 'POST', body: { profile: profile.value, maxDebt: Number(maxDebt.value) },
          });
          say(result, notice('ok', `policy → ${r.profile}`,
            `accrual ${r.accrualRate} · floor obligations ${r.floorRequired ? 'required' : 'not required'} · budget ${r.maxDebt}`));
        },
      }, 'Apply policy')),
    el('div', { style: 'height:12px' }),
    el('div', { class: 'field' }, el('label', {}, 'thread intent'), intent),
    el('div', { class: 'btn-row' },
      el('button', {
        class: 'act', onclick: async () => {
          await api('/api/runtime/thread', { method: 'POST', body: { intent: intent.value } });
          reload();
        },
      }, 'Open thread')),
    el('hr', { style: 'border:0;border-top:1px solid var(--rule);margin:16px 0' }),
    threads.length
      ? el('div', {},
        el('div', { class: 'row' },
          el('div', { class: 'field' }, el('label', {}, 'thread'), threadSel),
          el('div', { class: 'field' }, el('label', {}, 'artifact name'), artName)),
        el('div', { style: 'height:10px' }),
        el('div', { class: 'field' }, el('label', {}, 'artifact content'), content),
        el('div', { class: 'row' },
          el('div', { class: 'field' }, el('label', {}, 'generative mass'), gm),
          el('div', { class: 'field' }, el('label', {}, 'blast radius'), br),
          el('div', { class: 'field' }, el('label', {}, 'criticality'), cr)),
        el('div', { class: 'faint mono', style: 'margin-top:6px;font-size:10.5px' },
          'debt = mass × radius × criticality × accrual rate'),
        el('div', { class: 'btn-row' },
          el('button', {
            class: 'act primary', onclick: async () => {
              try {
                const r = await api('/api/runtime/feature', {
                  method: 'POST',
                  body: {
                    threadId: threadSel.value, artifactName: artName.value, content: content.value,
                    intent: intent.value, generativeMass: Number(gm.value),
                    blastRadius: Number(br.value), criticality: Number(cr.value),
                  },
                });
                reloadWith(notice('ok', 'Feature recorded — verification debt accrued',
                  `total residual debt is now ${r.state.debt.totalResidual}`));
              } catch (e) { say(result, refusalNotice(e)); }
            },
          }, 'Record Feature')))
      : el('div', { class: 'empty' }, 'Open a thread first.'));

  // -- debt ledger
  const debtTable = el('table', { class: 'data' },
    el('thead', {}, el('tr', {},
      el('th', {}, 'obligation'), el('th', {}, 'artifact'), el('th', {}, 'status'),
      el('th', {}, 'floor'), el('th', {}, 'incurred'), el('th', {}, 'residual'))),
    el('tbody', {}, ...(obligations.length
      ? obligations.map(([oid, ob]) => el('tr', { class: 'clickable', onclick: () => openDrawer('Obligation', jsonBlock(ob)) },
        el('td', {}, short(oid, 12)),
        el('td', {}, short(ob.artifact_digest, 12)),
        el('td', {}, el('span', { class: `tag ${ob.status === 'open' ? 'refused' : 'ok'}` }, ob.status)),
        el('td', {}, ob.floor_required ? 'required' : '—'),
        el('td', { class: 'num faint' }, num(ob.incurred_debt ?? 0, 2)),
        el('td', { class: 'num' }, num(ob.residual_debt ?? 0, 2))))
      : [el('tr', {}, el('td', { colspan: '6', class: 'empty' }, 'No obligations. Nothing is owed.'))])));

  // -- artifacts + verify/stabilize
  const artTable = el('table', { class: 'data' },
    el('thead', {}, el('tr', {},
      el('th', {}, 'artifact'), el('th', {}, 'digest'), el('th', {}, 'open floor'), el('th', {}, ''))),
    el('tbody', {}, ...(artifacts.length
      ? artifacts.map(([dig, a]) => {
        const openFloor = obligations.filter(([, ob]) =>
          ob.artifact_digest === dig && ob.status === 'open' && ob.floor_required).length;
        const expected = el('input', { type: 'text', value: 'raise ValueError', style: 'width:150px' });
        return el('tr', {},
          el('td', {}, a.ref?.name || '—'),
          el('td', { class: 'clickable', onclick: async () => {
            const t = await api(`/api/runtime/artifact/${dig}`);
            openDrawer('Artifact', el('pre', { class: 'json' }, t.text));
          } }, short(dig, 14)),
          el('td', {}, openFloor
            ? el('span', { class: 'tag refused' }, `${openFloor} open`)
            : el('span', { class: 'tag ok' }, 'clear')),
          el('td', {}, el('div', { style: 'display:flex;gap:6px;align-items:center;flex-wrap:wrap' },
            expected,
            el('button', {
              class: 'act', onclick: async () => {
                try {
                  const r = await api('/api/runtime/test', {
                    method: 'POST',
                    body: {
                      threadId: a.thread_id || threadSel.value, artifactDigest: dig,
                      check: { kind: 'text_contains', expected: expected.value },
                    },
                  });
                  const v = r.verification;
                  reloadWith(notice(v.passed ? 'ok' : 'refused',
                    `Deterministic check ${v.passed ? 'passed' : 'failed'} — ${v.kind}`,
                    `${v.details} · discharged ${v.discharged_obligations.length} obligation(s)`));
                } catch (e) { say(result, refusalNotice(e)); }
              },
            }, 'Verify'),
            el('button', {
              class: 'act', onclick: async () => {
                try {
                  const r = await api('/api/runtime/stabilize', {
                    method: 'POST',
                    body: { threadId: a.thread_id || threadSel.value, artifactDigest: dig },
                  });
                  reloadWith(notice('ok', 'Stabilized — projection committed',
                    `residual debt ${r.state.debt.totalResidual}`));
                } catch (e) { say(result, refusalNotice(e)); }
              },
            }, 'Stabilize'))));
      })
      : [el('tr', {}, el('td', { colspan: '4', class: 'empty' }, 'No artifacts yet.'))])));

  // -- operation log (hash chain)
  const logTable = el('table', { class: 'data' },
    el('thead', {}, el('tr', {},
      el('th', {}, '#'), el('th', {}, 'verb'), el('th', {}, 'entry hash'),
      el('th', {}, 'prev'), el('th', {}, 'evaluation'))),
    el('tbody', {}, ...(data.log.length
      ? data.log.map((e, i) => el('tr', {
        class: 'clickable',
        onclick: () => openDrawer(`Operation ${e.operation.type}`, jsonBlock(e)),
      },
        el('td', { class: 'num faint' }, String(i)),
        el('td', {}, el('span', { class: 'tag' }, e.operation.type)),
        el('td', {}, short(e.entryHash, 14)),
        el('td', { class: 'faint' }, e.prevHash ? short(e.prevHash, 10) : 'genesis'),
        el('td', { class: 'dim' }, e.operation.evaluation.status)))
      : [el('tr', {}, el('td', { colspan: '5', class: 'empty' }, 'Log is empty.'))])));

  // -- evidence actions
  const evOut = el('div', { style: 'margin-top:12px' });
  const evidence = el('div', {},
    el('div', { class: 'btn-row', style: 'margin-top:0' },
      ...[
        ['merkle-root', 'Merkle root'],
        ['replay-check', 'Replay determinism'],
        ['chain-verify', 'Verify hash chain'],
        ['metrics', 'Runtime metrics'],
        ['export-prov', 'W3C PROV export'],
      ].map(([kind, label]) => el('button', {
        class: 'act', onclick: async () => {
          try {
            const r = await api(`/api/runtime/evidence/${kind}`, { method: 'POST', body: {} });
            evOut.replaceChildren(jsonBlock(r));
          } catch (e) { evOut.replaceChildren(refusalNotice(e)); }
        },
      }, label))),
    evOut);

  // -- acceptance gate (subprocess against the repo)
  const accOut = el('div', { style: 'margin-top:12px' });
  const acceptance = el('div', {},
    el('p', { class: 'dim', style: 'margin:0 0 10px' },
      'SyberRuntime audits its own release readiness against an evidence corpus. '
      + 'On a fresh clone that corpus is absent — the criteria live in gitignored run '
      + 'directories — so the gate fails closed and names every missing criterion. '
      + 'This runs the repository CLI as a subprocess and reports what it printed.'),
    el('button', {
      class: 'act', onclick: async () => {
        accOut.replaceChildren(el('span', { class: 'spin' }));
        try {
          const r = await api('/api/runtime/acceptance', { method: 'POST', body: {} });
          if (!r.ok) { accOut.replaceChildren(jsonBlock(r)); return; }
          const rep = r.report;
          const rows = (rep.criteria || []).map((c) => el('tr', {
            class: 'clickable', onclick: () => openDrawer('Criterion', jsonBlock(c)),
          },
            el('td', {}, el('span', { class: `tag ${c.status === 'pass' ? 'ok' : c.status === 'warn' ? 'refused' : 'error'}` }, c.status)),
            el('td', {}, c.id),
            el('td', { class: 'dim' }, (c.evidence || c.citation || '').slice(0, 96))));
          accOut.replaceChildren(
            notice(rep.overall_status === 'fail' ? 'error' : 'ok',
              `overall_status: ${rep.overall_status}`,
              `${r.command}  ·  exit ${r.exitCode}`),
            el('div', { style: 'height:10px' }),
            el('table', { class: 'data' },
              el('thead', {}, el('tr', {}, el('th', {}, ''), el('th', {}, 'criterion'), el('th', {}, 'evidence'))),
              el('tbody', {}, ...rows)));
        } catch (e) { accOut.replaceChildren(refusalNotice(e)); }
      },
    }, 'Run acceptance-check'),
    accOut);

  function reload() { import('./app.js').then((m) => m.reselect()); }

  return stage('syber_runtime',
    head({
      id: 'syber_runtime', title: 'SyberRuntime', badge: 'operation-primary kernel',
      lede: 'Operations are the source of truth; artifacts are projections folded from a hash-chained log; '
        + 'verification debt is bounded accounting. Record a Feature and try to stabilize it before verifying — '
        + 'the kernel refuses, and the refusal is the point.',
      origin: 'in-process import · <b>syberruntime.Runtime</b> · zero third-party dependencies · session root under scratch',
    }),
    el('div', { class: 'grid-2' },
      panel('Drive the kernel', controls),
      el('div', { style: 'display:flex;flex-direction:column;gap:16px' },
        panel(`Debt ledger — residual ${num(st.debt.totalResidual, 2)}`, debtTable, { flush: true }),
        panel('Artifacts', artTable, { flush: true }))),
    out(result),
    panel(`Operation log — ${data.log.length} entries, hash-chained`, logTable, { flush: true }),
    el('div', { class: 'grid-2' },
      panel('Evidence', evidence),
      panel('Fail-closed acceptance gate', acceptance)));
}

/* =================================================================
   Barn — organization graph, licensing decisions, replay audit
   ================================================================= */

async function barnInstrument() {
  const snap = await api('/api/barn/snapshot');
  const result = resultHost();
  const has = Boolean(snap.state);

  if (!has) {
    const goal = el('input', { type: 'text', value: 'Ship a payments integration' });
    const cap = el('input', { type: 'number', value: '3', min: '1' });
    return stage('barn',
      head({
        id: 'barn', title: 'Barn', badge: 'organization runtime',
        lede: 'An artifact-conditioned organization graph for long-horizon coding agents. Every spawn, reuse, '
          + 'retire, artifact and verification is an append-only event licensed by a deterministic transition engine.',
        origin: 'mounted ASGI app · <b>barn.api.create_app()</b> · this UI and the raw API at /systems/barn share one engine',
      }),
      panel('Start a run', el('div', {},
        el('div', { class: 'row' },
          el('div', { class: 'field' }, el('label', {}, 'goal'), goal),
          el('div', { class: 'field' }, el('label', {}, 'max active agents'), cap),
          el('button', {
            class: 'act primary', onclick: async () => {
              await api('/api/barn/run', {
                method: 'POST',
                body: { goal: goal.value, maxActiveAgents: Number(cap.value) },
              });
              import('./app.js').then((m) => m.reselect());
            },
          }, 'Create run')),
        el('p', { class: 'faint', style: 'margin-top:14px' },
          'The real Barn API is also reachable unmodified at ',
          el('a', { href: '/systems/barn/docs', target: '_blank', style: 'color:var(--live)' }, '/systems/barn/docs'),
          ' — the source system stays independently usable.'))));
  }

  const run = snap.state;
  const agents = Object.values(run.agents || {});
  const works = Object.values(run.work_items || {});
  const artifacts = Object.values(run.artifacts || {});
  const events = snap.events || [];

  const agentSel = (v) => el('select', {}, ...agents.map((a) =>
    el('option', { value: a.id, selected: a.id === v }, `${a.role} · ${short(a.id, 14)}`)));
  // Default to a work item that actually declares required capabilities, so the
  // first specialist request exercises the licensing path rather than being
  // rejected with capability_not_required for an unrelated goal item.
  const needsCaps = works.filter((w) => (w.required_capabilities || []).length
    && !['resolved', 'abandoned'].includes(w.status));
  const preferred = (needsCaps[needsCaps.length - 1] || works[works.length - 1] || {}).id;
  const workSel = () => el('select', {}, ...works.map((w) =>
    el('option', { value: w.id, selected: w.id === preferred },
      `${w.title.slice(0, 34)} · ${w.status}`
      + ((w.required_capabilities || []).length ? ` · needs ${w.required_capabilities.join(',')}` : ''))));

  // -- specialist request
  const reqAgent = agentSel(agents[0]?.id);
  const reqWork = workSel();
  const preferredWork = works.find((w) => w.id === preferred);
  const reqCap = el('input', {
    type: 'text',
    value: (preferredWork?.required_capabilities || [])[0] || 'payments',
  });
  const reqRole = el('input', { type: 'text', value: 'Payments specialist' });
  const withAdvice = el('input', { type: 'checkbox', checked: true, style: 'width:auto' });

  const specialist = el('div', {},
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'requesting agent'), reqAgent),
      el('div', { class: 'field' }, el('label', {}, 'work'), reqWork)),
    el('div', { style: 'height:10px' }),
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'capability'), reqCap),
      el('div', { class: 'field' }, el('label', {}, 'role'), reqRole)),
    el('label', { class: 'faint mono', style: 'display:flex;gap:7px;align-items:center;margin-top:10px;font-size:11px' },
      withAdvice, 'also compute Bough advice beside the committed decision'),
    el('div', { class: 'btn-row' },
      el('button', {
        class: 'act primary', onclick: async () => {
          try {
            const r = await api('/api/barn/specialist', {
              method: 'POST',
              body: {
                requestingAgentId: reqAgent.value, workId: reqWork.value,
                capability: reqCap.value, role: reqRole.value,
                reason: `${reqAgent.selectedOptions[0].text.split(' ·')[0]} lacks ${reqCap.value}`,
                withAdvice: withAdvice.checked,
              },
            });
            const d = r.decision;
            const kids = [notice(d.outcome === 'rejected' ? 'refused' : 'ok',
              `Barn committed: ${d.outcome.toUpperCase()}`,
              `reason: ${d.reason}${d.agent_id ? ' · agent ' + short(d.agent_id, 14) : ''}`)];
            if (r.advice) kids.push(adviceBlock(r.advice, d));
            reloadWith(el('div', {}, ...kids));
          } catch (e) { say(result, refusalNotice(e)); }
        },
      }, 'Request specialist')));

  // -- work + artifact + verification + resolve
  const wTitle = el('input', { type: 'text', value: 'Integrate Stripe webhooks' });
  const wCaps = el('input', { type: 'text', value: 'payments' });
  const wVerify = el('input', { type: 'checkbox', checked: true, style: 'width:auto' });
  const addWork = el('div', {},
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'title'), wTitle),
      el('div', { class: 'field' }, el('label', {}, 'required capabilities'), wCaps)),
    el('label', { class: 'faint mono', style: 'display:flex;gap:7px;align-items:center;margin-top:10px;font-size:11px' },
      wVerify, 'requires independent verification'),
    el('div', { class: 'btn-row' },
      el('button', {
        class: 'act', onclick: async () => {
          try {
            await api('/api/barn/work', {
              method: 'POST',
              body: {
                actorAgentId: agents[0]?.id, title: wTitle.value,
                requiredCapabilities: wCaps.value.split(',').map((s) => s.trim()).filter(Boolean),
                parentWorkId: works[0]?.id, requiresVerification: wVerify.checked,
              },
            });
            import('./app.js').then((m) => m.reselect());
          } catch (e) { say(result, refusalNotice(e)); }
        },
      }, 'Add work')));

  const aAgent = agentSel(agents[agents.length - 1]?.id);
  const aWork = workSel();
  const lifecycle = el('div', {},
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'acting agent'), aAgent),
      el('div', { class: 'field' }, el('label', {}, 'work'), aWork)),
    el('div', { class: 'btn-row' },
      el('button', {
        class: 'act', onclick: async () => {
          try {
            const r = await api('/api/barn/artifact', {
              method: 'POST',
              body: {
                agentId: aAgent.value, workId: aWork.value, kind: 'code',
                uri: `repo://${aWork.selectedOptions[0].text.split(' ·')[0].toLowerCase().replace(/\W+/g, '-')}.py`,
                contentHash: `sha256:${Math.random().toString(16).slice(2, 10)}`,
              },
            });
            reloadWith(notice('ok', 'Artifact submitted', short(r.artifact.id, 18)));
          } catch (e) { say(result, refusalNotice(e)); }
        },
      }, 'Submit artifact'),
      el('button', {
        class: 'act', onclick: async () => {
          try {
            await api('/api/barn/resolve', {
              method: 'POST', body: { workId: aWork.value, actorAgentId: aAgent.value },
            });
            reloadWith(notice('ok', 'Work resolved', 'artifact present and independently verified'));
          } catch (e) { say(result, refusalNotice(e)); }
        },
      }, 'Resolve work')));

  // verification needs an artifact + a verifier
  const vArt = el('select', {}, ...artifacts.map((a) =>
    el('option', { value: a.id }, `${a.kind} · ${short(a.id, 14)}`)));
  const vAgent = agentSel(agents[0]?.id);
  const verification = artifacts.length
    ? el('div', {},
      el('div', { class: 'row' },
        el('div', { class: 'field' }, el('label', {}, 'artifact'), vArt),
        el('div', { class: 'field' }, el('label', {}, 'verifier'), vAgent)),
      el('p', { class: 'faint mono', style: 'margin-top:8px;font-size:10.5px' },
        'Choosing the producing agent is refused with independent_verifier_required.'),
      el('div', { class: 'btn-row' },
        el('button', {
          class: 'act', onclick: async () => {
            try {
              const r = await api('/api/barn/verification', {
                method: 'POST',
                body: {
                  verifierAgentId: vAgent.value, artifactId: vArt.value,
                  passed: true, evidence: 'reviewed signature handling and retry semantics',
                },
              });
              reloadWith(notice('ok', 'Verification recorded', `passed: ${r.verification.passed}`));
            } catch (e) { say(result, refusalNotice(e)); }
          },
        }, 'Record verification')))
    : el('div', { class: 'empty' }, 'Submit an artifact first.');

  // -- graph
  const graph = orgGraph(agents, works);

  // -- tables
  const agentTable = el('table', { class: 'data' },
    el('thead', {}, el('tr', {}, el('th', {}, 'agent'), el('th', {}, 'role'),
      el('th', {}, 'status'), el('th', {}, 'capabilities'), el('th', {}, 'why'))),
    el('tbody', {}, ...agents.map((a) => el('tr', {},
      el('td', {}, short(a.id, 14)),
      el('td', {}, a.role),
      el('td', {}, el('span', { class: `tag ${a.status === 'retired' ? '' : 'ok'}` }, a.status)),
      el('td', { class: 'dim' }, (a.capabilities || []).join(', ')),
      el('td', {}, el('button', {
        class: 'act', style: 'padding:2px 8px;font-size:10px',
        onclick: async () => {
          const r = await api(`/api/barn/why/${a.id}`);
          openDrawer(`Why does ${short(a.id, 14)} exist?`, el('div', {},
            el('div', { class: 'timeline' }, ...r.explanation.steps.map((s) =>
              el('div', { class: 'step done' },
                el('h5', {}, s.label),
                el('div', { class: 'who' }, s.kind + ' · ' + short(s.id, 22))))),
            el('div', { class: 'insp-section' }, el('h4', {}, 'Raw'), jsonBlock(r.explanation))));
        },
      }, 'trace'))))));

  const workTable = el('table', { class: 'data' },
    el('thead', {}, el('tr', {}, el('th', {}, 'work'), el('th', {}, 'status'),
      el('th', {}, 'requires verification'), el('th', {}, 'assigned'))),
    el('tbody', {}, ...works.map((w) => el('tr', {
      class: 'clickable', onclick: () => openDrawer('Work item', jsonBlock(w)),
    },
      el('td', {}, w.title),
      el('td', {}, el('span', { class: `tag ${w.status === 'resolved' ? 'ok' : ''}` }, w.status)),
      el('td', { class: 'dim' }, w.requires_verification ? 'yes' : '—'),
      el('td', { class: 'faint' }, w.assigned_agent_id ? short(w.assigned_agent_id, 14) : '—')))));

  const eventTable = el('table', { class: 'data' },
    el('thead', {}, el('tr', {}, el('th', {}, 'seq'), el('th', {}, 'type'),
      el('th', {}, 'actor'), el('th', {}, 'decision'))),
    el('tbody', {}, ...events.slice().reverse().map((e) => el('tr', {
      class: 'clickable', onclick: () => openDrawer(`BarnEvent ${e.type}`, jsonBlock(e)),
    },
      el('td', { class: 'num faint' }, String(e.seq)),
      el('td', {}, el('span', { class: 'tag' }, e.type)),
      el('td', { class: 'faint' }, e.actor_agent_id ? short(e.actor_agent_id, 12) : '—'),
      el('td', { class: 'dim' }, e.payload?.decision
        ? `${e.payload.decision.outcome} · ${e.payload.decision.reason}` : '—')))));

  // -- audit
  const auditOut = el('div', { style: 'margin-top:12px' });
  const audit = el('div', {},
    el('p', { class: 'dim', style: 'margin:0 0 10px' },
      'Barn hashes the materialized run state and compares it to state replayed from zero '
      + 'over the event log. If the two hashes differ, the event log is not the whole truth.'),
    el('button', {
      class: 'act', onclick: async () => {
        auditOut.replaceChildren(el('span', { class: 'spin' }));
        try {
          const r = await api('/api/barn/audit', { method: 'POST' });
          const a = r.audit;
          auditOut.replaceChildren(
            notice(a.matches ? 'ok' : 'error',
              a.matches ? 'Replay matches materialized state' : 'Replay MISMATCH',
              `${a.event_count} events`),
            el('div', { style: 'height:10px' }),
            kv([
              ['materialized', el('span', { class: 'mono' }, a.materialized_hash)],
              ['replayed', el('span', { class: 'mono' }, a.replayed_hash || '—')],
              ['replay error', a.replay_error || '—'],
            ]));
        } catch (e) { auditOut.replaceChildren(refusalNotice(e)); }
      },
    }, 'Audit by replay'),
    auditOut);

  const adviceOut = el('div', { style: 'margin-top:12px' });

  return stage('barn',
    head({
      id: 'barn', title: 'Barn', badge: `run ${short(run.id, 14)}`,
      lede: run.goal + ' — every organizational mutation below is licensed by the transition engine. '
        + 'Try resolving work with no artifact, or verifying an artifact with the agent that produced it.',
      origin: 'mounted ASGI app · <b>barn.api.create_app()</b> · shared engine · raw API at '
        + '<a href="/systems/barn/docs" target="_blank" style="color:var(--live)">/systems/barn/docs</a>',
    }),
    el('div', { class: 'grid-2' },
      panel('Specialist request — spawn / reuse / reject', specialist),
      panel('Work, artifacts, resolution', el('div', {}, addWork,
        el('hr', { style: 'border:0;border-top:1px solid var(--rule);margin:14px 0' }),
        lifecycle,
        el('hr', { style: 'border:0;border-top:1px solid var(--rule);margin:14px 0' }),
        verification))),
    out(result),
    panel('Organization graph', graph, { flush: true }),
    el('div', { class: 'grid-2' },
      panel('Agents', agentTable, { flush: true }),
      panel('Work items', workTable, { flush: true })),
    panel(`Event ledger — ${events.length} append-only events`, eventTable, { flush: true }),
    el('div', { class: 'grid-2' },
      panel('Replay audit', audit),
      panel('Bough advice (seam)', el('div', {},
        el('p', { class: 'dim', style: 'margin:0 0 10px' },
          'The integration plan in the source repo specifies an advisor between "a legal transition exists" '
          + 'and "which legal transition to commit". It may break ties and annotate; it may never authorize.'),
        el('button', {
          class: 'act', onclick: async () => {
            adviceOut.replaceChildren(el('span', { class: 'spin' }));
            try {
              const r = await api('/api/barn/advice', { method: 'POST' });
              adviceOut.replaceChildren(adviceBlock(r, null));
            } catch (e) { adviceOut.replaceChildren(refusalNotice(e)); }
          },
        }, 'Compute advice'),
        adviceOut))));
}

function adviceBlock(r, committed) {
  if (r.refused) return refusalNotice({ payload: r.refused });
  const a = r.advice;
  const rows = Object.entries(r.branches || {}).map(([rule, b]) => {
    const isChosen = rule === a.action;
    return el('tr', {},
      el('td', {}, el('span', { class: `tag ${isChosen ? 'ok' : ''}` }, rule)),
      el('td', { class: 'num' }, num(b.value, 4)),
      el('td', { class: 'num' }, num(b.reachProbability, 4)),
      el('td', { style: 'width:120px' }, el('div', { class: 'bar' },
        el('span', { style: `width:${Math.max(0, Math.min(1, b.reachProbability || 0)) * 100}%` }))));
  });
  const agree = committed
    ? (committed.outcome === 'spawned' && a.action === 'spawn')
      || (committed.outcome === 'reused' && a.action === 'reuse')
    : null;
  return el('div', {},
    committed
      ? notice(agree ? 'ok' : 'refused',
        agree ? 'Advice agrees with the committed decision' : 'Advice DIFFERS from the committed decision',
        `Barn committed ${committed.outcome}; Bough's value-optimal action is ${a.action}. `
        + 'Barn\'s decision stands — the advisor is not an authorization.')
      : null,
    el('div', { style: 'height:10px' }),
    el('table', { class: 'data' },
      el('thead', {}, el('tr', {}, el('th', {}, 'action'), el('th', {}, 'value'),
        el('th', {}, 'reach(resolved)'), el('th', {}, ''))),
      el('tbody', {}, ...rows)),
    el('div', { style: 'height:12px' }),
    kv([
      ['advised action', a.action],
      ['root value', num(a.value, 6)],
      ['reach probability', num(a.reach_probability, 6)],
      ['truncated', String(a.truncated)],
      ['authoritative', el('span', { class: 'tag refused' }, 'false — advice only')],
      ['repertoire hash', el('span', { class: 'mono' }, short(a.repertoire_hash, 24))],
      ['twin situations', `${r.automaton.situationCount} (from ${r.automaton.uncoalescedNodeCount} uncoalesced, ratio ${num(r.automaton.compressionRatio, 3)})`],
    ]),
    el('div', { style: 'height:10px' }),
    el('details', {}, el('summary', { class: 'faint mono', style: 'cursor:pointer;font-size:11px' },
      'calibration basis'), jsonBlock(r.calibration)),
    el('p', { class: 'faint', style: 'margin-top:10px;font-size:11px' }, r.disclaimer));
}

function orgGraph(agents, works) {
  const W = 1000, rowH = 64, pad = 28;
  const H = pad * 2 + Math.max(agents.length, works.length) * rowH;
  const svg = el('div', { class: 'graphwrap' });
  const ns = 'http://www.w3.org/2000/svg';
  const s = document.createElementNS(ns, 'svg');
  s.setAttribute('viewBox', `0 0 ${W} ${H}`);
  s.setAttribute('width', String(W));
  s.setAttribute('height', String(H));

  const mk = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
    if (text !== undefined) n.textContent = text;
    return n;
  };

  const aPos = new Map(), wPos = new Map();
  agents.forEach((a, i) => aPos.set(a.id, { x: 190, y: pad + 22 + i * rowH }));
  works.forEach((w, i) => wPos.set(w.id, { x: 700, y: pad + 22 + i * rowH }));

  // spawned_because edges
  for (const a of agents) {
    if (!a.spawned_because_work_id) continue;
    const from = aPos.get(a.id), to = wPos.get(a.spawned_because_work_id);
    if (!from || !to) continue;
    s.append(mk('path', {
      d: `M ${from.x + 120} ${from.y} C 420 ${from.y}, 470 ${to.y}, ${to.x - 130} ${to.y}`,
      class: 'edge', 'stroke-dasharray': '3 3',
    }));
  }
  // assignment edges
  for (const w of works) {
    if (!w.assigned_agent_id) continue;
    const from = aPos.get(w.assigned_agent_id), to = wPos.get(w.id);
    if (!from || !to) continue;
    s.append(mk('path', {
      d: `M ${from.x + 120} ${from.y} C 420 ${from.y}, 470 ${to.y}, ${to.x - 130} ${to.y}`,
      class: 'edge',
    }));
  }

  s.append(mk('text', { x: 70, y: 18, class: 'node-label' }, 'AGENTS'));
  s.append(mk('text', { x: 570, y: 18, class: 'node-label' }, 'WORK'));

  for (const a of agents) {
    const p = aPos.get(a.id);
    const g = mk('g', { class: 'gnode' });
    g.append(mk('rect', {
      x: p.x - 120, y: p.y - 17, width: 240, height: 34, rx: 4,
      class: a.status === 'retired' ? 'node-d' : 'node-c',
    }));
    g.append(mk('text', { x: p.x - 108, y: p.y - 2, class: 'node-label', fill: 'var(--ink)' }, a.role.slice(0, 26)));
    g.append(mk('text', { x: p.x - 108, y: p.y + 10, class: 'node-label' },
      `${a.status} · ${(a.capabilities || []).join(',').slice(0, 24)}`));
    g.addEventListener('click', () => openDrawer('Agent', jsonBlock(a)));
    s.append(g);
  }
  for (const w of works) {
    const p = wPos.get(w.id);
    const g = mk('g', { class: 'gnode' });
    g.append(mk('rect', {
      x: p.x - 130, y: p.y - 17, width: 260, height: 34, rx: 4,
      class: w.status === 'resolved' ? 'node-t' : 'node-c',
    }));
    g.append(mk('text', { x: p.x - 118, y: p.y - 2, class: 'node-label', fill: 'var(--ink)' }, w.title.slice(0, 30)));
    g.append(mk('text', { x: p.x - 118, y: p.y + 10, class: 'node-label' },
      `${w.status}${w.requires_verification ? ' · needs verification' : ''}`));
    g.addEventListener('click', () => openDrawer('Work item', jsonBlock(w)));
    s.append(g);
  }

  svg.append(s);
  svg.append(el('div', { class: 'faint mono', style: 'padding:8px 14px;font-size:10px' },
    'solid = assignment · dashed = spawned_because · click any node for its raw state'));
  return svg;
}

/* =================================================================
   Bough — the compiled jump chain
   ================================================================= */

async function boughInstrument() {
  const { families } = await api('/api/bough/families');
  const result = el('div');
  const graphHost = el('div', { class: 'graphwrap' },
    el('div', { class: 'empty' }, 'Compile a family to see its jump chain.'));
  const reportHost = el('div', {}, el('div', { class: 'empty' }, 'No compilation yet.'));

  const famSel = el('select', {}, ...Object.entries(families).map(([id, f]) =>
    el('option', { value: id }, f.title)));
  const paramHost = el('div', { class: 'row' });
  const maxSit = el('input', { type: 'number', value: '5000', min: '1' });
  const maxDepth = el('input', { type: 'number', value: '', placeholder: 'unbounded' });

  function renderParams() {
    const f = families[famSel.value];
    paramHost.replaceChildren(...Object.entries(f.params || {}).map(([k, spec]) =>
      el('div', { class: 'field' },
        el('label', {}, k),
        el('input', {
          type: 'number', value: String(spec.default), min: String(spec.min ?? 0),
          max: String(spec.max ?? 999), step: spec.type === 'float' ? '0.1' : '1',
          'data-param': k,
        }))));
    if (!Object.keys(f.params || {}).length) {
      paramHost.replaceChildren(el('div', { class: 'faint mono', style: 'font-size:11px' },
        'this family takes no parameters'));
    }
  }
  famSel.addEventListener('change', renderParams);
  renderParams();

  let lastGoal = null;

  async function compile() {
    const params = {};
    paramHost.querySelectorAll('[data-param]').forEach((i) => { params[i.dataset.param] = Number(i.value); });
    try {
      const r = await api('/api/bough/compile', {
        method: 'POST',
        body: {
          family: famSel.value, params,
          maxSituations: Number(maxSit.value),
          maxDepth: maxDepth.value ? Number(maxDepth.value) : null,
        },
      });
      lastGoal = r.goal;
      const rep = r.report;
      reportHost.replaceChildren(kv([
        ['situations', el('b', {}, String(rep.situation_count))],
        ['uncoalesced', String(rep.uncoalesced_node_count)],
        ['compression ratio', el('b', {}, num(rep.compression_ratio, 4))],
        ['edges', String(rep.edge_count)],
        ['stages (derived)', rep.stage_count ?? rep.staging_error ?? '—'],
        ['truncated', el('span', { class: `tag ${rep.truncated ? 'refused' : 'ok'}` }, String(rep.truncated))],
        ['expand', `${num(rep.expand_seconds * 1000, 2)} ms`],
        ['refresh', rep.refresh_seconds !== null ? `${num(rep.refresh_seconds * 1000, 3)} ms` : '—'],
        ['root', el('span', { class: 'mono' }, short(rep.root, 20))],
      ]));
      graphHost.replaceChildren(jumpChain(r.automaton));
      say(result, notice('ok', `Compiled ${families[famSel.value].title}`,
        `${rep.uncoalesced_node_count} uncoalesced states coalesced to ${rep.situation_count}`));
    } catch (e) { say(result, refusalNotice(e)); graphHost.replaceChildren(el('div', { class: 'empty' }, 'compilation refused')); }
  }

  const goalInput = el('input', { type: 'text', value: 'all-on', placeholder: 'terminal label' });
  const queryOut = el('div', { style: 'margin-top:12px' });

  const controls = el('div', {},
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'family'), famSel)),
    el('div', { style: 'height:10px' }), paramHost,
    el('div', { style: 'height:10px' }),
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'max situations'), maxSit),
      el('div', { class: 'field' }, el('label', {}, 'max depth'), maxDepth)),
    el('div', { class: 'btn-row' }, el('button', { class: 'act primary', onclick: compile }, 'Compile')),
    el('hr', { style: 'border:0;border-top:1px solid var(--rule);margin:16px 0' }),
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'reach — terminal label'), goalInput),
      el('button', {
        class: 'act', onclick: async () => {
          try {
            const r = await api('/api/bough/reach', { method: 'POST', body: { label: goalInput.value } });
            queryOut.replaceChildren(notice('ok', `reach(${r.label}) = ${r.mass}`,
              `exact probability mass over ${r.paths} distinct path(s)`));
          } catch (e) { queryOut.replaceChildren(refusalNotice(e)); }
        },
      }, 'reach()')),
    el('div', { class: 'btn-row' },
      el('button', {
        class: 'act', onclick: async () => {
          try {
            const r = await api('/api/bough/policy', { method: 'POST' });
            queryOut.replaceChildren(
              notice('ok', `optimal action: ${r.rootAction[0] ?? 'none'}`,
                `root value ${num(r.rootValue, 6)} — backward induction over the compiled automaton`),
              el('div', { style: 'height:10px' }), jsonBlock({ rootValue: r.rootValue, rootAction: r.rootAction }));
          } catch (e) { queryOut.replaceChildren(refusalNotice(e)); }
        },
      }, 'optimal_policy()'),
      el('button', {
        class: 'act', onclick: async () => {
          try {
            const r = await api('/api/bough/cypher', { method: 'POST' });
            openDrawer('Neo4j inspection Cypher', el('pre', { class: 'json' }, r.cypher));
          } catch (e) { queryOut.replaceChildren(refusalNotice(e)); }
        },
      }, 'Cypher export')),
    queryOut);

  return stage('bough',
    head({
      id: 'bough', title: 'Bough', badge: 'jump-chain compiler',
      lede: 'A typed hypergraph rewrite system compiled into an exhaustively coalesced jump chain with exact '
        + 'path and reachability probabilities. Compile the ontology fragment and ask for reach() — it is cyclic, '
        + 'and Bough refuses rather than approximating.',
      origin: 'in-process import · <b>bough.expand / reach / optimal_policy</b> · over OSAHR 0.2 at the pinned commit',
    }),
    el('div', { class: 'grid-2' },
      panel('Compile and query', controls),
      panel('Compilation report', el('div', {}, reportHost, out(result)))),
    panel('Jump chain — situations by depth, edges carry exact probabilities', graphHost, { flush: true }));
}

function jumpChain(auto) {
  const byDepth = new Map();
  for (const s of auto.situations) {
    if (!byDepth.has(s.depth)) byDepth.set(s.depth, []);
    byDepth.get(s.depth).push(s);
  }
  const depths = [...byDepth.keys()].sort((a, b) => a - b);
  const colW = 210, rowH = 46, pad = 34;
  const maxRows = Math.max(...depths.map((d) => byDepth.get(d).length));
  const W = pad * 2 + depths.length * colW;
  const H = pad * 2 + maxRows * rowH + 20;

  const ns = 'http://www.w3.org/2000/svg';
  const mk = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const s = document.createElementNS(ns, 'svg');
  s.setAttribute('viewBox', `0 0 ${W} ${H}`);
  s.setAttribute('width', String(W));
  s.setAttribute('height', String(H));

  const pos = new Map();
  depths.forEach((d, di) => {
    const col = byDepth.get(d);
    const offset = (maxRows - col.length) / 2;
    col.forEach((sit, i) => {
      pos.set(sit.signature, { x: pad + di * colW + 70, y: pad + 26 + (offset + i) * rowH });
    });
  });

  // depth guides
  depths.forEach((d, di) => {
    s.append(mk('text', { x: pad + di * colW + 70, y: 20, class: 'node-label', 'text-anchor': 'middle' },
      `depth ${d}`));
  });

  for (const e of auto.edges) {
    const a = pos.get(e.source), b = pos.get(e.target);
    if (!a || !b) continue;
    s.append(mk('path', {
      d: `M ${a.x + 62} ${a.y} C ${a.x + 120} ${a.y}, ${b.x - 120} ${b.y}, ${b.x - 62} ${b.y}`,
      class: 'edge',
    }));
    if (e.probability !== null && e.probability !== undefined) {
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 - 4;
      s.append(mk('text', { x: mx, y: my, class: 'edge-label', 'text-anchor': 'middle' },
        Number(e.probability).toFixed(3)));
    }
  }

  for (const sit of auto.situations) {
    const p = pos.get(sit.signature);
    const cls = sit.kind === 'terminal' ? 'node-t' : sit.kind === 'decision' ? 'node-d' : 'node-c';
    const g = mk('g', { class: 'gnode' });
    g.append(mk('rect', {
      x: p.x - 62, y: p.y - 15, width: 124, height: 30, rx: 4,
      class: `${cls}${sit.isRoot ? ' node-root' : ''}`,
    }));
    g.append(mk('text', { x: p.x, y: p.y - 2, class: 'node-label', 'text-anchor': 'middle', fill: 'var(--ink)' },
      sit.label || sit.short));
    g.append(mk('text', { x: p.x, y: p.y + 9, class: 'node-label', 'text-anchor': 'middle' },
      `${sit.kind}${sit.isRoot ? ' · root' : ''}`));
    g.addEventListener('click', () => openDrawer(`Situation ${sit.short}`, el('div', {},
      el('div', { class: 'insp-section' }, el('h4', {}, 'Situation'), kv([
        ['signature', el('span', { class: 'mono' }, sit.signature)],
        ['kind', sit.kind], ['depth', String(sit.depth)],
        ['label', sit.label || '—'], ['out-degree', String(sit.outDegree)],
        ['hypergraph', `${sit.graph?.nodeCount ?? '?'} vertices, ${sit.graph?.edgeCount ?? '?'} hyperedges`],
      ])),
      el('div', { class: 'insp-section' }, el('h4', {}, 'Outgoing edges'),
        jsonBlock(auto.edges.filter((e) => e.source === sit.signature))))));
    s.append(g);
  }

  const wrap = el('div', {});
  wrap.append(s);
  wrap.append(el('div', { class: 'faint mono', style: 'padding:8px 14px;font-size:10px' },
    'green outline = chance · amber = decision · filled = terminal · bold = root · numbers on edges are exact probabilities'));
  return wrap;
}

/* =================================================================
   OSAHR — exact vs kernel schedulers
   ================================================================= */

async function osahrInstrument() {
  const result = el('div');
  const sixG = await sixGPanel();
  const famSel = el('select', {},
    el('option', { value: 'race' }, 'C2 race (exact P(a) = rate_a / (rate_a + rate_b))'),
    el('option', { value: 'bits' }, 'Irreversible bits'));
  const rateA = el('input', { type: 'number', value: '2.0', step: '0.5', min: '0.1' });
  const rateB = el('input', { type: 'number', value: '1.0', step: '0.5', min: '0.1' });
  const reps = el('input', { type: 'number', value: '96', step: '24', min: '8' });
  const seed = el('input', { type: 'number', value: '23' });
  const outHost = el('div', { style: 'margin-top:14px' },
    el('div', { class: 'empty' }, 'Run the comparison to drive the kernel.'));

  const controls = el('div', {},
    el('div', { class: 'field' }, el('label', {}, 'family'), famSel),
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'rate a'), rateA),
      el('div', { class: 'field' }, el('label', {}, 'rate b'), rateB)),
    el('div', { style: 'height:10px' }),
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'replicates per scheduler'), reps),
      el('div', { class: 'field' }, el('label', {}, 'root seed'), seed)),
    el('div', { class: 'btn-row' },
      el('button', {
        class: 'act primary', onclick: async () => {
          outHost.replaceChildren(el('div', { style: 'padding:14px' }, el('span', { class: 'spin' }),
            el('span', { class: 'faint', style: 'margin-left:9px' }, 'driving three kernel schedulers…')));
          try {
            const r = await api('/api/osahr/agreement', {
              method: 'POST',
              body: {
                family: famSel.value,
                params: famSel.value === 'race'
                  ? { rate_a: Number(rateA.value), rate_b: Number(rateB.value) } : { n: 2 },
                replicates: Number(reps.value), rootSeed: Number(seed.value),
              },
            });
            outHost.replaceChildren(agreementView(r));
          } catch (e) { outHost.replaceChildren(refusalNotice(e)); }
        },
      }, 'Run comparison')));

  // -- the kernel's own primitive: a typed directed hypergraph + rewrite rules
  const modelSel = el('select', {},
    el('option', { value: 'ontology' }, 'Ontology fragment (typed hyperedges)'),
    el('option', { value: 'token_attach' }, 'Token attach'),
    el('option', { value: 'race' }, 'C2 race'),
    el('option', { value: 'machine' }, 'Protect / ignore'),
    el('option', { value: 'bits' }, 'Irreversible bits'));
  const modelOut = el('div', { style: 'margin-top:12px' },
    el('div', { class: 'empty' }, 'Load a model to inspect its hypergraph.'));

  const modelPanel = el('div', {},
    el('p', { class: 'dim', style: 'margin:0 0 10px' },
      'Everything below is read off the real osahr.Model: vertices with their declared types and '
      + 'attributes, hyperedges with their tail/head incidences and roles, and each rule exactly as '
      + 'the family declared it. A rule is a rewrite: the left graph is matched and replaced by the right.'),
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'model'), modelSel),
      el('button', {
        class: 'act', onclick: async () => {
          modelOut.replaceChildren(el('span', { class: 'spin' }));
          try {
            const m = await api(`/api/osahr/model?family=${modelSel.value}`);
            modelOut.replaceChildren(hypergraphView(m));
          } catch (e) { modelOut.replaceChildren(refusalNotice(e)); }
        },
      }, 'Load model')),
    modelOut);


/* ---------------- the 6G semantic twin: a full visual panel ------------- */

async function sixGPanel() {
  const host = el('div');
  const netHost = el('div', { class: 'panel' });
  const statsHost = el('div');
  const feedHost = el('div');
  const clockHost = el('div');
  let started = false;

  const policySel = el('select', {},
    el('option', { value: 'semantic', selected: true }, 'semantic — task-aware'),
    el('option', { value: 'qos' }, 'qos — reliability + fidelity'),
    el('option', { value: 'throughput' }, 'throughput — rate + link only'));
  const seed = el('input', { type: 'number', value: '7' });
  const noteHost = el('div');

  function paint(snapshot) {
    netHost.replaceChildren(
      el('header', {},
        el('h3', {}, `Adaptive RAN / MEC twin — t = ${num(snapshot.time, 3)}s`),
        el('span', { class: 'spacer' }),
        snapshot.outage.active
          ? el('span', { class: 'tag error' }, 'MEC-fast outage')
          : el('span', { class: 'tag ok' }, 'both edges up'),
        el('span', { class: 'tag' }, `${snapshot.eventIndex} kernel events`)),
      el('div', { class: 'body flush' }, networkView(snapshot)));
    clockHost.replaceChildren(timeline(snapshot));
    statsHost.replaceChildren(statsView(snapshot));
    feedHost.replaceChildren(eventFeed(snapshot.recentEvents));
  }

  async function begin() {
    const r = await api('/api/osahr6g/start', {
      method: 'POST', body: { policy: policySel.value, seed: Number(seed.value) },
    });
    started = true;
    noteHost.replaceChildren(el('div', { class: 'g6-policy-note' },
      el('b', {}, `${r.policy}: `), r.policyNote));
    paint(r.snapshot);
    return r;
  }

  async function advance(fn) {
    if (!started) await begin();
    const r = await fn();
    paint(r.snapshot);
    if (r.stopped) {
      noteHost.append(notice('refused', 'Stopped', r.stopped));
    }
  }

  /* The kernel runs at roughly 25 events a second with full event records, so
     advancing 35 seconds of simulated time is a ten-second wait. Streaming turns
     that from a frozen request into the thing worth watching. */
  let running = false;
  function streamTo(target) {
    if (running) return;
    running = true;
    const buttons = [...host.querySelectorAll('button.act')];
    buttons.forEach((b) => { b.disabled = true; });
    const progress = notice('ok', `Advancing to t = ${target}s…`,
      'Each frame is real kernel events; the network is rewiring as you watch.');
    noteHost.replaceChildren(progress);

    const src = new EventSource(
      `/api/osahr6g/stream?to=${target}&session=${SESSION_ID}`);
    let total = 0;
    const finish = (msg, kind = 'ok') => {
      src.close();
      running = false;
      buttons.forEach((b) => { b.disabled = false; });
      noteHost.replaceChildren(notice(kind, msg, ''));
    };
    src.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.type === 'frame') {
        total += d.events.length;
        paint(d.snapshot);
        progress.replaceChildren(
          el('b', {}, `t = ${num(d.snapshot.time, 2)}s`),
          el('span', { class: 'code' },
            `${total} kernel events · ${d.snapshot.counts.Transit || 0} in flight`
            + (d.snapshot.outage.active ? '  ·  MEC-fast is down' : '')));
      } else if (d.type === 'stopped') {
        finish(`Stopped: ${d.reason}`, 'refused');
      } else if (d.type === 'failed') {
        finish(d.error, 'error');
      } else if (d.type === 'end') {
        paint(d.snapshot);
        finish(`Reached t = ${num(d.snapshot.time, 2)}s after ${d.events} kernel events.`);
      }
    };
    src.onerror = () => finish('Lost the twin stream.', 'error');
  }

  const controls = el('div', {},
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'routing policy'), policySel),
      el('div', { class: 'field' }, el('label', {}, 'seed'), seed),
      el('button', { class: 'act primary', onclick: async () => {
        try { await begin(); } catch (e) { noteHost.replaceChildren(refusalNotice(e)); }
      } }, 'Build twin')),
    el('div', { class: 'btn-row' },
      ...[['Step 1', 1], ['Step 10', 10], ['Step 50', 50]].map(([label, n]) =>
        el('button', { class: 'act', onclick: () => advance(
          () => api('/api/osahr6g/step', { method: 'POST', body: { count: n } })) }, label)),
      el('button', { class: 'act', onclick: () => streamTo(20) }, 'Run to outage (20s)'),
      el('button', { class: 'act', onclick: () => streamTo(35) }, 'Through outage (35s)'),
      el('button', { class: 'act', onclick: () => streamTo(60) }, 'To horizon (60s)'),
      el('button', { class: 'act danger', onclick: async () => {
        const r = await api('/api/osahr6g/reset', { method: 'POST' }); paint(r.snapshot);
      } }, 'Reset')),
    noteHost,
    el('div', { style: 'height:12px' }),
    clockHost);

  // resume an already-running twin when the instrument is re-entered
  try {
    const existing = await api('/api/osahr6g/snapshot');
    if (existing.started) {
      started = true;
      policySel.value = existing.policy || 'semantic';
      paint(existing.snapshot);
    } else {
      netHost.replaceChildren(
        el('header', {}, el('h3', {}, 'Adaptive RAN / MEC twin')),
        el('div', { class: 'body' }, el('div', { class: 'empty' },
          'Build the twin to stand up a live OSAHR runtime.')));
      feedHost.replaceChildren(el('div', { class: 'empty' }, 'No kernel events yet.'));
      statsHost.replaceChildren(el('div', { class: 'empty' }, 'No statistics yet.'));
    }
  } catch (e) { noteHost.replaceChildren(refusalNotice(e)); }

  host.append(
    panel('Drive the twin', controls),
    netHost,
    el('div', { class: 'grid-2' },
      panel('Sufficient statistics (runtime.memory)', statsHost),
      panel('Kernel events', feedHost, { flush: true })));
  return host;
}

  return stage('osahr',
    head({
      id: 'osahr', title: 'OSAHR Cell', badge: 'stochastic rewrite kernel',
      lede: 'An open stochastic adaptive rewrite kernel over a typed directed hypergraph. Bough computes a '
        + 'first-passage probability analytically; OSAHR reaches the same number by simulation, three different ways. '
        + 'Each scheduler is an independent implementation, so agreement is a real cross-check.',
      origin: 'in-process import · <b>bough.compare.agree_first_passage</b> driving '
        + '<b>osahr.schedulers</b> · direct_ssa, next_reaction, thinning',
    }),
    el('div', {},
      el('h4', { class: 'g6-section' },
        '6G semantic twin',
        el('span', {}, 'osahr-6g/semantic_6g_twin_experiment.py — a RAN/MEC digital twin '
          + 'committed in the OSAHR repository, run here event by event')),
      sixG),
    el('h4', { class: 'g6-section' },
      'Kernel cross-check',
      el('span', {}, 'exact analytic probability against the kernel schedulers')),
    el('div', { class: 'grid-2' },
      panel('Configure the cross-check', controls),
      panel('Agreement', outHost)),
    out(result),
    panel('Typed hypergraph and rewrite rules', modelPanel));
}

function hypergraphView(m) {
  const vTable = el('table', { class: 'data' },
    el('thead', {}, el('tr', {}, el('th', {}, 'vertex'), el('th', {}, 'type'), el('th', {}, 'attributes'))),
    el('tbody', {}, ...m.vertices.map((v) => el('tr', {},
      el('td', { class: 'faint' }, v.id.split(':').pop()),
      el('td', {}, el('span', { class: 'tag' }, v.type)),
      el('td', { class: 'dim' }, Object.entries(v.attributes).map(([k, x]) => `${k}=${x}`).join('  ') || '—')))));

  const eTable = m.edges.length
    ? el('table', { class: 'data' },
      el('thead', {}, el('tr', {}, el('th', {}, 'hyperedge'), el('th', {}, 'type'),
        el('th', {}, 'tail (role → vertex)'), el('th', {}, 'head'))),
      el('tbody', {}, ...m.edges.map((e) => el('tr', {
        class: 'clickable', onclick: () => openDrawer('Hyperedge', jsonBlock(e)),
      },
        el('td', { class: 'faint' }, e.id.split(':').pop()),
        el('td', {}, el('span', { class: 'tag' }, e.type)),
        el('td', { class: 'dim' }, e.tail.map((i) => `${i.role}→${i.vertex.split(':').pop()}`).join('  ') || '—'),
        el('td', { class: 'dim' }, e.head.map((i) => `${i.role}→${i.vertex.split(':').pop()}`).join('  ') || '—')))))
    : el('div', { class: 'empty' }, 'This model has no hyperedges — its state lives entirely in vertex attributes.');

  const side = (g) => {
    const parts = g.vertices.map((v) =>
      `${v.key}:${v.type}{${Object.entries(v.attributes).map(([k, x]) => `${k}=${x}`).join(',')}}`);
    for (const e of g.edges) parts.push(`${e.key || ''}:${e.type}[${e.tail.length}→${e.head.length}]`);
    return parts.join('  ') || '∅';
  };

  const rTable = el('table', { class: 'data' },
    el('thead', {}, el('tr', {}, el('th', {}, 'rule'), el('th', {}, 'kind'), el('th', {}, 'hazard'),
      el('th', {}, 'left  ⟶  right'))),
    el('tbody', {}, ...m.rules.map((r) => el('tr', {
      class: 'clickable', onclick: () => openDrawer(`Rule ${r.ruleId}`, jsonBlock(r)),
    },
      el('td', {}, r.eventId),
      el('td', {}, el('span', { class: `tag ${r.kind === 'decision' ? 'refused' : 'ok'}` }, r.kind)),
      el('td', { class: 'num' }, r.hazard),
      el('td', { class: 'dim', style: 'font-size:11px' }, `${side(r.left)}   ⟶   ${side(r.right)}`)))));

  return el('div', {},
    kv([
      ['schema', m.schemaId],
      ['vertex types', m.vertexTypes.join(', ') || '—'],
      ['hyperedge types', m.edgeTypes.join(', ') || '—'],
      ['repertoire hash', el('span', { class: 'mono' }, short(m.repertoireHash, 24))],
    ]),
    el('div', { style: 'height:14px' }),
    el('h4', { class: 'faint mono', style: 'font-size:10px;letter-spacing:.14em;margin:0 0 6px' },
      `VERTICES (${m.vertices.length})`),
    vTable,
    el('div', { style: 'height:14px' }),
    el('h4', { class: 'faint mono', style: 'font-size:10px;letter-spacing:.14em;margin:0 0 6px' },
      `HYPEREDGES (${m.edges.length})`),
    eTable,
    el('div', { style: 'height:14px' }),
    el('h4', { class: 'faint mono', style: 'font-size:10px;letter-spacing:.14em;margin:0 0 6px' },
      `REWRITE RULES (${m.rules.length})`),
    rTable,
    el('div', { style: 'height:12px' }),
    provenanceBlock(m.provenance));
}

function agreementView(r) {
  const rows = r.schedulers.map((s) => {
    const pct = Math.max(0, Math.min(1, s.empirical));
    const exactPct = Math.max(0, Math.min(1, s.exact));
    return el('div', { style: 'margin-bottom:14px' },
      el('div', { style: 'display:flex;gap:10px;align-items:baseline;margin-bottom:5px' },
        el('span', { class: 'mono', style: 'min-width:108px' }, s.scheduler),
        el('span', { class: 'mono num dim' }, num(s.empirical, 4)),
        el('span', { style: 'flex:1' }),
        el('span', { class: `tag ${s.within_radius ? 'ok' : 'error'}` },
          s.within_radius ? 'within radius' : 'OUTSIDE radius')),
      el('div', { class: 'bar' },
        el('span', { style: `width:${pct * 100}%` }),
        el('span', { class: 'exact', style: `left:${exactPct * 100}%` })));
  });
  return el('div', {},
    notice('ok', `Bough exact = ${num(r.exact, 6)}`,
      `${r.replicates} replicates per scheduler · target label "${r.goal}" · ${r.paths} exact path(s)`),
    el('div', { style: 'height:14px' }),
    ...rows,
    el('div', { class: 'faint mono', style: 'font-size:10px;margin-top:4px' },
      'bar = empirical first-passage frequency · white tick = Bough\'s exact answer · '
      + 'radius is Hoeffding at alpha=1e-6'),
    el('div', { style: 'height:12px' }),
    el('details', {}, el('summary', { class: 'faint mono', style: 'cursor:pointer;font-size:11px' }, 'raw rows'),
      jsonBlock(r.schedulers)));
}

/* =================================================================
   Relay — the explicit handoff
   ================================================================= */

async function relayInstrument({ sys }) {
  if (!sys?.available) {
    return stage('relay',
      head({ id: 'relay', title: 'Relay', badge: 'unavailable' }),
      panel('Sidecar unreachable', el('div', {},
        notice('error', 'The Relay sidecar is not running',
          sys?.health?.error || 'no health response'),
        el('p', { class: 'dim', style: 'margin-top:12px' },
          'Relay is TypeScript and requires Node >= 24. The platform runs its real lib/*.ts modules in a '
          + 'Node 24 sidecar. Start it with:'),
        el('pre', { class: 'json' },
          'RELAY_ROOT=<repo>/systems/relay node platform/relay-sidecar/server.mjs'))));
  }

  const result = el('div');
  const url = el('input', { type: 'text', value: 'https://job-boards.greenhouse.io/acme/jobs/4455?utm_campaign=spring&gh_src=abc' });
  const facts = el('textarea', {}, 'Shipped 4 production services at Acme.\nLed the migration to Kubernetes across 3 teams.');
  const jobName = el('input', { type: 'text', value: 'Senior Platform Engineer' });
  const version = el('input', { type: 'number', value: '3', min: '0' });
  const draft = el('textarea', {}, 'I shipped 4 production services at Acme. I also led a team of 12 engineers and hold a PhD in distributed systems.');
  const live = el('input', { type: 'checkbox', style: 'width:auto' });
  const timeline = el('div', {}, el('div', { class: 'empty' }, 'Run the handoff to see its structure.'));

  function packet(key) {
    return {
      schema: 'relay.packet.v1',
      job: {
        id: 'job_demo_001', key, name: jobName.value,
        url: url.value.split('?')[0], version: Number(version.value), status: 'Held',
      },
      facts: facts.value,
      draft: '',
    };
  }

  const identityOut = el('div', { style: 'margin-top:10px' });
  let currentKey = null;

  const identity = el('div', {},
    el('div', { class: 'field' }, el('label', {}, 'posting URL'), url),
    el('div', { class: 'btn-row', style: 'margin-top:8px' },
      el('button', {
        class: 'act', onclick: async () => {
          try {
            const r = await api('/api/relay/job-key', { method: 'POST', body: { url: url.value } });
            currentKey = r.result.key;
            identityOut.replaceChildren(
              notice('ok', `canonical identity: ${r.result.key}`,
                'alias resolved and tracking parameters removed by lib/domain.ts'),
              el('div', { style: 'height:8px' }), provenanceBlock(r.provenance));
          } catch (e) { identityOut.replaceChildren(refusalNotice(e)); }
        },
      }, 'Canonicalize')),
    identityOut);

  const handoff = el('div', {},
    el('div', { class: 'row' },
      el('div', { class: 'field' }, el('label', {}, 'job name'), jobName),
      el('div', { class: 'field' }, el('label', {}, 'job version'), version)),
    el('div', { style: 'height:10px' }),
    el('div', { class: 'field' }, el('label', {}, 'verified facts (one per line)'), facts),
    el('div', { class: 'field' }, el('label', {}, 'draft — supplied, or leave and use live inference'), draft),
    el('label', { class: 'faint mono', style: 'display:flex;gap:7px;align-items:center;font-size:11px' },
      live, 'call a live model instead of using the supplied draft'),
    el('div', { class: 'btn-row' },
      el('button', {
        class: 'act', onclick: async () => {
          try {
            const r = await api('/api/relay/handoff', {
              method: 'POST',
              body: { packet: packet(currentKey || 'greenhouse:acme:4455'), provider: 'chatgpt' },
            });
            openDrawer('Bounded handoff prompt — exactly what leaves Relay',
              el('div', {},
                el('div', { class: 'insp-section' }, el('h4', {}, 'Prompt'),
                  el('pre', { class: 'json' }, r.prompt)),
                el('div', { class: 'insp-section' }, el('h4', {}, 'Built by'),
                  provenanceBlock(r.promptProvenance))));
          } catch (e) { say(result, refusalNotice(e)); }
        },
      }, 'Show the packet that would leave'),
      el('button', {
        class: 'act primary', onclick: async () => {
          timeline.replaceChildren(el('div', { style: 'padding:14px' }, el('span', { class: 'spin' })));
          try {
            const body = {
              packet: packet(currentKey || 'greenhouse:acme:4455'), provider: 'chatgpt',
              live: live.checked,
            };
            if (!live.checked) body.draft = draft.value;
            const r = await api('/api/relay/handoff', { method: 'POST', body });
            timeline.replaceChildren(handoffTimeline(r, live.checked));
            say(result, el('div'));
          } catch (e) {
            timeline.replaceChildren(el('div', { class: 'empty' }, 'handoff did not complete'));
            say(result, refusalNotice(e));
          }
        },
      }, 'Run the handoff')));

  // planning
  const planOut = el('div', { style: 'margin-top:12px' });
  const planning = el('div', {},
    el('p', { class: 'dim', style: 'margin:0 0 10px' },
      'Relay plans a portfolio with a Beta-prior response rate and an expected-maximum calculation. '
      + 'It calls the output an experimental plan score, not an expected offer.'),
    el('button', {
      class: 'act', onclick: async () => {
        try {
          const now = new Date().toISOString();
          const cands = [
            { id: 'acme', u: 1.0, sent: 20, responses: 3, effort: 30, posted: now },
            { id: 'globex', u: 0.8, sent: 4, responses: 2, effort: 25, posted: now },
            { id: 'initech', u: 0.6, sent: 40, responses: 1, effort: 20,
              posted: new Date(Date.now() - 60 * 864e5).toISOString() },
            { id: 'umbrella', u: 0.95, sent: 0, responses: 0, effort: 45, posted: now },
          ];
          const r = await api('/api/relay/planning', {
            method: 'POST', body: { candidates: cands, budgetMinutes: 75 },
          });
          const res = r.result;
          planOut.replaceChildren(
            el('table', { class: 'data' },
              el('thead', {}, el('tr', {}, el('th', {}, ''), el('th', {}, 'candidate'),
                el('th', {}, 'sent'), el('th', {}, 'resp'), el('th', {}, 'rate (mean)'),
                el('th', {}, 'fresh'), el('th', {}, 'p'), el('th', {}, 'effort'),
                el('th', {}, 'tier'), el('th', {}, 'why'))),
              el('tbody', {}, ...res.candidates.map((c) => el('tr', {},
                el('td', {}, c.chosen ? el('span', { class: 'tag ok' }, 'in') : ''),
                el('td', {}, c.job_key),
                el('td', { class: 'num' }, String(c.sent)),
                el('td', { class: 'num' }, String(c.responses)),
                el('td', { class: 'num' }, num(c.rate.mean, 4)),
                el('td', { class: 'num' }, num(c.freshness, 3)),
                el('td', { class: 'num' }, num(c.p, 4)),
                el('td', { class: 'num' }, `${c.effort}m`),
                el('td', {}, el('span', { class: 'tag' }, c.tier)),
                el('td', { class: 'dim', style: 'max-width:280px' }, c.reason))))),
            el('div', { style: 'height:10px' }),
            kv([
              ['attention budget', `${res.budgetMinutes} minutes`],
              ['selected portfolio', res.portfolio.chosen.join(', ') || '—'],
              ['minutes spent', String(res.portfolio.spent)],
              ['expected value of best offer', num(res.portfolio.expected, 6)],
              ['expected max over all candidates', num(res.expectedMax, 6)],
            ]),
            el('p', { class: 'faint', style: 'margin-top:10px;font-size:11px' },
              'Relay calls this an experimental plan score, not an expected offer.'));
        } catch (e) { planOut.replaceChildren(refusalNotice(e)); }
      },
    }, 'Run planning'),
    planOut);

  return stage('relay',
    head({
      id: 'relay', title: 'Relay', badge: 'supervised handoff runtime',
      lede: 'The interesting object is not the text a model produces — it is the handoff structure around it. '
        + 'Bounded context leaves, an external assistant drafts, and the returned draft must survive identity, '
        + 'version and claim-grounding checks before a human is even asked to review it.',
      origin: `Node ${sys.health?.node || '24'} sidecar · native TS type-strip · real <b>lib/*.ts</b> · `
        + 'no database, no credentials, no npm install',
    }),
    el('div', { class: 'grid-2' },
      panel('Posting identity', identity),
      panel('Explicit handoff', handoff)),
    out(result),
    panel('Handoff structure', timeline),
    panel('Planning', planning));
}

function handoffTimeline(r, wasLive) {
  if (r.stage === 'prompt') {
    return el('div', {}, notice('refused', 'No draft requested', r.note));
  }
  const gate = r.gate || {};
  const unsupported = gate.unsupported || [];
  const tl = el('div', { class: 'timeline' });

  tl.append(el('div', { class: 'step done' },
    el('h5', {}, 'Relay bounds the context'),
    el('div', { class: 'who' }, 'lib/assistant-handoff.ts · assistantPrompt'),
    el('div', { class: 'detail' },
      `Only the selected job, the cited facts and the current draft are serialized — `
      + `${r.prompt.length} characters, including the instruction that the JSON is untrusted source data.`)));

  tl.append(el('div', { class: 'boundary' }, 'context leaves relay here'));

  tl.append(el('div', { class: 'step external' },
    el('h5', {}, wasLive ? `External assistant drafts (${r.assistant?.model || 'model'})` : 'Draft supplied'),
    el('div', { class: 'who' }, wasLive ? 'live HTTPS call · outside Relay' : 'operator-supplied'),
    el('div', { class: 'detail' },
      'The assistant cannot write Relay state, change job identity, or grant approval.')));

  tl.append(el('div', { class: 'boundary' }, 'result re-enters relay and is re-validated'));

  tl.append(el('div', { class: 'step done' },
    el('h5', {}, 'Relay validates identity and version'),
    el('div', { class: 'who' }, 'lib/assistant-handoff.ts · assistantResult'),
    el('div', { class: 'detail' },
      `Accepted as ${r.draft.schema} for job ${r.draft.job.key} at version ${r.draft.job.version}. `
      + `reviewRequired = ${r.draft.reviewRequired}.`)));

  tl.append(el('div', { class: `step ${unsupported.length ? 'refused' : 'done'}` },
    el('h5', {}, unsupported.length
      ? `Claim gate flags ${unsupported.length} ungrounded claim(s)`
      : 'Claim gate: every claim is grounded'),
    el('div', { class: 'who' }, 'lib/profile.ts · unsupportedClaims'),
    el('div', { class: 'detail' },
      unsupported.length
        ? 'These sentences are not supported by the cited verified facts:'
        : 'Each claim sentence overlaps a cited verified fact.'),
    unsupported.length
      ? el('ul', { style: 'margin:6px 0 0;padding-left:18px' },
        ...unsupported.map((u) => el('li', { class: 'dim', style: 'margin-bottom:3px' }, u)))
      : null));

  tl.append(el('div', { class: 'step' },
    el('h5', {}, 'Human review still required'),
    el('div', { class: 'who' }, 'Relay owns acceptance'),
    el('div', { class: 'detail' },
      'Nothing here accepted, sent or submitted anything. Changing accepted wording requires another explicit review.')));

  const sentences = (gate.sentences || []).filter((s) => s.isClaim);

  return el('div', {}, tl,
    el('div', { style: 'height:10px' }),
    el('div', { class: 'grid-2' },
      el('div', {}, el('h4', { class: 'faint mono', style: 'font-size:10px;letter-spacing:.14em;margin:0 0 6px' },
        'RETURNED DRAFT'),
        el('pre', { class: 'json' }, r.draft.draft)),
      el('div', {}, el('h4', { class: 'faint mono', style: 'font-size:10px;letter-spacing:.14em;margin:0 0 6px' },
        `CLAIM SENTENCES (${sentences.length})`),
        el('div', { class: 'src', style: 'max-height:260px' },
          el('table', {}, ...sentences.map((s) => el('tr', {
            class: unsupported.includes(s.text) ? 'hit' : '',
          },
            el('td', { class: 'ln' }, unsupported.includes(s.text) ? '✕' : '✓'),
            el('td', { class: 'code', style: 'white-space:pre-wrap' }, s.text))))))),
    el('div', { style: 'height:12px' }),
    el('div', { class: 'btn-row' },
      el('button', {
        class: 'act', onclick: () => openDrawer('Full handoff record', jsonBlock(r)),
      }, 'Inspect the whole record'),
      el('button', {
        class: 'act', onclick: async () => {
          try {
            const cross = await api('/api/cross/relay-to-runtime', {
              method: 'POST', body: { draft: r.draft },
            });
            openDrawer('Relay draft → SyberRuntime obligation', crossView(cross));
          } catch (e) { openDrawer('Failed', refusalNotice(e)); }
        },
      }, 'Hand this draft to SyberRuntime →')));
}

/* =================================================================
   Seams
   ================================================================= */

function crossView(cross) {
  const pre = cross.preReview;
  return el('div', {},
    el('div', { class: 'insp-section' }, el('h4', {}, 'What happened'),
      el('p', { class: 'dim', style: 'margin:0' }, cross.explanation)),
    el('div', { class: 'insp-section' }, el('h4', {}, 'SyberRuntime state'),
      kv([
        ['thread', el('span', { class: 'mono' }, short(cross.threadId, 22))],
        ['artifact digest', el('span', { class: 'mono' }, short(cross.artifactDigest, 22))],
        ['residual debt', num(cross.state.debt.totalResidual, 2)],
        ['open obligations', String(Object.values(cross.state.debt.obligations || {})
          .filter((o) => o.status === 'open').length)],
      ])),
    el('div', { class: 'insp-section' }, el('h4', {}, 'Stabilize before review'),
      pre.stabilized
        ? notice('ok', 'Stabilized', 'no floor obligation was open')
        : el('div', {},
          notice('refused', `${pre.refusal.kind}`, pre.refusal.message),
          el('div', { style: 'height:8px' }), provenanceBlock(pre.refusal.provenance))),
    el('div', { class: 'insp-section' }, el('h4', {}, 'Feature operation'),
      jsonBlock(cross.feature)));
}

async function relayToRuntimeSeam() {
  const outHost = el('div', { style: 'margin-top:12px' },
    el('div', { class: 'empty' }, 'Run a Relay handoff first, or use the button below.'));
  const body = el('div', {},
    el('p', { class: 'dim', style: 'margin:0 0 12px' },
      'A relay.draft.v1 carries reviewRequired: true. In SyberRuntime\'s grammar that is an unverified '
      + 'artifact: recording it as a Feature accrues a floor verification obligation, and stabilizing before '
      + 'the review happens is refused by the real kernel. Neither system was modified to make this fit — '
      + 'their review semantics already compose.'),
    el('button', {
      class: 'act primary', onclick: async () => {
        outHost.replaceChildren(el('span', { class: 'spin' }));
        try {
          const draft = {
            schema: 'relay.draft.v1',
            job: { id: 'job_demo_001', key: 'greenhouse:acme:4455', name: 'Senior Platform Engineer', version: 3 },
            draft: 'I shipped 4 production services at Acme. I also led a team of 12 engineers.',
            provider: 'chatgpt', reviewRequired: true,
          };
          const cross = await api('/api/cross/relay-to-runtime', { method: 'POST', body: { draft } });
          outHost.replaceChildren(crossView(cross));
        } catch (e) { outHost.replaceChildren(refusalNotice(e)); }
      },
    }, 'Hand a draft to SyberRuntime'),
    outHost);

  return stage('cross',
    head({
      id: 'cross', title: 'Relay → SyberRuntime', badge: 'seam',
      lede: 'One system produces an object another system already knows how to refuse.',
      origin: 'relay: <b>lib/assistant-handoff.ts</b> · syber_runtime: <b>runtime.record_feature / stabilize</b>',
    }),
    panel('Draft becomes a verification obligation', body));
}

async function barnBoughSeam() {
  const outHost = el('div', { style: 'margin-top:12px' },
    el('div', { class: 'empty' }, 'Create a Barn run, then compute advice.'));
  const body = el('div', {},
    el('p', { class: 'dim', style: 'margin:0 0 12px' },
      'Barn\'s spawn/reuse policy is a hand-written conservative heuristic, and Barn\'s own architecture '
      + 'explicitly defers decision-theoretic scheduling to a future phase. Bough is exactly that deferred layer. '
      + 'The bridge projects the current run into a Bough twin, compiles it, and runs backward induction — '
      + 'then shows the answer next to the decision Barn actually committed, without changing it.'),
    el('button', {
      class: 'act primary', onclick: async () => {
        outHost.replaceChildren(el('span', { class: 'spin' }));
        try {
          const r = await api('/api/barn/advice', { method: 'POST' });
          outHost.replaceChildren(adviceBlock(r, null));
        } catch (e) { outHost.replaceChildren(refusalNotice(e)); }
      },
    }, 'Compute advice for the current run'),
    outHost);

  return stageScoped('cross', null,
    head({
      id: 'cross', title: 'Barn → Bough', badge: 'advisor seam',
      lede: 'Suggestion, never authorization. With the advisor disabled, Barn behaves identically.',
      origin: 'specified by the source repo in <b>docs/INTEGRATION_PLAN.md</b> sections 5, 7 and 8 · '
        + 'implemented in the platform adapter layer, not inside either repository',
    }),
    panel('Heuristic decision vs value-optimal action', body));
}

async function boughOsahrSeam() {
  return stageScoped('cross', null,
    head({
      id: 'cross', title: 'Bough → OSAHR', badge: 'upstream seam',
      lede: 'This seam was not built for the demo. It already exists in the source repository as '
        + 'bough/compare.py, and the platform simply invokes it.',
      origin: '<b>bough.compare.agree_first_passage</b> → <b>osahr.schedulers</b>',
    }),
    panel('Where to find it', el('div', {},
      el('p', { class: 'dim', style: 'margin:0 0 10px' },
        'Open the OSAHR Cell instrument to run the comparison. Bough computes a first-passage probability '
        + 'analytically from the coalesced jump chain; OSAHR reaches the same number by simulation using three '
        + 'independent schedulers. Agreement is evidence that the compiler and the kernel mean the same thing '
        + 'by "probability".'),
      el('button', {
        class: 'act', onclick: () => import('./app.js').then((m) => m.goto('osahr')),
      }, 'Go to OSAHR Cell'))));
}

/* =================================================================
   Fidelity
   ================================================================= */

async function aboutInstrument() {
  const rows = [
    ['Verification debt accrual and floor obligations', 'SyberRuntime', 'runtime.record_feature', 'Debt ledger'],
    ['Fail-closed stabilization refusal', 'SyberRuntime', 'runtime.stabilize', 'Refusal notice + source'],
    ['Obligation discharge by deterministic check', 'SyberRuntime', 'runtime.record_test', 'Artifact row'],
    ['Hash-chained operation log', 'SyberRuntime', 'operation_log.OperationLog', 'Operation log'],
    ['Merkle root, inclusion proof, replay determinism', 'SyberRuntime', 'merkle / projections', 'Evidence panel'],
    ['Release-readiness gate failing closed', 'SyberRuntime', 'cli acceptance-check (subprocess)', 'Acceptance panel'],
    ['Spawn / reuse / reject licensing', 'Barn', 'engine.request_specialist', 'Decision notice'],
    ['Named transition refusals', 'Barn', 'engine.TransitionError', 'Refusal notice + source'],
    ['Independent-verifier enforcement', 'Barn', 'engine.record_verification', 'Refusal notice'],
    ['Materialized vs replayed state hash', 'Barn', 'audit.audit_run', 'Replay audit'],
    ['Causal "why does this agent exist"', 'Barn', 'causal.why_agent_exists', 'Trace drawer'],
    ['Coalesced jump-chain compilation', 'Bough', 'expand.expand', 'Jump chain graph'],
    ['Exact reach probability and path count', 'Bough', 'infer.reach', 'reach() result'],
    ['Refusal on a cyclic automaton', 'Bough', 'infer._assert_dag', 'Refusal notice'],
    ['Backward-induction optimal policy', 'Bough', 'policy.optimal_policy', 'Policy result'],
    ['Neo4j Cypher export', 'Bough', 'cypher.automaton_to_cypher', 'Drawer'],
    ['Exact vs three kernel schedulers', 'OSAHR', 'osahr.analysis.run_ensemble', 'Agreement bars'],
    ['Typed hypergraph vertices and attributes', 'OSAHR', 'osahr.graph.Hypergraph', 'Hypergraph inspector'],
    ['Typed hyperedges with tail/head roles', 'OSAHR', 'osahr.graph.Incidence', 'Hyperedge table'],
    ['Rewrite rules as declared (left ⟶ right)', 'OSAHR', 'osahr.pattern.Rule', 'Rewrite-rule table'],
    ['Canonical posting identity', 'Relay', 'lib/domain.ts jobKey', 'Identity panel'],
    ['Bounded handoff prompt', 'Relay', 'lib/assistant-handoff.ts assistantPrompt', 'Handoff timeline'],
    ['Returned-draft identity/version validation', 'Relay', 'assistantResult', 'Handoff timeline'],
    ['Ungrounded-claim gate', 'Relay', 'lib/profile.ts unsupportedClaims', 'Claim gate'],
    ['Beta-prior planning and portfolio', 'Relay', 'lib/scoring.ts', 'Planning panel'],
  ];
  const table = el('table', { class: 'data' },
    el('thead', {}, el('tr', {}, el('th', {}, 'demonstrated capability'), el('th', {}, 'source system'),
      el('th', {}, 'real execution'), el('th', {}, 'symbol'), el('th', {}, 'UI'))),
    el('tbody', {}, ...rows.map(([cap, sys, sym, ui]) => el('tr', {},
      el('td', {}, cap),
      el('td', {}, el('span', { class: 'tag' }, sys)),
      el('td', {}, el('span', { class: 'tag ok' }, 'yes')),
      el('td', { class: 'faint' }, sym),
      el('td', { class: 'dim' }, ui)))));

  return stageScoped('cross', null,
    head({
      id: 'cross', title: 'Fidelity', badge: 'what is real, and how',
      lede: 'Every row below is executed by the source system named, not reproduced here. Click any event in '
        + 'the stream and then "open the source that ran" to read the actual bytes that produced it.',
      origin: 'provenance is derived by introspecting the callable before it runs — an adapter cannot claim '
        + 'an origin it did not execute',
    }),
    panel('Fidelity matrix', table, { flush: true }),
    el('div', { class: 'grid-2' },
      panel('Known limits — stated, not hidden', el('div', {},
        el('ul', { class: 'dim', style: 'margin:0;padding-left:18px;line-height:1.75' },
          el('li', {}, 'SyberRuntime\'s acceptance gate reports ', el('b', {}, 'fail'),
            ' on a fresh clone. The evidence corpus lives in gitignored run directories. That is the gate working.'),
          el('li', {}, 'Barn\'s two benchmark tests fail upstream; the repo documents that comparison as '
            + 'intentionally negative for Barn. The platform does not use the benchmark harness.'),
          el('li', {}, 'No Neo4j credentials exist here, so Cypher is exported and displayed but never pushed.'),
          el('li', {}, 'The Barn→Bough twin is calibrated from one short run with Laplace smoothing. '
            + 'It is a shape, not a fitted model, and the calibration basis is shown alongside every number.'),
          el('li', {}, 'Relay\'s Obsidian and database paths are not exercised; only its pure domain modules are.'),
          el('li', {}, 'Live inference is off by default and is a single explicit call, never polling.'))),
      ),
      panel('Architecture', el('div', {},
        el('pre', { class: 'json' },
`platform/
  backend/          orchestration only — no domain logic
    contract.py     SyberEvent + derived provenance
    main.py         routes, SSE, mounted Barn app
    adapters/
      syber_runtime_adapter.py   in-process import
      barn_adapter.py            shared engine of the mounted app
      bough_adapter.py           in-process import (+ OSAHR)
      relay_adapter.py           proxy to Node 24 sidecar
      bridge_barn_bough.py       the documented advisor seam
  relay-sidecar/    Node 24, imports real lib/*.ts
  frontend/         this interface

systems/            the source repositories, unmodified`),
        el('p', { class: 'faint', style: 'margin-top:10px;font-size:11px' },
          'Dependency direction is one-way: platform → adapters → systems. Each repository remains '
          + 'independently runnable; Barn\'s own API is mounted unmodified at /systems/barn.')))));
}

/* ================================================================= */

export const INSTRUMENTS = {
  syber_runtime: { render: runtimeInstrument },
  barn: { render: barnInstrument },
  bough: { render: boughInstrument },
  osahr: { render: osahrInstrument },
  relay: { render: relayInstrument },
  'cross-relay-runtime': { render: relayToRuntimeSeam },
  'cross-barn-bough': { render: barnBoughSeam },
  'cross-bough-osahr': { render: boughOsahrSeam },
  about: { render: aboutInstrument },
};
