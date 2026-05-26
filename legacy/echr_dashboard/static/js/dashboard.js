// ── Theme Toggle ──────────────────────────────────────────────────────────
function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    try { localStorage.setItem('echr-theme', next); } catch(e) {}
}

// Apply saved theme
(function() {
    try {
        const saved = localStorage.getItem('echr-theme');
        if (saved) document.documentElement.setAttribute('data-theme', saved);
    } catch(e) {}
})();

// ── Filter Toggle ────────────────────────────────────────────────────────
function toggleFilters() {
    const panel = document.getElementById('filtersPanel');
    if (panel) panel.classList.toggle('open');
}

// ── Keyboard shortcut: focus search on / ─────────────────────────────────
document.addEventListener('keydown', function(e) {
    if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        e.preventDefault();
        const input = document.getElementById('searchInput') || document.querySelector('.search-input');
        if (input) input.focus();
    }
});
