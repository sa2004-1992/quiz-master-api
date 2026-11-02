/* My Performance: Last 10 game scores. Charts are plain SVG (no libraries, CSP-safe) and are only
   created after the user chooses Bar or Pie. The render functions are pure and unit-testable in Node. */
(function (root) {
  'use strict';
  var COLORS = ['#2563eb', '#16a34a', '#f59e0b', '#db2777', '#0891b2', '#7c3aed', '#ea580c', '#65a30d', '#dc2626', '#0d9488'];
  function esc(v) { return String(v).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function tip(g) { return 'Game ' + g.n + ' \u00b7 ' + g.quiz + ' \u00b7 ' + g.date + ' \u00b7 Score ' + g.score; }
  function niceMax(v) { var step = v <= 10 ? 10 : Math.pow(10, Math.floor(Math.log10(v))); return Math.max(10, Math.ceil(v / step) * step); }

  function bar(games) {
    var W = 640, H = 320, L = 48, R = 14, T = 24, B = 40, pw = W - L - R, ph = H - T - B;
    var max = niceMax(Math.max.apply(null, games.map(function (g) { return g.score; }).concat([0])));
    var out = '<svg class="chart-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Bar chart of your last ' + games.length + ' game scores">';
    for (var i = 0; i <= 4; i++) {
      var y = T + ph - (ph * i / 4), val = Math.round(max * i / 4);
      out += '<line class="chart-grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '"/>' +
             '<text class="chart-text" x="' + (L - 8) + '" y="' + (y + 4) + '" text-anchor="end">' + val + '</text>';
    }
    var slot = pw / games.length, bw = Math.min(46, slot * 0.6);
    games.forEach(function (g, idx) {
      var h = ph * g.score / max, x = L + slot * idx + (slot - bw) / 2, y = T + ph - h;
      out += '<g><title>' + esc(tip(g)) + '</title><rect class="chart-bar" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) +
             '" width="' + bw.toFixed(1) + '" height="' + Math.max(h, 1).toFixed(1) + '" rx="4"/>' +
             '<text class="chart-val" x="' + (x + bw / 2).toFixed(1) + '" y="' + (y - 6).toFixed(1) + '" text-anchor="middle">' + g.score + '</text>' +
             '<text class="chart-text" x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 16) + '" text-anchor="middle">#' + g.n + '</text></g>';
    });
    out += '<text class="chart-text" x="' + (L + pw / 2) + '" y="' + (H - 2) + '" text-anchor="middle">Game (oldest to newest)</text>' +
           '<text class="chart-text" transform="rotate(-90 12 ' + (T + ph / 2) + ')" x="12" y="' + (T + ph / 2) + '" text-anchor="middle">Score</text></svg>';
    return out;
  }

  function pie(games) {
    var total = games.reduce(function (s, g) { return s + g.score; }, 0);
    if (total <= 0) return '<p class="muted">All of these games scored 0, so there is nothing to show in a pie chart. Try the bar chart.</p>';
    var cx = 160, cy = 160, r = 140, angle = -Math.PI / 2, out = '<div class="pie-wrap"><svg class="chart-svg pie-svg" viewBox="0 0 320 320" role="img" aria-label="Pie chart of your last ' + games.length + ' game scores">';
    var positive = games.filter(function (g) { return g.score > 0; });
    games.forEach(function (g, i) {
      if (g.score <= 0) return;
      var color = COLORS[i % COLORS.length], frac = g.score / total, a2 = angle + frac * 2 * Math.PI;
      if (positive.length === 1) {
        out += '<g><title>' + esc(tip(g)) + '</title><circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + color + '"/></g>';
        out += '<text class="pie-val" x="' + cx + '" y="' + (cy + 5) + '" text-anchor="middle">' + g.score + '</text>';
      } else {
        var x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle), x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
        out += '<g><title>' + esc(tip(g)) + '</title><path d="M' + cx + ' ' + cy + ' L' + x1.toFixed(2) + ' ' + y1.toFixed(2) + ' A' + r + ' ' + r +
               ' 0 ' + (frac > 0.5 ? 1 : 0) + ' 1 ' + x2.toFixed(2) + ' ' + y2.toFixed(2) + ' Z" fill="' + color + '" class="pie-seg"/></g>';
        if (frac >= 0.06) {
          var mid = angle + (a2 - angle) / 2;
          out += '<text class="pie-val" x="' + (cx + r * 0.62 * Math.cos(mid)).toFixed(1) + '" y="' + (cy + r * 0.62 * Math.sin(mid) + 5).toFixed(1) + '" text-anchor="middle">' + g.score + '</text>';
        }
      }
      angle = a2;
    });
    out += '</svg><ul class="pie-legend">';
    games.forEach(function (g, i) {
      out += '<li><svg class="swatch" viewBox="0 0 10 10" aria-hidden="true"><rect width="10" height="10" rx="2" fill="' + COLORS[i % COLORS.length] + '"/></svg>' +
             '<span>#' + g.n + ' \u00b7 ' + esc(g.quiz) + ' \u00b7 ' + esc(g.date) + '</span><strong>' + g.score + '</strong></li>';
    });
    return out + '</ul></div>';
  }

  var api = { bar: bar, pie: pie, esc: esc };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.QMCharts = api;

  if (typeof document === 'undefined') return;
  var area = document.getElementById('chartArea'), dataEl = document.getElementById('perfChartData');
  if (!area || !dataEl) return;
  var games = JSON.parse(dataEl.textContent || '[]'), hint = document.getElementById('chartHint');
  document.querySelectorAll('.seg-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.seg-btn').forEach(function (b) { b.setAttribute('aria-pressed', String(b === btn)); });
      if (hint) hint.hidden = true;
      area.hidden = false;
      var kind = btn.getAttribute('data-chart');
      area.innerHTML = games.length ? (kind === 'pie' ? pie(games) : bar(games))
        : '<p class="muted">No completed games yet. Finish and save a quiz to see your scores here.</p>';
    });
  });
})(typeof window !== 'undefined' ? window : globalThis);
