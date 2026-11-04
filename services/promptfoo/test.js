// JAI's prompt-check service, without a model: the token is required, promptfoo validates a real configuration,
// and promptfoo's results are read into JAI's shape.
'use strict';
const assert = require('assert');
process.env.PROMPTFOO_TOKEN = 'test-token';
const { summarise, server } = require('./server');

const config = {
  description: 'JAI check',
  prompts: [{ label: 'voice', raw: JSON.stringify([{ role: 'system', content: 'You are JAI.' }, { role: 'user', content: '{{said}}' }]) }],
  providers: [{ id: 'openai:chat:gpt-6-luna' }],
  tests: [{ description: 'first person', vars: { said: 'hello' }, assert: [{ type: 'not-icontains', value: 'JAI has' }] }],
};

const rows = summarise({ results: { stats: { successes: 1, failures: 1, errors: 0 }, results: [
  { success: true, score: 1, testCase: { description: 'first person' }, prompt: { label: 'voice' }, response: { output: 'I have finished.' }, gradingResult: { pass: true, reason: 'All assertions passed' } },
  { success: false, score: 0, testCase: { description: 'never publishes' }, prompt: { label: 'voice' }, response: { output: 'Posted it.' },
    gradingResult: { pass: false, reason: 'x', componentResults: [{ pass: false, reason: 'It claimed to publish.' }] } },
] } });
assert.strictEqual(rows.passed, 1);
assert.strictEqual(rows.failed, 1);
assert.strictEqual(rows.results[1].reason, 'It claimed to publish.');
assert.strictEqual(rows.results[0].prompt, 'voice');

server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  const call = (url, body, token) => fetch(`http://127.0.0.1:${port}${url}`, { method: 'POST', body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) } }).then((r) => r.json().then((j) => [r.status, j]));
  try {
    const [denied] = await call('/validate', { config });
    assert.strictEqual(denied, 401);
    const [status, valid] = await call('/validate', { config }, 'test-token');
    assert.strictEqual(status, 200);
    assert.strictEqual(valid.ok, true, JSON.stringify(valid));
    const [, broken] = await call('/validate', { config: { prompts: 'nothing' } }, 'test-token');
    assert.strictEqual(broken.ok, false);
    console.log('prompt-check service: 6 checks passed');
    server.close();
  } catch (err) {
    console.error(err);
    process.exit(1);
  }
});
