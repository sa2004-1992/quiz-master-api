(function () {
  'use strict';
  var csrf = (window.QM && window.QM.csrf) || '';
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, text, cls) { var e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
  function clear(node) { node.textContent = ''; }
  function api(path, opts) {
    opts = opts || {}; opts.credentials = 'same-origin'; opts.headers = Object.assign({ 'X-CSRFToken': csrf }, opts.headers || {});
    return fetch(path, opts).then(function (r) { return r.json().then(function (j) { j.httpStatus = r.status; return j; }); })
      .catch(function () { return { ok: false, error: 'Network problem. Please try again.' }; });
  }
  function show(node, kind, text) { node.className = 'alert alert-' + kind; node.textContent = text; node.hidden = false; }
  function statBox(label, value) { var d = el('div', undefined, 'stat'); d.appendChild(el('span', label, 'stat-label')); d.appendChild(el('strong', String(value))); return d; }

  /* ---------- question bank counts ---------- */
  function loadCounts() {
    api('/api/admin/questions/counts').then(function (j) {
      var body = $('countsRows'), foot = $('countsTotals'); clear(body); clear(foot);
      if (!j.ok) { var tr = el('tr'); var td = el('td', j.error || 'Could not load counts.'); td.colSpan = 4; tr.appendChild(td); body.appendChild(tr); return; }
      j.rows.forEach(function (r) {
        var tr = el('tr'); tr.appendChild(el('td', r.name));
        ['category', 'all', 'daily'].forEach(function (m) { tr.appendChild(el('td', String(r[m]), 'num')); }); body.appendChild(tr);
      });
      var t = el('tr', undefined, 'qa-total'); t.appendChild(el('th', 'Total'));
      ['category', 'all', 'daily'].forEach(function (m) { t.appendChild(el('th', String(j.totals[m]), 'num')); }); foot.appendChild(t);
    });
  }

  /* ---------- CSV import ---------- */
  var fileInput = $('csvFile'), drop = $('csvDrop'), chosen = null, previewed = false;
  function csvSync() { $('csvCategoryField').hidden = $('csvMode').value !== 'category'; }
  function csvReset() { previewed = false; $('csvPreview').hidden = true; $('csvResult').hidden = true; $('csvImportBtn').disabled = true; $('csvPreviewBtn').disabled = !chosen; }
  function setFile(f) { chosen = f || null; $('csvFileName').textContent = chosen ? chosen.name + ' (' + Math.ceil(chosen.size / 1024) + ' KB)' : 'No file selected'; csvReset(); }
  function csvForm() {
    var fd = new FormData(); fd.append('file', chosen); fd.append('mode', $('csvMode').value);
    fd.append('category', $('csvMode').value === 'category' ? $('csvCategory').value : ''); return fd;
  }
  drop.addEventListener('click', function () { fileInput.click(); });
  drop.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } });
  fileInput.addEventListener('change', function () { setFile(fileInput.files[0]); });
  ['dragenter', 'dragover'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
  ['dragleave', 'drop'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
  drop.addEventListener('drop', function (e) { if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]); });
  $('csvMode').addEventListener('change', function () { csvSync(); csvReset(); });
  $('csvCategory').addEventListener('change', csvReset);
  csvSync();

  function problemsList(list, truncated) {
    var box = $('csvProblems'); clear(box);
    if (!list.length) return;
    box.appendChild(el('h4', 'Records that will NOT be imported', 'qa-sub'));
    var ul = el('ul', undefined, 'plain qa-problems');
    list.forEach(function (p) { ul.appendChild(el('li', 'Row ' + p.row + ' (line ' + p.line + '): ' + p.reason)); });
    box.appendChild(ul);
    if (truncated) box.appendChild(el('p', 'Only the first problems are listed.', 'muted small'));
  }
  $('csvPreviewBtn').addEventListener('click', function () {
    if (!chosen) return;
    $('csvPreviewBtn').disabled = true; $('csvResult').hidden = true;
    api('/api/admin/questions/csv/preview', { method: 'POST', body: csvForm() }).then(function (j) {
      $('csvPreviewBtn').disabled = false;
      if (!j.ok) { $('csvPreview').hidden = true; show($('csvResult'), 'error', j.error || 'The file could not be checked.'); return; }
      var stats = $('csvStats'); clear(stats);
      stats.appendChild(statBox('Records', j.total)); stats.appendChild(statBox('Valid', j.valid));
      stats.appendChild(statBox('Invalid', j.invalid)); stats.appendChild(statBox('Duplicates', j.duplicates));
      var body = $('csvRows'); clear(body);
      j.preview.forEach(function (r) {
        var tr = el('tr', undefined, r.status === 'valid' ? '' : 'qa-bad');
        tr.appendChild(el('td', String(r.row))); tr.appendChild(el('td', r.category)); tr.appendChild(el('td', r.question, 'qa-q'));
        tr.appendChild(el('td', r.answer)); tr.appendChild(el('td', r.status === 'valid' ? 'Valid' : (r.status === 'duplicate' ? 'Duplicate' : 'Invalid')));
        body.appendChild(tr);
      });
      problemsList(j.problems, j.problems_truncated);
      $('csvPreview').hidden = false; previewed = true;
      $('csvImportBtn').disabled = j.valid === 0;
      $('csvImportHint').textContent = j.valid ? ('Import ' + j.valid + ' valid question(s) into ' + j.mode_label + '.') : 'There is nothing valid to import.';
    });
  });
  $('csvImportBtn').addEventListener('click', function () {
    if (!chosen || !previewed) return;
    $('csvImportBtn').disabled = true;
    api('/api/admin/questions/csv/import', { method: 'POST', body: csvForm() }).then(function (j) {
      if (!j.ok) { $('csvImportBtn').disabled = false; show($('csvResult'), 'error', j.error || 'The import failed. Nothing was imported.'); return; }
      show($('csvResult'), j.imported ? 'success' : 'info', 'Imported ' + j.imported + ' question(s) into ' + j.mode_label + '. Skipped: ' + j.invalid + ' invalid, ' + j.duplicates + ' duplicate(s).');
      problemsList(j.problems, j.problems_truncated); previewed = false; $('csvImportBtn').disabled = true; loadCounts();
    });
  });

  /* ---------- Gemini generation ---------- */
  function genSync() {
    var m = $('genMode').value; $('genCategoryField').hidden = m !== 'category';
    $('genHint').textContent = m === 'category' ? 'Questions are saved only to the selected category of the Category Quiz.'
      : (m === 'all' ? 'Questions are saved only to the All Quiz dataset, filling the categories with the fewest questions first.'
                     : 'Questions are saved only to the Daily Quiz dataset (English categories unless you choose Kannada).');
  }
  $('genMode').addEventListener('change', genSync); genSync();
  $('genForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var count = parseInt($('genCount').value, 10);
    if (!count || count < 1) { show($('genResult'), 'error', 'Enter how many questions to generate.'); return; }
    var btn = $('genBtn'); btn.disabled = true; btn.textContent = 'Generating…'; $('genResult').hidden = true; $('genDetailsWrap').hidden = true;
    api('/api/admin/questions/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: $('genMode').value, category: $('genMode').value === 'category' ? $('genCategory').value : '', count: count, language: $('genLang').value }) })
      .then(function (j) {
        btn.disabled = false; btn.textContent = 'Generate Questions';
        var summary = 'Saved ' + (j.saved || 0) + ' of ' + (j.requested || count) + ' requested question(s) to ' + (j.mode_label || 'the selected mode') + '.'
          + (j.generated !== undefined ? ' Generated ' + j.generated + ', duplicates skipped ' + j.duplicates + ', invalid ' + j.invalid + '.' : '');
        if (j.ok && !j.error) show($('genResult'), j.saved ? 'success' : 'info', summary);
        else show($('genResult'), 'error', (j.error || 'Generation failed.') + (j.saved !== undefined ? ' ' + summary : ''));
        var body = $('genDetails'); clear(body);
        (j.details || []).forEach(function (d) {
          var tr = el('tr'); tr.appendChild(el('td', d.category));
          [d.generated, d.saved, d.duplicates, d.invalid].forEach(function (v) { tr.appendChild(el('td', String(v), 'num')); }); body.appendChild(tr);
        });
        $('genDetailsWrap').hidden = !(j.details && j.details.length); loadCounts();
      });
  });

  /* ---------- browse ---------- */
  var brPage = 1;
  function browse(page) {
    var q = '?mode=' + encodeURIComponent($('brMode').value) + '&category=' + encodeURIComponent($('brCategory').value) + '&page=' + page;
    api('/api/admin/questions/list' + q).then(function (j) {
      if (!j.ok) { $('brWrap').hidden = true; return; }
      brPage = j.page; var body = $('brRows'); clear(body);
      j.items.forEach(function (r) {
        var tr = el('tr'); tr.appendChild(el('td', String(r.id))); tr.appendChild(el('td', r.category)); tr.appendChild(el('td', r.question, 'qa-q'));
        tr.appendChild(el('td', r.correct_answer + ' – ' + r.options[r.correct_answer])); tr.appendChild(el('td', r.source)); body.appendChild(tr);
      });
      $('brWrap').hidden = false; $('brPager').hidden = j.total === 0;
      $('brInfo').textContent = 'Page ' + j.page + ' of ' + j.pages + ' · ' + j.total + ' question(s)';
      $('brPrev').disabled = j.page <= 1; $('brNext').disabled = j.page >= j.pages;
    });
  }
  $('brBtn').addEventListener('click', function () { browse(1); });
  $('brPrev').addEventListener('click', function () { browse(brPage - 1); });
  $('brNext').addEventListener('click', function () { browse(brPage + 1); });

  loadCounts();
})();
