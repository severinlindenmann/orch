/* One icon set (24px grid, 1.75 stroke, currentColor), replaces the mixed unicode glyphs. Usage: icon('check', 16). */
(function () {
  const P = {
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
    expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    play: '<path d="M7 4v16l13-8z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    compare: '<path d="M12 3v18M8 7H4v10h4M16 7h4v10h-4"/>',
    download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    file: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10"/>',
    text: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    code: '<path d="m8 8-5 4 5 4M16 8l5 4-5 4"/>',
    test: '<path d="M9 11l2 2 4-4"/><rect x="3" y="3" width="18" height="18" rx="3"/>',
    metric: '<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>',
    note: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    page: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 8h18"/>',
    shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    up: '<path d="m6 15 6-6 6 6"/>', down: '<path d="m6 9 6 6 6-6"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    send: '<path d="M4 12 20 4l-6 16-3-7z"/>',
  };
  window.icon = (name, size = 16, cls = '') =>
    `<svg class="ic ${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ''}</svg>`;
})();
