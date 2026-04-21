/**
 * Head init — applies theme and sidebar state from localStorage before first paint (FOUC).
 * Loaded synchronously in <head> on index.html and login.html.
 */
(function() {
  try {
    var theme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    // Sidebar: always start collapsed (hover-to-expand)
    document.documentElement.classList.add('sidebar-collapsed');
  } catch (e) {
    console.error('Failed to apply initial theme or sidebar state:', e);
  }
})();
