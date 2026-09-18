/* The OSAHR 6G semantic twin, drawn.

   Every node, edge, number and colour here is read from a live osahr.Runtime
   snapshot. Positions are the only thing this file invents — the topology is
   fixed (4 UEs, 2 gNBs, 2 MEC nodes), so they are laid out in columns.

   The thing worth watching is Transit: a single hyperedge binding a robot, a
   task, an access point and an execution node in one typed relation. It is
   drawn as a junction with four spokes because that is what it is; a pairwise
   graph could not hold it. */

import { el, jsonBlock, openDrawer, num, short } from './app.js';

const NS = 'http://www.w3.org/2000/svg';
const mk = (tag, attrs = {}, text) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    n.setAttribute(k, String(v));
  }
  if (text !== undefined) n.textContent = text;
  return n;
};

const W = 1120;
const COL = { ue: 120, gnb: 470, edge: 880 };

/** Fixed column layout; the topology never changes shape, only its bindings do. */
function layout(snapshot) {
  const pos = new Map();
  const byType = { UE: [], GNB: [], EdgeNode: [] };
  for (const v of Object.values(snapshot.vertices)) {
    if (byType[v.type]) byType[v.type].push(v);
  }
  for (const k of Object.keys(byType)) {
    byType[k].sort((a, b) => String(a.attributes.name).localeCompare(String(b.attributes.name)));
  }
  const place = (list, x, top, gap) =>
    list.forEach((v, i) => pos.set(v.id, { x, y: top + i * gap, v }));

  place(byType.UE, COL.ue, 90, 86);
  place(byType.GNB, COL.gnb, 150, 170);
  place(byType.EdgeNode, COL.edge, 140, 190);
  const lowest = Math.max(...[...pos.values()].map((p) => p.y), 260);
  const H = lowest + 92;
  return { pos, byType, H };
}

