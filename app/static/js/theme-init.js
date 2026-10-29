// Runs before first paint. Logged-in pages get their theme from the server; others use localStorage.
(function () {
  var root = document.documentElement;
  if (root.getAttribute('data-theme-source') === 'server') return;
  try {
    var saved = localStorage.getItem('qm-theme');
    if (saved === 'dark' || saved === 'light') root.setAttribute('data-theme', saved);
  } catch (e) { /* storage unavailable */ }
})();
