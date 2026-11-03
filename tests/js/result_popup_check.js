// Runs the REAL quiz.js in jsdom and checks the Finish & Save result popup (Home + View History buttons).
// Usage: node tests/js/result_popup_check.js fixture.json   (needs `jsdom`)
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
  // jsdom has no <dialog> behaviour: emulate showModal/close like a browser
  w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  w.HTMLDialogElement.prototype.close = function (v) { this.removeAttribute('open'); this.returnValue = v || ''; this.dispatchEvent(new w.Event('close')); };
  const calls = [];
  w.fetch = (url, opts) => {
    const method = (opts && opts.method) || 'GET';
    calls.push({ url, method });
    let body = { ok: false, error: 'unexpected ' + method + ' ' + url }, status = 200, delay = 0;
    if (method === 'GET' && url.endsWith('/state')) body = input.state0;
    if (method === 'POST' && url.endsWith('/finish')) { body = input.finish; status = input.finishStatus || 200; delay = 120; }
    return new Promise((resolve) => setTimeout(() => resolve({ ok: status < 400, status, json: () => Promise.resolve(JSON.parse(JSON.stringify(body))) }), delay));
  };
  w.eval(fs.readFileSync('app/static/js/quiz.js', 'utf8'));
  await sleep(40);

  const dlg = d.getElementById('resultDialog'), fin = d.getElementById('finishBtn');
  ok(!dlg.hasAttribute('open'), 'popup is closed before saving');
  ok(fin.disabled === false, 'Finish & Save is enabled');
  fin.click(); fin.click(); fin.click();           // rapid repeated clicks
  await sleep(250);
  const posts = calls.filter((c) => c.method === 'POST' && c.url.endsWith('/finish')).length;
  ok(posts === 1, 'Finish & Save sent exactly once for repeated clicks, got ' + posts);

  if (input.mode === 'failure') {
    ok(!dlg.hasAttribute('open'), 'no "Quiz saved" popup when saving failed');
    ok(d.getElementById('quizMessage').textContent.length > 0, 'an error message is shown instead');
    ok(fin.disabled === false, 'Finish & Save is available again to retry');
    console.log('popup ok');
    process.exit(0);
  }

  ok(dlg.hasAttribute('open'), 'popup shown after the backend confirmed the save');
  ok(dlg.querySelector('h2').textContent === 'Quiz saved!', 'existing heading kept');
  ok(d.getElementById('resultBody').textContent === input.expectBody, 'existing result text kept: ' + d.getElementById('resultBody').textContent);
  const links = Array.from(dlg.querySelectorAll('.dialog-actions a'));
  ok(links.length === 2, 'two buttons in the popup, got ' + links.length);
  ok(links[0].textContent === 'Home' && links[1].textContent === 'View History', 'order: Home then View History');
  ok(links[0].getAttribute('href') === input.homeHref, 'Home links to the existing Home route: ' + links[0].getAttribute('href'));
  ok(links[1].getAttribute('href') === input.historyHref, 'View History links to History: ' + links[1].getAttribute('href'));
  ok(links[0].classList.contains('btn') && links[1].classList.contains('btn'), 'both use the existing button styling');
  ok(fin.disabled === true, 'Finish & Save is disabled after a successful save (no duplicate saves)');
  ok(!calls.some((c) => c.method === 'POST' && !c.url.endsWith('/finish')), 'nothing else was posted (no new quiz started)');
  console.log('popup ok');
  process.exit(0);
})().catch((err) => fail(String(err && err.stack || err)));
