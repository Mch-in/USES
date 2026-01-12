/**
 * Theme Toggle Functionality
 * Переключение между темной и светлой темой с сохранением в localStorage
 */

(function() {
  'use strict';

  // Получаем текущую тему из localStorage или устанавливаем темную по умолчанию
  function getTheme() {
    return localStorage.getItem('theme') || 'dark';
  }

  // Сохраняем тему в localStorage
  function setTheme(theme) {
    localStorage.setItem('theme', theme);
  }

  // Применяем тему к документу
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    updateThemeToggleButton(theme);
  }

  // Обновляем иконку и текст кнопки переключения темы
  function updateThemeToggleButton(theme) {
    // Обновляем десктопную кнопку
    const toggleBtn = document.getElementById('theme-toggle-btn');
    if (toggleBtn) {
      const icon = toggleBtn.querySelector('i');
      const text = toggleBtn.querySelector('span');

      if (theme === 'light') {
        // Показываем иконку луны для переключения на темную тему
        icon.className = 'bi bi-moon-stars-fill';
        text.textContent = 'Темная тема';
      } else {
        // Показываем иконку солнца для переключения на светлую тему
        icon.className = 'bi bi-sun-fill';
        text.textContent = 'Светлая тема';
      }
    }

    // Обновляем мобильную кнопку
    const mobileToggleBtn = document.getElementById('theme-toggle-btn-mobile');
    if (mobileToggleBtn) {
      const icon = mobileToggleBtn.querySelector('i');
      const text = mobileToggleBtn.querySelector('span');

      if (theme === 'light') {
        icon.className = 'bi bi-moon-stars-fill';
        text.textContent = 'Темная тема';
      } else {
        icon.className = 'bi bi-sun-fill';
        text.textContent = 'Светлая тема';
      }
    }
  }

  // Переключаем тему
  function toggleTheme() {
    const currentTheme = getTheme();
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    setTheme(newTheme);
    applyTheme(newTheme);
    
    // Обновляем графики при смене темы
    if (typeof window.updateChartsTheme === 'function') {
      // Небольшая задержка, чтобы CSS переменные успели обновиться
      setTimeout(function() {
        window.updateChartsTheme();
      }, 50);
    }
  }

  // Инициализация при загрузке страницы
  function initTheme() {
    const savedTheme = getTheme();
    applyTheme(savedTheme);
  }

  // Инициализируем тему при загрузке DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTheme);
  } else {
    initTheme();
  }

  // Экспортируем функцию переключения для использования в HTML
  window.toggleTheme = toggleTheme;
})();

