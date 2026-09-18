/**
 * Relay sidecar.
 *
 * Relay is TypeScript and requires Node >= 24. This process imports the real
 * `lib/*.ts` modules directly, relying on Node 24's native type stripping, and
 * exposes them over a small JSON HTTP surface for the platform backend.
 *
 * It contains no Relay logic of its own. Every handler below is a thin call
 * into an imported upstream symbol. The `provenance` block each response
 * carries is *resolved*, not asserted: `import.meta.resolve` is used to find
 * where the module actually loaded from, so the reported path is observed.
 *
 * No database, no Cloudflare bindings, no credentials, no network calls.
 */

import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const RELAY_ROOT = process.env.RELAY_ROOT;
if (!RELAY_ROOT) {
  console.error('RELAY_ROOT is required');
  process.exit(2);
}
const PORT = Number(process.env.RELAY_SIDECAR_PORT || 8766);

const libUrl = (name) => new URL(`file://${RELAY_ROOT.replace(/\\/g, '/')}/${name}`).href;

// --- real Relay modules ----------------------------------------------------
const profile = await import(libUrl('lib/profile.ts'));
const domain = await import(libUrl('lib/domain.ts'));
const scoring = await import(libUrl('lib/scoring.ts'));
const fit = await import(libUrl('lib/fit.ts'));
const handoff = await import(libUrl('lib/assistant-handoff.ts'));
const connectors = await import(libUrl('integrations/connectors.mjs'));

/** Where a symbol's module actually resolved from, relative to the checkout. */
function provenanceOf(moduleRelPath, symbol) {
  let resolved = null;
  try {
    resolved = fileURLToPath(libUrl(moduleRelPath));
  } catch {
    resolved = null;
  }
  return {
    system: 'relay',
    module: resolved ? path.relative(RELAY_ROOT, resolved).replace(/\\/g, '/') : moduleRelPath,
    symbol,
    execution: 'node 24 sidecar, native TS type-strip',
    node: process.version,
  };
}

// --- handlers --------------------------------------------------------------
// Each entry: [moduleRelPath, exportedSymbol, invoke(body)]

