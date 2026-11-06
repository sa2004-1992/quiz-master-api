// Runs the REAL admin_questions.js in jsdom against recorded server responses (CSV preview/import, Gemini, counts).
// Usage: node tests/js/admin_ui_check.js fixture.json   (needs `jsdom`)
const fs = require('fs');
const { JSDOM } = require('jsdom');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fail = (m) => { console.error('FAIL: ' + m); process.exit(1); };
const ok = (c, m) => { if (!c) fail(m); };
(async () => {
  const dom = new JSDOM(input.html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const w = dom.window, d = w.document, $ = (id) => d.getElementById(id);
  w.QM = { csrf: 'tok' };
  const calls = [];
  w.fetch = (url, opts) => {
    const method = (opts && opts.method) || 'GET';
    calls.push({ url, method, body: opts && opts.body });
    const path = url.split('?')[0];
    const map = { '/api/admin/questions/counts': input.counts, '/api/admin/questions/csv/preview': input.preview,
                  '/api/admin/questions/csv/import': input.import, '/api/admin/questions/generate': input.generate,
                  '/api/admin/questions/list': input.list };
    const body = map[path] || { ok: false, error: 'unexpected ' + path };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(body))) });
  };
  w.eval(fs.readFileSync('app/static/js/admin_questions.js', 'utf8'));
  await sleep(40);

  // counts table loaded from the server (56 rows + totals)
  ok($('countsRows').querySelectorAll('tr').length === 56, 'counts rows: ' + $('countsRows').querySelectorAll('tr').length);
  ok($('countsRows').firstChild.firstChild.textContent === 'History', 'first category name shown (not a number)');
  ok($('countsTotals').textContent.includes(String(input.counts.totals.all)), 'totals shown');

  // mode switches show/hide the category selector
  ok($('csvCategoryField').hidden === false, 'Category Quiz shows the category selector');
  $('csvMode').value = 'all'; $('csvMode').dispatchEvent(new w.Event('change'));
  ok($('csvCategoryField').hidden === true, 'All Quiz hides it');
  $('csvMode').value = 'daily'; $('csvMode').dispatchEvent(new w.Event('change'));
  ok($('csvCategoryField').hidden === true, 'Daily Quiz hides it');
  $('csvMode').value = 'category'; $('csvMode').dispatchEvent(new w.Event('change'));

  // choose a file -> preview -> confirm
  ok($('csvPreviewBtn').disabled === true, 'Preview disabled until a file is chosen');
  const file = new w.File(['x'], 'questions.csv', { type: 'text/csv' });
  Object.defineProperty($('csvFile'), 'files', { value: [file] });
  $('csvFile').dispatchEvent(new w.Event('change'));
  ok($('csvFileName').textContent.includes('questions.csv') && $('csvPreviewBtn').disabled === false, 'file chosen');
  ok($('csvPreview').hidden === true && $('csvImportBtn').disabled === true, 'nothing previewed or importable yet');
  $('csvPreviewBtn').click(); await sleep(40);
  const p = input.preview;
  ok($('csvPreview').hidden === false, 'preview shown');
  const stats = Array.from($('csvStats').querySelectorAll('.stat')).map((s) => s.textContent);
  ok(stats.length === 4 && stats[0].includes(String(p.total)) && stats[1].includes(String(p.valid)) && stats[2].includes(String(p.invalid)), 'valid/invalid/duplicate counts: ' + stats.join('|'));
  ok($('csvRows').querySelectorAll('tr').length === p.preview.length, 'one preview row per record');
  ok($('csvRows').querySelectorAll('tr.qa-bad').length === p.invalid + p.duplicates, 'problem rows are marked');
  ok($('csvProblems').textContent.includes('will NOT be imported') && $('csvProblems').textContent.includes(p.problems[0].reason), 'problems listed with reasons');
  ok($('csvImportBtn').disabled === false, 'Confirm Import enabled after a preview with valid rows');
  const pv = calls.find((c) => c.url.endsWith('/csv/preview'));
  ok(pv.body.get('mode') === 'category' && pv.body.get('file').name === 'questions.csv', 'mode and file were sent');
  $('csvImportBtn').click(); await sleep(40);
  ok($('csvResult').hidden === false && $('csvResult').textContent.includes('Imported ' + input.import.imported), 'import result shown after the server confirmed: ' + $('csvResult').textContent);
  ok($('csvImportBtn').disabled === true, 'cannot import the same preview twice');
  ok(calls.filter((c) => c.url.endsWith('/counts')).length >= 2, 'counts refreshed after the import');

  // Gemini form
  $('genMode').value = 'all'; $('genMode').dispatchEvent(new w.Event('change'));
  ok($('genCategoryField').hidden === true, 'category hidden for All Quiz generation');
  $('genCount').value = '10';
  $('genForm').dispatchEvent(new w.Event('submit', { cancelable: true })); await sleep(40);
  const g = calls.find((c) => c.url.endsWith('/generate'));
  const sent = JSON.parse(g.body);
  ok(sent.mode === 'all' && sent.count === 10 && sent.language === 'auto' && sent.category === '', 'generate request: ' + g.body);
  ok($('genResult').textContent.includes('Saved ' + input.generate.saved), 'generation result shows the saved count: ' + $('genResult').textContent);
  ok($('genBtn').disabled === false && $('genBtn').textContent === 'Generate Questions', 'button restored');
  ok($('genDetails').querySelectorAll('tr').length === input.generate.details.length, 'per-category details listed');

  // browse
  $('brBtn').click(); await sleep(40);
  ok($('brRows').querySelectorAll('tr').length === input.list.items.length && $('brWrap').hidden === false, 'browse rows');
  console.log('admin ui ok'); process.exit(0);
})().catch((e) => fail(String(e && e.stack || e)));
