/**
 * Theme Toggle Functionality
 * Switch between dark and light theme; persist choice in localStorage.
 */

(function() {
  'use strict';

  // Read current theme from localStorage, default to dark
  function getTheme() {
    return localStorage.getItem('theme') || 'dark';
  }

  // Persist theme in localStorage
  function setTheme(theme) {
    localStorage.setItem('theme', theme);
  }

  // Apply theme to the document
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    updateThemeToggleButton(theme);
  }

  // Update theme toggle icon and label
  function updateThemeToggleButton(theme) {
    // Helper to update one button (desktop and mobile)
    function updateButton(btnId) {
      const btn = document.getElementById(btnId);
      if (!btn) return;

      const icon = btn.querySelector('i');
      const text = btn.querySelector('span'); // span may be absent on desktop
      
      const lightText = btn.getAttribute('data-text-light') || 'Light theme';
      const darkText = btn.getAttribute('data-text-dark') || 'Dark theme';

      if (icon) {
        if (theme === 'light') {
          // Moon icon: switch to dark theme
          icon.className = 'bi bi-moon-stars-fill';
          if (text) text.textContent = darkText;
          btn.setAttribute('data-tooltip', darkText);
        } else {
          // Sun icon: switch to light theme
          icon.className = 'bi bi-sun-fill';
          if (text) text.textContent = lightText;
          btn.setAttribute('data-tooltip', lightText);
        }
      }
    }

    // Desktop button
    updateButton('theme-toggle-btn');
    
    // Mobile button
    updateButton('theme-toggle-btn-mobile');
  }

  // Toggle theme
  function toggleTheme() {
    const currentTheme = getTheme();
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    setTheme(newTheme);
    applyTheme(newTheme);
    
    // Dispatch custom event so other parts of the app (e.g. charts) react to theme changes
    const event = new CustomEvent('themeChanged', { detail: { theme: newTheme } });
    document.dispatchEvent(event);
  }

  // Init on page load
  function initTheme() {
    const savedTheme = getTheme();
    applyTheme(savedTheme);
  }

  // Initialize theme when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTheme);
  } else {
    initTheme();
  }

  // Expose toggle for inline handlers in HTML
  window.toggleTheme = toggleTheme;
})();

