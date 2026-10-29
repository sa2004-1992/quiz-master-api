(function () {
  'use strict';
  var body = document.body, root = document.documentElement;
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var mobile = window.matchMedia('(max-width: 900px)');

  /* ---------- sidebar ---------- */
  var toggle = document.getElementById('menuToggle'), overlay = document.getElementById('sidebarOverlay');
  function navOpen() { return mobile.matches ? body.classList.contains('nav-open') : !body.classList.contains('nav-collapsed'); }
  function setNav(open) {
    if (mobile.matches) body.classList.toggle('nav-open', open); else body.classList.toggle('nav-collapsed', !open);
    if (toggle) toggle.setAttribute('aria-expanded', String(open));
  }
  if (toggle) {
    setNav(!mobile.matches && !(function () { try { return localStorage.getItem('qm-nav') === 'closed'; } catch (e) { return false; } })());
    toggle.addEventListener('click', function () {
      var next = !navOpen(); setNav(next);
      if (!mobile.matches) { try { localStorage.setItem('qm-nav', next ? 'open' : 'closed'); } catch (e) {} }
    });
    if (overlay) overlay.addEventListener('click', function () { setNav(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && mobile.matches) setNav(false); });
    document.querySelectorAll('.sidebar a').forEach(function (a) { a.addEventListener('click', function () { if (mobile.matches) setNav(false); }); });
    mobile.addEventListener('change', function () { body.classList.remove('nav-open', 'nav-collapsed'); setNav(!mobile.matches); });
  }

  /* ---------- dark mode ---------- */
  var themeBtn = document.getElementById('themeToggle');
  if (themeBtn) themeBtn.addEventListener('click', function () {
    var dark = root.getAttribute('data-theme') !== 'dark';
    root.setAttribute('data-theme', dark ? 'dark' : 'light');
    themeBtn.setAttribute('aria-pressed', String(dark));
    fetch('/api/preferences/theme', { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ dark: dark }) })
      .then(function (r) { if (!r.ok) throw new Error(); })
      .catch(function () { root.setAttribute('data-theme', dark ? 'light' : 'dark'); themeBtn.setAttribute('aria-pressed', String(!dark)); });
  });

  /* ---------- password show/hide ---------- */
  document.querySelectorAll('[data-toggle-password]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = document.getElementById(btn.getAttribute('data-toggle-password'));
      var show = input.type === 'password'; input.type = show ? 'text' : 'password'; btn.textContent = show ? 'Hide' : 'Show';
    });
  });

  /* ---------- client-side form validation (server re-validates everything) ---------- */
  function fieldError(input, msg) {
    var wrap = input.closest('.field'); if (!wrap) return;
    var el = wrap.querySelector('.field-error');
    if (!msg) { if (el) el.remove(); input.classList.remove('invalid'); return; }
    if (!el) { el = document.createElement('span'); el.className = 'field-error'; el.setAttribute('role', 'alert'); wrap.appendChild(el); }
    el.textContent = msg; input.classList.add('invalid');
  }
  var forms = { register: function (f) {
      var v = function (n) { return f.elements[n].value; }, ok = true;
      var rules = [
        ['full_name', v('full_name').trim().length < 2, 'Full name must be at least 2 characters.'],
        ['email', !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(v('email').trim()), 'Enter a valid email address.'],
        ['username', !/^[A-Za-z0-9_.]{3,30}$/.test(v('username').trim()), 'Username must be 3-30 characters: letters, numbers, underscore or dot.'],
        ['gender', !v('gender'), 'Please select a gender.'],
        ['password', v('password').length < 6, 'Password must be at least 6 characters.'],
        ['confirm_password', v('confirm_password') !== v('password') || !v('confirm_password'), 'Passwords do not match.']];
      rules.forEach(function (r) { fieldError(f.elements[r[0]], r[1] ? r[2] : ''); if (r[1]) ok = false; });
      return ok; },
    login: function (f) {
      var ok = true;
      [['identifier', 'Enter your username or email.'], ['password', 'Enter your password.']].forEach(function (r) {
        var bad = !f.elements[r[0]].value.trim(); fieldError(f.elements[r[0]], bad ? r[1] : ''); if (bad) ok = false; });
      return ok; } };
  document.querySelectorAll('form[data-validate]').forEach(function (f) {
    f.addEventListener('submit', function (e) { if (!forms[f.getAttribute('data-validate')](f)) e.preventDefault(); });
  });

  /* ---------- category search (live filter; the form also works server-side) ---------- */
  var search = document.querySelector('[data-category-search]');
  if (search) {
    var cards = document.querySelectorAll('#categoryGrid .category-card'), none = document.getElementById('noResults');
    var filter = function () {
      var q = search.value.trim().toLowerCase(), shown = 0;
      cards.forEach(function (c) { var m = !q || c.getAttribute('data-name').indexOf(q) !== -1; c.hidden = !m; if (m) shown++; });
      if (none) none.hidden = shown !== 0 || cards.length === 0;
    };
    search.addEventListener('input', filter); filter();
    search.form.addEventListener('submit', function (e) { e.preventDefault(); });
  }

  /* ---------- profile: clear data dialog ---------- */
  var cd = document.getElementById('clearDialog');
  if (cd) {
    document.querySelector('[data-open-clear]').addEventListener('click', function () { cd.showModal(); });
    cd.querySelector('[data-close-clear]').addEventListener('click', function () { cd.close(); });
  }

  /* ---------- bar chart widths (CSSOM, CSP-safe) ---------- */
  document.querySelectorAll('.bar[data-value]').forEach(function (b) {
    var max = parseFloat(b.getAttribute('data-max')) || 1; b.style.height = Math.max(2, (parseFloat(b.getAttribute('data-value')) / max) * 100) + '%';
  });

  window.QM = { csrf: csrf };
})();
