// JAI's prompt checks (Wave 6): promptfoo (MIT) behind a small API for JAI's backend.
//
// The backend sends a promptfoo configuration built from JAI's real, current prompts (the voice's instructions, an
// agent's instructions, including any self-evolved change before it is applied) with test cases for the rules that
// must always hold: hard boundaries, first person, looking the outside world up. promptfoo runs each case and grades
// it, and this service returns what passed and failed. Every model call, the graders' included, goes to JAI's model
// gateway with JAI's gateway token, so it is priced and inside the daily spending limit; promptfoo has no provider
// key and no route to the internet. One check runs at a time.
'use strict';

const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFile } = require('child_process');

const PORT = Number(process.env.PORT || 8792);
const TOKEN = process.env.PROMPTFOO_TOKEN || '';
const LIMIT_MS = Number(process.env.PROMPTFOO_LIMIT_SECONDS || 900) * 1000;
let running = Promise.resolve();
let checks = 0;

function authorised(req) {
  const raw = req.headers.authorization || '';
  const given = raw.toLowerCase().startsWith('bearer ') ? raw.slice(7) : raw;
  if (!TOKEN || given.length !== TOKEN.length) return false;
  return crypto.timingSafeEqual(Buffer.from(given), Buffer.from(TOKEN));
}

function send(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) });
  res.end(data);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const parts = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > 2_000_000) { reject(new Error('The check is larger than 2 MB.')); req.destroy(); return; }
      parts.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(parts).toString('utf8')));
    req.on('error', reject);
  });
}

function promptfoo(args, cwd) {
  return new Promise((resolve) => {
    execFile('promptfoo', args, { cwd, timeout: LIMIT_MS, maxBuffer: 20_000_000, env: process.env },
      (error, stdout, stderr) => resolve({ code: error ? (error.code ?? 1) : 0, stdout, stderr, killed: !!(error && error.killed) }));
  });
}

// What promptfoo wrote, in the shape JAI reads: one line per case, with the grader's reason.
function summarise(out) {
  const top = out.results || {};
  const rows = Array.isArray(top) ? top : (top.results || []);
  const results = rows.map((r) => {
    const grading = r.gradingResult || {};
    const reasons = (grading.componentResults || []).filter((c) => !c.pass).map((c) => c.reason).filter(Boolean);
    return {
      description: (r.testCase && r.testCase.description) || (r.vars && (r.vars.said || r.vars.request)) || '',
      prompt: (r.prompt && (r.prompt.label || r.prompt.id)) || '',
      pass: !!r.success,
      score: typeof r.score === 'number' ? r.score : null,
      reason: (reasons.join('; ') || grading.reason || r.error || '').slice(0, 1000),
      output: String((r.response && r.response.output) || '').slice(0, 2000),
    };
  });
  const stats = top.stats || {};
  return {
    passed: stats.successes ?? results.filter((r) => r.pass).length,
    failed: stats.failures ?? results.filter((r) => !r.pass && !r.reason.startsWith('Error')).length,
    errors: stats.errors ?? 0,
    results,
  };
}

async function runCheck(config, validateOnly) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'jai-check-'));
  try {
    const file = path.join(dir, 'promptfooconfig.json');
    fs.writeFileSync(file, JSON.stringify(config));
    const valid = await promptfoo(['validate', '-c', file], dir);
    if (valid.code !== 0) return { ok: false, stage: 'validate', reason: (valid.stderr || valid.stdout).slice(-2000) };
    if (validateOnly) return { ok: true, valid: true };
    const output = path.join(dir, 'results.json');
    const ran = await promptfoo(['eval', '-c', file, '-o', output, '--no-cache', '--no-progress-bar', '--no-table',
      '--max-concurrency', '2', '--no-share'], dir);
    if (ran.killed) return { ok: false, stage: 'eval', reason: `The check took longer than ${LIMIT_MS / 1000} seconds.` };
    if (!fs.existsSync(output)) return { ok: false, stage: 'eval', reason: (ran.stderr || ran.stdout).slice(-2000) };
    // promptfoo exits 100 when a case fails: that is a result, not an error.
    return { ok: true, ...summarise(JSON.parse(fs.readFileSync(output, 'utf8'))) };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === 'GET' && req.url === '/health') return send(res, 200, { ok: true, checks });
    if (req.method !== 'POST' || !['/eval', '/validate'].includes(req.url)) return send(res, 404, { ok: false, reason: 'Not here.' });
    if (!authorised(req)) return send(res, 401, { ok: false, reason: "Not JAI's prompt-check token." });
    const body = JSON.parse(await readBody(req) || '{}');
    if (!body.config || typeof body.config !== 'object') return send(res, 400, { ok: false, reason: 'Send {"config": {...}}.' });
    const turn = running.then(() => runCheck(body.config, req.url === '/validate'));
    running = turn.catch(() => undefined);
    const result = await turn;
    checks += 1;
    return send(res, 200, result);
  } catch (err) {
    return send(res, 500, { ok: false, reason: String(err && err.message || err).slice(0, 1000) });
  }
});

if (require.main === module) {
  server.listen(PORT, '0.0.0.0', () => console.log(`JAI prompt checks on ${PORT}`));
}
module.exports = { summarise, authorised, server };
