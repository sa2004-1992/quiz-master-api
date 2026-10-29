(function () {
  'use strict';
  var root = document.getElementById('quiz'); if (!root) return;
  var base = root.getAttribute('data-base'), csrf = window.QM.csrf, state = null, tickStart = 0, tickBase = 0, busy = false;
  var $ = function (id) { return document.getElementById(id); };
  var el = { type: $('qType'), cat: $('qCategory'), num: $('qNumber'), score: $('qScore'), timer: $('qTimer'), hints: $('qHints'),
    text: $('qText'), options: $('options'), fb: $('feedback'), verdict: $('verdict'), expl: $('explanation'), bm: $('bookmarkBtn'),
    prev: $('prevBtn'), next: $('nextBtn'), hint: $('hintBtn'), pause: $('pauseBtn'), exit: $('exitBtn'), finish: $('finishBtn'),
    msg: $('quizMessage'), banner: $('pausedBanner'), card: $('questionCard') };

  function fmt(s) { s = Math.max(0, Math.floor(s)); var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : String(m).padStart(2, '0')) + ':' + String(x).padStart(2, '0'); }
  function say(t) { el.msg.textContent = t || ''; }

  function api(path, method, payload) {
    return fetch(base + path, { method: method || 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: method === 'GET' ? undefined : JSON.stringify(payload || {}) })
      .then(function (r) { return r.json().then(function (j) { j.status = r.status; return j; }); })
      .catch(function () { return { ok: false, error: 'Network problem. Please try again.' }; });
  }
  function run(path, payload, method) {
    if (busy) return Promise.resolve();
    busy = true; say('');
    return api(path, method, payload).then(function (res) {
      busy = false;
      if (res.ok && res.state) { apply(res.state); return res; }
      if (res.ok) return res;
      say(res.error || 'Something went wrong.');
      if (res.code === 'out_of_sync' || res.code === 'duplicate_answer' || res.code === 'paused') load();
      if (res.status === 404) { say('This game is no longer available.'); setTimeout(function () { location.href = '/quizzes'; }, 1500); }
      return res;
    });
  }
  function load() { return api('/state', 'GET').then(function (r) { if (r.ok) apply(r.state); else say(r.error); }); }

  function apply(s) {
    state = s; tickBase = s.elapsed_seconds; tickStart = performance.now();
    el.type.textContent = s.quiz_label; el.cat.textContent = s.question.category; el.cat.hidden = s.quiz_type === 'category' ? false : false;
    el.num.textContent = s.question.number + ' / ' + s.total; el.score.textContent = s.score;
    el.hints.textContent = s.hints_left + ' / ' + s.hints_max; el.timer.textContent = fmt(s.elapsed_seconds);
    el.text.textContent = s.question.text;
    var q = s.question; el.options.textContent = '';
    ['A', 'B', 'C', 'D'].forEach(function (k) {
      var b = document.createElement('button'); b.type = 'button'; b.className = 'option'; b.dataset.key = k;
      var l = document.createElement('span'); l.className = 'letter'; l.textContent = k;
      var t = document.createElement('span'); t.textContent = q.options[k]; b.append(l, t);
      if (q.resolved) { b.disabled = true;
        if (k === q.correct_answer) b.classList.add('correct');
        else if (k === q.selected) b.classList.add('incorrect'); }
      b.addEventListener('click', function () { answer(k); }); el.options.appendChild(b);
    });
    el.fb.hidden = !q.resolved;
    if (q.resolved) {
      el.verdict.className = 'verdict ' + (q.hint_used ? '' : (q.is_correct ? 'ok' : 'bad'));
      el.verdict.textContent = q.hint_used ? 'Hint used — correct answer: ' + q.correct_answer + '. No points change.'
        : (q.is_correct ? 'Correct! +10 points' : 'Incorrect. The correct answer is ' + q.correct_answer + '. −5 points');
      el.expl.textContent = q.explanation; el.bm.textContent = q.bookmarked ? 'Remove bookmark' : 'Bookmark question';
    }
    var paused = s.paused; el.card.classList.toggle('is-paused', paused); el.banner.hidden = !paused;
    el.pause.textContent = paused ? 'Resume' : 'Pause';
    el.prev.disabled = !s.can_previous || paused; el.next.disabled = !s.can_next || paused;
    el.hint.disabled = q.resolved || s.hints_left <= 0 || paused; el.finish.disabled = !s.can_finish;
    el.options.querySelectorAll('.option').forEach(function (b) { if (paused) b.disabled = true; });
  }

  function answer(k) { run('/answer', { question_id: state.question.id, option: k }); }
  el.hint.addEventListener('click', function () { run('/hint', { question_id: state.question.id }); });
  el.prev.addEventListener('click', function () { run('/previous'); });
  el.next.addEventListener('click', function () { run('/next'); });
  el.pause.addEventListener('click', function () { run(state.paused ? '/resume' : '/pause'); });
  el.bm.addEventListener('click', function () {
    if (busy) return; api('/bookmark', 'POST', { question_id: state.question.id }).then(function (r) {
      if (r.ok) { state.question.bookmarked = r.bookmarked; el.bm.textContent = r.bookmarked ? 'Remove bookmark' : 'Bookmark question'; } else say(r.error); });
  });

  function confirmDialog(title, text, okLabel) {
    var d = $('confirmDialog'); $('confirmTitle').textContent = title; $('confirmBody').textContent = text; $('confirmOk').textContent = okLabel;
    return new Promise(function (resolve) { d.addEventListener('close', function h() { d.removeEventListener('close', h); resolve(d.returnValue === 'ok'); }); d.showModal(); });
  }
  el.exit.addEventListener('click', function () {
    confirmDialog('Exit this quiz?', 'Your current progress will be discarded. Nothing will be saved to your history, score or progress.', 'Exit without saving')
      .then(function (yes) { if (yes) run('/exit').then(function (r) { if (r && r.ok) location.href = r.redirect; }); });
  });
  el.finish.addEventListener('click', function () {
    run('/finish').then(function (r) {
      if (!r || !r.ok) return;
      var s = r.summary, d = $('resultDialog');
      $('resultBody').textContent = 'Score: ' + s.score + ' · Answered: ' + s.resolved + ' of ' + s.total + ' · Correct: ' + s.correct + ' · Time: ' + fmt(s.elapsed_seconds);
      $('resultLink').href = r.redirect; d.showModal(); d.addEventListener('close', function () { location.href = r.redirect; });
    });
  });

  setInterval(function () { if (state && !state.paused) el.timer.textContent = fmt(tickBase + (performance.now() - tickStart) / 1000); }, 500);
  load();
})();
