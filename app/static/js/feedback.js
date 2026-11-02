(function () {
  'use strict';
  var form = document.getElementById('feedbackForm'); if (!form) return;
  var csrf = (window.QM && window.QM.csrf) || '';
  var $ = function (id) { return document.getElementById(id); };
  var msg = $('message'), btn = $('feedbackSend'), status = $('feedbackStatus');
  var ratingErr = $('ratingError'), msgErr = $('messageError');

  function show(kind, text) {
    status.className = 'alert alert-' + kind; status.textContent = text; status.hidden = false;
  }
  function renderRows(items) {
    var tbody = $('feedbackRows'); tbody.textContent = '';
    items.forEach(function (f) {
      var tr = document.createElement('tr');
      [['Date & Time', f.when, ''], ['Rating', f.stars, 'fb-rating'], ['Feedback Message', f.message, 'fb-message']].forEach(function (c) {
        var td = document.createElement('td'); td.setAttribute('data-label', c[0]); if (c[2]) td.className = c[2];
        td.textContent = c[1]; tr.appendChild(td);   // textContent: user text is never interpreted as HTML
      });
      tbody.appendChild(tr);
    });
    $('feedbackEmpty').hidden = items.length > 0; $('feedbackTableWrap').hidden = items.length === 0;
  }
  function selectedRating() { var r = form.querySelector('input[name="rating"]:checked'); return r ? r.value : ''; }

  form.addEventListener('submit', function (e) {
    e.preventDefault(); status.hidden = true;
    var rating = selectedRating(), text = msg.value.trim(), ok = true;
    ratingErr.textContent = rating ? '' : 'Please select a rating.'; if (!rating) ok = false;
    msgErr.textContent = text ? '' : 'Please write your feedback.'; msg.classList.toggle('invalid', !text); if (!text) ok = false;
    if (!ok) return;
    btn.disabled = true;
    fetch(form.getAttribute('data-api'), { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ rating: rating, message: msg.value }) })
      .then(function (r) { return r.json().then(function (j) { j.httpStatus = r.status; return j; }); })
      .catch(function () { return { ok: false, error: 'Could not send your feedback. Please check your connection and try again.' }; })
      .then(function (res) {
        btn.disabled = false;
        if (res.ok) {
          renderRows(res.items); form.reset(); ratingErr.textContent = ''; msgErr.textContent = '';
          show('success', 'Thank you! Your feedback has been sent.');
        } else {
          if (res.errors) { ratingErr.textContent = res.errors.rating || ''; msgErr.textContent = res.errors.message || ''; }
          show('error', res.error || 'Could not send your feedback. Please try again.');
        }
      });
  });
  msg.addEventListener('input', function () { if (msg.value.trim()) { msgErr.textContent = ''; msg.classList.remove('invalid'); } });
  form.addEventListener('change', function (e) { if (e.target.name === 'rating') ratingErr.textContent = ''; });
})();