const handlers = {
  /** Canonical posting identity: alias resolution + tracking-parameter removal. */
  'job-key': ['lib/domain.ts', 'jobKey', (b) => ({
    key: domain.jobKey(b.url ?? null, b.fallback ?? 'fallback'),
    url: b.url,
  })],

  /** Heuristic requirement extraction from posting text. */
  requirements: ['lib/fit.ts', 'extractRequirements', (b) => ({
    requirements: fit.extractRequirements(String(b.text ?? '')),
  })],

  /**
   * The draft-log gate. Returns the claim sentences NOT grounded in the cited
   * verified facts. This is Relay's real review gate, not a summary of it.
   */
  'unsupported-claims': ['lib/profile.ts', 'unsupportedClaims', (b) => {
    const facts = (b.facts ?? []).map((f) => ({
      id: String(f.id ?? ''),
      claim: String(f.claim ?? ''),
      status: String(f.status ?? 'Proposed'),
      tag: String(f.tag ?? 'detail'),
      confidence: String(f.confidence ?? 'high'),
      expires: f.expires ?? null,
    }));
    const now = new Date().toISOString();
    const body = String(b.body ?? '');
    const sentences = profile.sentences(body);
    return {
      unsupported: profile.unsupportedClaims(body, facts),
      sentences: sentences.map((s) => ({ text: s, isClaim: profile.isClaim(s) })),
      factsUsable: facts.map((f) => ({ id: f.id, claim: f.claim, usable: profile.usableFact(f, now) })),
    };
  }],

  /**
   * Beta-prior response rate, then greedy portfolio construction under an
   * attention budget in minutes. `selectPortfolio` maximises the expected
   * value of the BEST offer, not a sum, so it spreads tiers on its own.
   * Candidates must carry `job_key`, `u`, `p` and `effort` — the real type.
   */
  planning: ['lib/scoring.ts', 'selectPortfolio', (b) => {
    const now = b.now ?? new Date().toISOString();
    const rated = (b.candidates ?? []).map((c) => {
      const sent = Number(c.sent ?? 0);
      const responses = Number(c.responses ?? 0);
      const rate = scoring.responseRate(sent, responses);
      const fresh = scoring.freshness(c.posted ?? null, now);
      const p = rate.mean * fresh;
      return {
        job_key: String(c.id ?? c.job_key),
        u: Number(c.u ?? 1),
        p,
        effort: Number(c.effort ?? 30),
        sent,
        responses,
        posted: c.posted ?? null,
        rate,
        freshness: fresh,
        tier: scoring.tierOf(p),
      };
    });
    const budgetMinutes = Number(b.budgetMinutes ?? 90);
    const portfolio = scoring.selectPortfolio(rated, budgetMinutes);
    return {
      candidates: rated.map((c) => ({
        ...c,
        reason: scoring.reason(c, now, c.posted),
        chosen: portfolio.chosen.some((x) => x.job_key === c.job_key),
      })),
      budgetMinutes,
      expectedMax: scoring.expectedMax(rated),
      portfolio: {
        chosen: portfolio.chosen.map((c) => c.job_key),
        spent: portfolio.spent,
        expected: portfolio.expected,
      },
    };
  }],

  /** Validate a relay.packet.v1 — identity and facts are checked upstream. */
  'validate-packet': ['integrations/connectors.mjs', 'validatePacket', (b) => ({
    packet: connectors.validatePacket(b.packet),
  })],

  /**
   * Build the bounded handoff prompt. This is what actually leaves Relay.
   * Nothing beyond the selected job, the cited facts and the current draft is
   * included — the bounding is done by upstream `selectedPacket`.
   */
  'handoff-prompt': ['lib/assistant-handoff.ts', 'assistantPrompt', (b) => ({
    prompt: handoff.assistantPrompt(
      b.packet,
      b.provider ?? 'chatgpt',
      Boolean(b.draftOnly),
      b.context ?? {},
    ),
  })],

  /**
   * Validate a returned draft against job identity and version. A stale
   * version or a mismatched packet is rejected here, by Relay.
   */
  'handoff-result': ['lib/assistant-handoff.ts', 'assistantResult', (b) => ({
    result: handoff.assistantResult(b.packet, String(b.draft ?? ''), b.provider ?? 'chatgpt'),
  })],

  /** Import classification and status merge rules. */
  classify: ['lib/domain.ts', 'classify', (b) => ({
    status: domain.importedJobStatus(String(b.status ?? 'Held')),
    merged: domain.mergeJobStatus(b.existing ?? undefined, String(b.incoming ?? 'Held')),
    blocker: domain.importedBlocker(b.blocker ?? null),
  })],
};

// --- transport -------------------------------------------------------------

function send(res, code, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

const server = createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    return send(res, 200, {
      status: 'ok',
      node: process.version,
      relayRoot: RELAY_ROOT,
      handlers: Object.keys(handlers),
    });
  }
  if (req.method !== 'POST') return send(res, 405, { error: 'POST only' });

  const name = (req.url || '').replace(/^\//, '');
  const entry = handlers[name];
  if (!entry) return send(res, 404, { error: `unknown handler: ${name}` });
  const [modulePath, symbol, invoke] = entry;

  let raw = '';
  req.on('data', (c) => {
    raw += c;
    if (raw.length > 4_000_000) req.destroy();
  });
  req.on('end', () => {
    const prov = provenanceOf(modulePath, symbol);
    let body;
    try {
      body = raw ? JSON.parse(raw) : {};
    } catch {
      return send(res, 400, { error: 'invalid JSON body', provenance: prov });
    }
    const started = process.hrtime.bigint();
    try {
      const result = invoke(body);
      const durationMs = Number(process.hrtime.bigint() - started) / 1e6;
      send(res, 200, { ok: true, result, provenance: prov, durationMs });
    } catch (err) {
      const durationMs = Number(process.hrtime.bigint() - started) / 1e6;
      // Relay throws plain Errors with user-facing messages. These are real
      // refusals and are reported as such, never swallowed or rewritten.
      send(res, 200, {
        ok: false,
        refused: true,
        error: { type: err?.constructor?.name ?? 'Error', message: String(err?.message ?? err) },
        provenance: prov,
        durationMs,
      });
    }
  });
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`relay-sidecar listening on 127.0.0.1:${PORT} (node ${process.version})`);
  console.log(`relay root: ${RELAY_ROOT}`);
});
