/**
 * Sidebar Toggle Functionality
 * Переключение между полным и компактным режимом sidebar с сохранением в localStorage
 */

(function() {
  'use strict';

  // Получаем текущее состояние sidebar из localStorage
  function getSidebarState() {
    const saved = localStorage.getItem('sidebarCollapsed');
    return saved === 'true';
  }

  // Сохраняем состояние sidebar в localStorage
  function setSidebarState(collapsed) {
    localStorage.setItem('sidebarCollapsed', collapsed.toString());
  }

  // Применяем состояние sidebar
  function applySidebarState(collapsed) {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    if (collapsed) {
      sidebar.classList.add('sidebar-collapsed');
    } else {
      sidebar.classList.remove('sidebar-collapsed');
    }

    // Обновляем иконку кнопки
    updateToggleButton(collapsed);
    
    // Обновляем графики при изменении размера sidebar
    if (typeof window.resizeAllCharts === 'function') {
      setTimeout(function() {
        window.resizeAllCharts();
      }, 300); // Ждем завершения анимации
    }
  }

  // Обновляем иконку кнопки переключения
  function updateToggleButton(collapsed) {
    const toggleIcon = document.getElementById('sidebar-toggle-icon');
    if (toggleIcon) {
      if (collapsed) {
        toggleIcon.className = 'bi bi-chevron-right';
      } else {
        toggleIcon.className = 'bi bi-chevron-left';
      }
    }
  }

  // Переключаем sidebar
  function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    const isCollapsed = sidebar.classList.contains('sidebar-collapsed');
    const newState = !isCollapsed;
    
    setSidebarState(newState);
    applySidebarState(newState);
  }

  // Инициализация при загрузке страницы
  function initSidebar() {
    const savedState = getSidebarState();
    applySidebarState(savedState);
  }

  // Инициализируем sidebar при загрузке DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSidebar);
  } else {
    initSidebar();
  }

  // Обработчик изменения размера окна - обновляем графики
  let resizeTimeout;
  window.addEventListener('resize', function() {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(function() {
      if (typeof window.resizeAllCharts === 'function') {
        window.resizeAllCharts();
      }
    }, 150);
  });

  // Экспортируем функцию переключения для использования в HTML
  window.toggleSidebar = toggleSidebar;
})();

