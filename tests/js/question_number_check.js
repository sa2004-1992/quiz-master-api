// Runs the REAL quiz.js in jsdom and checks the question counter while moving with Next / Previous.
// Usage: node tests/js/question_number_check.js fixture.json   (needs `jsdom`)
const fs = require('fs');
const { JSDOM } = require('jsdom');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fail = (m) => { console.error('FAIL: ' + m); process.exit(1); };
const ok = (c, m) => { if (!c) fail(m); };
(async () => {
  const dom = new JSDOM(input.html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const w = dom.window, d = w.document;
  w.QM = { csrf: 't' };
  const route = { 'GET /state': 'state0', 'POST /answer': 'answered', 'POST /next': 'next', 'POST /previous': 'prev' };
  let current = 'state0';
  w.fetch = (url, opts) => {
    const method = (opts && opts.method) || 'GET', key = method + ' ' + url.replace(/^.*\/api\/games\/\d+/, '');
    const name = route[key];
    if (name && key !== 'GET /state') current = name;
    const body = key === 'GET /state' ? input.states[current] : (name ? input.states[name] : { ok: false, error: 'unexpected ' + key });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(body))) });
  };
  w.eval(fs.readFileSync('app/static/js/quiz.js', 'utf8'));
  await sleep(40);
  const num = () => d.getElementById('qNumber').textContent;
  const label = () => d.querySelector('.quiz-meta .stat-label').textContent;
  ok(label() === 'Question', 'label is Question');
  ok(num() === input.expect[0], 'first question shows "' + input.expect[0] + '" but got "' + num() + '"');
  d.querySelector('#options .option[data-key="B"]').click();            // resolve it so Next is allowed
  await sleep(40);
  ok(num() === input.expect[0], 'answering does not change the number');
  d.getElementById('nextBtn').click(); await sleep(40);
  ok(num() === input.expect[1], 'after Next shows "' + input.expect[1] + '" but got "' + num() + '"');
  d.getElementById('prevBtn').click(); await sleep(40);
  ok(num() === input.expect[0], 'after Previous shows "' + input.expect[0] + '" but got "' + num() + '"');
  console.log('number ok');
  process.exit(0);
})().catch((e) => fail(String(e && e.stack || e)));
