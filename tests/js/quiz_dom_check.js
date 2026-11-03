// Runs the REAL app/static/js/quiz.js inside jsdom against recorded server responses and checks the DOM.
// Usage: node tests/js/quiz_dom_check.js fixture.json   (needs `jsdom`; the pytest wrapper skips if it is missing)
const fs = require('fs');
const { JSDOM } = require('jsdom');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fail = (msg) => { console.error('FAIL: ' + msg); process.exit(1); };
const ok = (c, msg) => { if (!c) fail(msg); };

(async () => {
  const dom = new JSDOM(input.html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const w = dom.window, d = w.document;
  w.QM = { csrf: 'test-token' };
  const calls = [];
  w.fetch = (url, opts) => {
    const method = (opts && opts.method) || 'GET';
    calls.push({ url, method });
    let body = { ok: false, error: 'unexpected call ' + method + ' ' + url };
    let delay = 0;
    if (method === 'GET' && url.endsWith('/state')) body = input.state0;
    if (method === 'POST' && url.endsWith('/answer')) { body = input.answer; delay = input.delayMs || 0; }
    return new Promise((resolve) => setTimeout(() => resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(body))) }), delay));
  };
  w.eval(fs.readFileSync('app/static/js/quiz.js', 'utf8'));
  await sleep(40);

  const $ = (id) => d.getElementById(id);
  const opts = () => Array.from(d.querySelectorAll('#options .option'));
  const byKey = (k) => opts().find((b) => b.dataset.key === k);
  const e = input.expect;

  // initial screen: existing layout preserved + the two new counters
  ok($('qType').textContent === e.quizLabel, 'quiz type shown: ' + $('qType').textContent);
  ok($('qCategory').textContent === e.category, 'category shown: ' + $('qCategory').textContent);
  ok(/^1( \/ \d+)?$/.test($('qNumber').textContent), 'question number shown: ' + $('qNumber').textContent);
  ok($('qCorrect').textContent === '0' && $('qWrong').textContent === '0' && $('qScore').textContent === '0', 'counters start at 0');
  ok($('qHints').textContent.includes('/') && $('qTimer').textContent.length >= 5, 'hints and timer shown');
  ok(opts().length === 4 && opts().every((b) => !b.disabled), 'four enabled options');
  ok($('feedback').hidden === true, 'no feedback before answering');
  ok(!d.querySelector('.opt-badge'), 'no badges before answering');
  ['prevBtn', 'hintBtn', 'pauseBtn', 'nextBtn', 'exitBtn', 'finishBtn'].forEach((id) => ok($(id), 'button kept: ' + id));

  // click: all four options lock IMMEDIATELY (before the server has answered)
  byKey(input.click).click();
  ok(opts().every((b) => b.disabled), 'all four options disabled instantly on click');
  await sleep((input.delayMs || 0) + 60);

  // feedback
  const sel = byKey(input.click), cor = byKey(e.correctKey);
  if (e.outcome === 'wrong') {
    ok(sel.classList.contains('incorrect') && !sel.classList.contains('correct'), 'selected wrong option is red');
    ok(sel.textContent.includes('\u274C Wrong Answer!'), 'wrong option shows red cross + "Wrong Answer!"');
    ok(cor.classList.contains('correct'), 'actual correct option highlighted green');
    ok(cor.textContent.includes('\u2705 Correct Answer!'), 'correct option shows green check + "Correct Answer!"');
    ok(opts().filter((b) => b.classList.contains('incorrect')).length === 1, 'only the selected option is red');
  } else {
    ok(sel.classList.contains('correct') && sel.textContent.includes('\u2705 Correct Answer!'), 'selected correct option is green with message');
    ok(!d.querySelector('.option.incorrect') && !d.querySelector('.opt-badge.bad'), 'nothing red when correct');
  }
  ok(opts().filter((b) => b.classList.contains('correct')).length === 1, 'exactly one green option');
  ok(opts().every((b) => b.disabled), 'options stay disabled after the result');
  ok($('feedback').hidden === false && $('explanation').textContent === e.explanation, 'explanation shown immediately inside the card');
  ok($('questionCard').contains($('explanation')), 'explanation lives inside the question card');
  ok($('qCorrect').textContent === String(e.counters.correct) && $('qWrong').textContent === String(e.counters.wrong)
     && $('qScore').textContent === String(e.counters.score), 'counters updated: ' + $('qCorrect').textContent + '/' + $('qWrong').textContent + '/' + $('qScore').textContent);
  ok($('nextBtn').disabled === false, 'Next enabled after feedback');

  // the answer cannot be changed or submitted twice
  const other = opts().find((b) => b.dataset.key !== input.click);
  other.click();
  await sleep(30);
  ok(calls.filter((c) => c.method === 'POST').length === 1, 'only one answer request was ever sent');
  ok(sel.classList.contains(e.outcome === 'wrong' ? 'incorrect' : 'correct'), 'selection unchanged');
  console.log('dom ok');
  process.exit(0);
})().catch((err) => fail(String(err && err.stack || err)));