export function networkView(snapshot) {
  const { pos, byType, H } = layout(snapshot);
  const svg = mk('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'g6-svg' });

  // ---- column captions
  for (const [x, label] of [[COL.ue, 'ROBOT UEs'], [COL.gnb, 'RAN / gNB'], [COL.edge, 'MEC EDGE NODES']]) {
    svg.append(mk('text', { x, y: 34, class: 'g6-col', 'text-anchor': 'middle' }, label));
  }

  const V = (id) => pos.get(id);
  const edgesByType = (t) => snapshot.edges.filter((e) => e.type === t);
  const roleVertex = (e, role) => {
    const hit = [...e.tail, ...e.head].find((i) => i.role === role);
    return hit ? hit.vertex : null;
  };

  // ---- Neighbor (gNB <-> gNB): the mobility topology
  for (const e of edgesByType('Neighbor')) {
    const a = V(roleVertex(e, 'from_gnb')); const b = V(roleVertex(e, 'to_gnb'));
    if (!a || !b) continue;
    svg.append(mk('path', {
      d: `M ${a.x} ${a.y + 26} C ${a.x - 54} ${(a.y + b.y) / 2}, ${b.x - 54} ${(a.y + b.y) / 2}, ${b.x} ${b.y - 26}`,
      class: 'g6-neighbor',
    }));
  }

  // ---- Path (gNB -> EdgeNode): opacity carries link_quality
  for (const e of edgesByType('Path')) {
    const a = V(roleVertex(e, 'gnb')); const b = V(roleVertex(e, 'edge'));
    if (!a || !b) continue;
    const q = Number(e.attributes.link_quality ?? 1);
    const line = mk('path', {
      d: `M ${a.x + 62} ${a.y} C ${a.x + 200} ${a.y}, ${b.x - 200} ${b.y}, ${b.x - 74} ${b.y}`,
      class: 'g6-path', 'stroke-opacity': (0.14 + q * 0.5).toFixed(2),
      'stroke-width': (0.8 + q * 1.5).toFixed(2),
    });
    line.append(mk('title', {}, `Path ${e.attributes.name} · link_quality ${q}`));
    svg.append(line);
  }

  // ---- Association (UE -> gNB): rewired by handover
  for (const e of edgesByType('Association')) {
    const a = V(roleVertex(e, 'ue')); const b = V(roleVertex(e, 'gnb'));
    if (!a || !b) continue;
    svg.append(mk('path', {
      d: `M ${a.x + 54} ${a.y} C ${a.x + 150} ${a.y}, ${b.x - 150} ${b.y}, ${b.x - 62} ${b.y}`,
      class: 'g6-assoc', 'data-eid': e.id,
    }));
  }

  // ---- Transit: the 4-ary hyperedge, drawn as a junction with spokes
  const transits = edgesByType('Transit');
  transits.forEach((e, i) => {
    const ue = V(roleVertex(e, 'source'));
    const gnb = V(roleVertex(e, 'gnb'));
    const edge = V(roleVertex(e, 'edge'));
    const taskId = roleVertex(e, 'task');
    const task = snapshot.vertices[taskId];
    if (!ue || !gnb || !edge) return;

    // Spread the junctions along the RAN -> MEC corridor so overlapping
    // bindings stay separable.
    const lane = COL.gnb + 110 + (i % 4) * 52;
    const hx = Math.min(lane, COL.edge - 130);
    const hy = (ue.y + gnb.y + edge.y) / 3 + (((i * 37) % 7) - 3) * 16;
    const critical = task && task.attributes.kind === 'critical';
    const kindCls = critical ? 'critical' : 'background';
    const cls = `g6-transit ${kindCls}`;

    const g = mk('g', { class: `g6-hyper ${kindCls}` });
    // three spokes: the binding is one relation over four entities
    for (const [p, role] of [[ue, 'source'], [gnb, 'gnb'], [edge, 'edge']]) {
      g.append(mk('line', { x1: hx, y1: hy, x2: p.x, y2: p.y, class: `${cls} spoke-${role}` }));
    }
    g.append(mk('circle', { cx: hx, cy: hy, r: 13, class: `g6-hub-halo ${kindCls}` }));
    g.append(mk('circle', { cx: hx, cy: hy, r: 8.5, class: `g6-hub ${kindCls}` }));
    g.append(mk('text', { x: hx, y: hy + 3, class: `g6-hubkind ${kindCls}`, 'text-anchor': 'middle' },
      critical ? 'C' : 'b'));
    if (task) {
      g.append(mk('text', { x: hx, y: hy - 17, class: 'g6-hublabel', 'text-anchor': 'middle' },
        `u ${task.attributes.utility} · d ${task.attributes.deadline}s`));
    }
    g.addEventListener('click', () => openDrawer('Transit hyperedge', el('div', {},
      el('p', { class: 'dim', style: 'margin:0 0 10px' },
        'One typed relation binding four entities at once: the robot that produced the task, '
        + 'the task itself, the access point it is associated with, and the edge node chosen to '
        + 'execute it. A pairwise edge cannot express this.'),
      jsonBlock({ edge: e, task: task || null }))));
    svg.append(g);
  });

  // ---- Queued tasks, stacked on their robot
  const queued = new Map();
  for (const e of edgesByType('Queued')) {
    const ue = roleVertex(e, 'source');
    if (!queued.has(ue)) queued.set(ue, []);
    queued.get(ue).push(snapshot.vertices[roleVertex(e, 'task')]);
  }

  // ---- UE nodes
  for (const v of byType.UE) {
    const p = V(v.id);
    const g = mk('g', { class: 'g6-node' });
    g.append(mk('rect', { x: p.x - 54, y: p.y - 19, width: 108, height: 38, rx: 5, class: 'g6-ue' }));
    g.append(mk('text', { x: p.x, y: p.y - 3, class: 'g6-name', 'text-anchor': 'middle' },
      String(v.attributes.name)));
    g.append(mk('text', { x: p.x, y: p.y + 10, class: 'g6-sub', 'text-anchor': 'middle' },
      `crit ${v.attributes.critical_rate}/s · bg ${v.attributes.background_rate}/s`));
    const q = queued.get(v.id) || [];
    q.slice(0, 5).forEach((t, i) => {
      g.append(mk('rect', {
        x: p.x - 54 + i * 13, y: p.y + 22, width: 10, height: 10, rx: 2,
        class: `g6-queued ${t && t.attributes.kind === 'critical' ? 'critical' : 'background'}`,
      }));
    });
    if (q.length) {
      g.append(mk('text', { x: p.x + 24, y: p.y + 31, class: 'g6-sub' }, `${q.length} queued`));
    }
    g.addEventListener('click', () => openDrawer('UE', jsonBlock(v)));
    svg.append(g);
  }

  // ---- gNB nodes
  for (const v of byType.GNB) {
    const p = V(v.id);
    const g = mk('g', { class: 'g6-node' });
    g.append(mk('rect', { x: p.x - 62, y: p.y - 22, width: 124, height: 44, rx: 5, class: 'g6-gnb' }));
    g.append(mk('text', { x: p.x, y: p.y + 4, class: 'g6-name', 'text-anchor': 'middle' },
      String(v.attributes.name)));
    g.addEventListener('click', () => openDrawer('gNB', jsonBlock(v)));
    svg.append(g);
  }

  // ---- EdgeNode: availability, load against capacity
  for (const v of byType.EdgeNode) {
    const p = V(v.id);
    const a = v.attributes;
    const down = a.available === false;
    const load = Number(a.load || 0); const cap = Number(a.capacity || 1);
    const g = mk('g', { class: 'g6-node' });
    g.append(mk('rect', {
      x: p.x - 74, y: p.y - 42, width: 172, height: 84, rx: 6,
      class: `g6-edge${down ? ' down' : ''}`,
    }));
    g.append(mk('text', { x: p.x - 62, y: p.y - 22, class: 'g6-name' }, String(a.name)));
    if (down) {
      g.append(mk('text', { x: p.x + 84, y: p.y - 22, class: 'g6-down', 'text-anchor': 'end' }, 'OUTAGE'));
    }
    g.append(mk('text', { x: p.x - 62, y: p.y - 7, class: 'g6-sub' },
      `rel ${a.reliability} · fid ${a.fidelity} · E ${a.energy_cost}`));
    g.append(mk('text', { x: p.x - 62, y: p.y + 7, class: 'g6-sub' },
      `service ${a.service_rate}/s`));
    // load bar
    g.append(mk('rect', { x: p.x - 62, y: p.y + 16, width: 148, height: 7, rx: 3, class: 'g6-bar-bg' }));
    g.append(mk('rect', {
      x: p.x - 62, y: p.y + 16, width: Math.max(0, Math.min(1, load / cap)) * 148, height: 7, rx: 3,
      class: `g6-bar${load >= cap ? ' full' : ''}`,
    }));
    g.append(mk('text', { x: p.x - 62, y: p.y + 35, class: 'g6-sub' }, `load ${load} / ${cap}`));
    g.addEventListener('click', () => openDrawer('EdgeNode', jsonBlock(v)));
    svg.append(g);
  }

  const legend = el('div', { class: 'g6-legend' },
    lg('assoc', 'Association  UE → gNB'),
    lg('path', 'Path  gNB → MEC'),
    lg('neighbor', 'Neighbor  gNB ↔ gNB'),
    lg('crit', 'Transit (critical task)'),
    lg('bg', 'Transit (background task)'),
    el('span', { class: 'g6-legend-note' },
      `${transits.length} task(s) in flight · Transit is a 4-ary hyperedge — click one`));

  return el('div', {}, el('div', { class: 'g6-canvas' }, svg), legend);
}

function lg(kind, label) {
  return el('span', { class: 'g6-lg' }, el('i', { class: `g6-sw ${kind}` }), label);
}

/** A run clock: the outage window and the arrival cutoff are real config. */
export function timeline(snapshot) {
  const h = snapshot.horizon || 60;
  const pct = (t) => `${Math.max(0, Math.min(1, t / h)) * 100}%`;
  return el('div', { class: 'g6-timeline' },
    el('div', { class: 'g6-tl-track' },
      el('div', {
        class: 'g6-tl-outage',
        style: `left:${pct(snapshot.outage.start)};width:${
          ((snapshot.outage.end - snapshot.outage.start) / h) * 100}%`,
      }),
      el('div', { class: 'g6-tl-stop', style: `left:${pct(snapshot.arrivalsStop)}` }),
      el('div', { class: 'g6-tl-now', style: `left:${pct(snapshot.time)}` })),
    el('div', { class: 'g6-tl-marks' },
      el('span', {}, '0s'),
      el('span', { class: 'g6-tl-legend' },
        `outage ${snapshot.outage.start}–${snapshot.outage.end}s · arrivals stop ${snapshot.arrivalsStop}s`),
      el('span', {}, `${h}s`)));
}

/** Sufficient statistics, straight off runtime.memory. */
export function statsView(snapshot) {
  const z = snapshot.memory || {};
  const d = snapshot.derived || {};
  const cell = (label, value, hint) => el('div', { class: 'g6-stat' },
    el('div', { class: 'g6-stat-v' }, value),
    el('div', { class: 'g6-stat-k' }, label),
    hint ? el('div', { class: 'g6-stat-h' }, hint) : null);

  return el('div', {},
    el('div', { class: 'g6-stats' },
      cell('goal utility ratio', d.goalUtilityRatio === null || d.goalUtilityRatio === undefined
        ? '—' : num(d.goalUtilityRatio, 3), 'timely value / generated value'),
      cell('critical success', d.criticalSuccessRate === null || d.criticalSuccessRate === undefined
        ? '—' : num(d.criticalSuccessRate, 3), 'critical tasks inside deadline'),
      cell('timely tasks', d.timelyTaskRate === null || d.timelyTaskRate === undefined
        ? '—' : num(d.timelyTaskRate, 3), 'all tasks inside deadline'),
      cell('energy', num(Number(z.energy || 0), 2), 'accumulated edge cost')),
    el('div', { class: 'g6-ztable' },
      ...['generated', 'generated_critical', 'delivered', 'timely', 'timely_critical',
        'reroutes', 'handovers', 'bytes_delivered'].filter((k) => k in z).map((k) =>
        el('div', { class: 'g6-zrow' },
          el('span', { class: 'g6-zk' }, k),
          el('span', { class: 'g6-zv' }, num(Number(z[k]), 2))))));
}

/** Per-event feed: rule, when, and the hazard it won on. */
export function eventFeed(events) {
  if (!events || !events.length) {
    return el('div', { class: 'empty' }, 'No kernel events yet. Step the twin.');
  }
  return el('div', { class: 'g6-feed' }, ...events.map((e) => {
    const share = e.hazard && e.totalActivity ? e.hazard / e.totalActivity : null;
    return el('div', {
      class: `g6-ev rule-${e.rule}${e.isRule === false ? ' external' : ''}`,
      onclick: () => openDrawer(`${e.rule} · event ${e.index}`, el('div', {},
        e.ruleNote ? el('p', { class: 'dim', style: 'margin:0 0 10px' }, e.ruleNote) : null,
        jsonBlock(e))),
    },
      el('div', { class: 'g6-ev-top' },
        el('span', { class: 'g6-ev-rule' },
          e.isRule === false ? `⇥ ${e.rule}` : e.rule),
        el('span', { class: 'g6-ev-t' }, `t=${num(e.time, 3)}s`)),
      el('div', { class: 'g6-ev-meta' },
        `Δt ${num(e.deltaTime, 4)}s`,
        e.hazard !== null && e.hazard !== undefined
          ? `  ·  hazard ${num(e.hazard, 2)}` : '',
        share !== null ? `  ·  ${(share * 100).toFixed(1)}% of activity` : '',
        e.created.edges.length ? `  ·  +${e.created.edges.map((x) => x.type).join(',')}` : '',
        e.deleted.edges.length ? `  ·  −${e.deleted.edges.map((x) => x.type).join(',')}` : ''));
  }));
}
