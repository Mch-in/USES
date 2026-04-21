/**
 * Base initialization for all pages (tooltips, mobile menu).
 * Loaded from index.html after jQuery and Bootstrap.
 */
$(document).ready(function() {
  var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  var tooltipList = tooltipTriggerList.map(function(tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });

  // Tooltips for edit buttons (data-bs-toggle="modal")
  var editButtons = [].slice.call(document.querySelectorAll('.edit-expense-btn[title], .edit-salary-payment-btn[title]'));
  editButtons.forEach(function(button) {
    new bootstrap.Tooltip(button);
  });

  // Tooltip for the "Import/Load sales" button (uses title attribute)
  var loadButton = document.getElementById('triggerUpdateSalesBtn');
  if (loadButton && loadButton.getAttribute('title')) {
    new bootstrap.Tooltip(loadButton);
  }

  $('.mobile-nav-header').on('click', function() {
    $('.mobile-nav').toggleClass('mobile-nav-open');
    $('.mobile-menu-toggle i').toggleClass('bi-list bi-x-lg');
  });

  $('.mobile-nav-link:not(.theme-toggle-btn-mobile):not(.language-toggle-btn-mobile)').on('click', function() {
    $('.mobile-nav').removeClass('mobile-nav-open');
    $('.mobile-menu-toggle i').removeClass('bi-x-lg').addClass('bi-list');
  });

  // Hover-to-expand sidebar: html.sidebar-hovering flag
  // (also disables tooltips while the menu is expanded on hover)
  const sidebarEl = document.querySelector('.sidebar');
  if (sidebarEl) {
    sidebarEl.addEventListener('mouseenter', function() {
      document.documentElement.classList.add('sidebar-hovering');
      initCollapsedMenuTooltips();
    });
    sidebarEl.addEventListener('mouseleave', function() {
      document.documentElement.classList.remove('sidebar-hovering');
      initCollapsedMenuTooltips();
    });
  }

  // Restore mobile menu after reload (e.g. language switch)
  if (sessionStorage.getItem('keepMobileMenuOpen') === 'true') {
    $('.mobile-nav').addClass('mobile-nav-open');
    $('.mobile-menu-toggle i').removeClass('bi-list').addClass('bi-x-lg');
    sessionStorage.removeItem('keepMobileMenuOpen');
  }

  $(document).on('click', function(e) {
    if (!$(e.target).closest('.mobile-nav').length && $('.mobile-nav').hasClass('mobile-nav-open')) {
      $('.mobile-nav').removeClass('mobile-nav-open');
      $('.mobile-menu-toggle i').removeClass('bi-x-lg').addClass('bi-list');
    }
  });

  // Tooltips when the sidebar is collapsed
  function initCollapsedMenuTooltips() {
    // Show tooltips only in compact mode (not while hover-expanded)
    const isCollapsed =
      document.documentElement.classList.contains('sidebar-collapsed') &&
      !document.documentElement.classList.contains('sidebar-hovering');
    
    // All sidebar elements with data-tooltip
    const tooltipElements = document.querySelectorAll('.sidebar [data-tooltip]');

    // Expanded menu: remove all tooltip instances
    if (!isCollapsed) {
      tooltipElements.forEach(function(element) {
        if (element._tooltipElement) {
          // Hide visible tooltip first
          element._tooltipElement.style.opacity = '0';
          element._tooltipElement.style.visibility = 'hidden';
          // Then remove the node
          element._tooltipElement.remove();
          element._tooltipElement = null;
          element.classList.remove('has-js-tooltip');
          // Clear theme update handlers
          element._updateTooltipTheme = null;
        }
      });
      return;
    }

    tooltipElements.forEach(function(element) {
      const tooltipText = element.getAttribute('data-tooltip');
      
      // Skip if already initialized
      if (element._tooltipElement) {
        return;
      }

      // Create a real DOM node for the tooltip
      const tooltipElement = document.createElement('div');
      tooltipElement.className = 'sidebar-tooltip-js';
      tooltipElement.textContent = tooltipText;
      
      tooltipElement.style.cssText = `
        position: fixed;
        padding: 0.5rem 0.75rem;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 400;
        white-space: nowrap;
        opacity: 0;
        visibility: hidden;
        pointer-events: none;
        z-index: 10001;
        transition: opacity 0.2s ease, transform 0.2s ease, visibility 0.2s ease;
        transform: translateY(-50%) translateX(-5px);
      `;
      document.body.appendChild(tooltipElement);
      element._tooltipElement = tooltipElement;
      element.classList.add('has-js-tooltip'); // Hide native CSS tooltip

      // Update tooltip colors when theme changes
      function updateTooltipTheme() {
        const isLightTheme = document.documentElement.getAttribute('data-theme') === 'light';
        const bgColor = isLightTheme ? '#1F2937' : '#2d2d2d';
        const textColor = isLightTheme ? '#FFFFFF' : '#E0E0E0';
        const borderColor = isLightTheme ? 'none' : '1px solid rgba(255, 255, 255, 0.1)';
        const shadow = isLightTheme ? '0 4px 12px rgba(0, 0, 0, 0.15)' : '0 2px 8px rgba(0, 0, 0, 0.3)';
        
        tooltipElement.style.backgroundColor = bgColor;
        tooltipElement.style.color = textColor;
        tooltipElement.style.border = borderColor;
        tooltipElement.style.boxShadow = shadow;
        tooltipElement.style.fontSize = '12px'; // 12px for all tooltips
      }
      
      // Initialize theme colors
      updateTooltipTheme();

      // Show on hover (collapsed menu only)
      element.addEventListener('mouseenter', function() {
        // Still collapsed?
        if (!document.documentElement.classList.contains('sidebar-collapsed')) {
          return;
        }
        
        // Tooltip node still present?
        if (!element._tooltipElement) {
          return;
        }

        // Refresh text if it changed dynamically
        element._tooltipElement.textContent = element.getAttribute('data-tooltip');
        
        updateTooltipTheme(); // Sync colors before show
        const rect = element.getBoundingClientRect();
        const tooltipLeft = rect.right + 12; // 0.75rem = 12px
        const tooltipTop = rect.top + rect.height / 2;
        
        tooltipElement.style.left = tooltipLeft + 'px';
        tooltipElement.style.top = tooltipTop + 'px';
        tooltipElement.style.opacity = '1';
        tooltipElement.style.visibility = 'visible';
        tooltipElement.style.transform = 'translateY(-50%) translateX(0)';
      });

      // Hide on mouse leave
      element.addEventListener('mouseleave', function() {
        tooltipElement.style.opacity = '0';
        tooltipElement.style.visibility = 'hidden';
        tooltipElement.style.transform = 'translateY(-50%) translateX(-5px)';
      });

      // Keep theme updater for MutationObserver
      element._updateTooltipTheme = updateTooltipTheme;
    });

    // React to data-theme changes
    const themeObserver = new MutationObserver(function(mutations) {
      mutations.forEach(function(mutation) {
        if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
          tooltipElements.forEach(function(element) {
            if (element._updateTooltipTheme) {
              element._updateTooltipTheme();
            }
          });
        }
      });
    });

    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    });
  }

  // Run after DOM ready
  setTimeout(function() {
    initCollapsedMenuTooltips();
    
    // Re-init when sidebar class changes
    const observer = new MutationObserver(function(mutations) {
      mutations.forEach(function(mutation) {
        if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
          // Short delay for CSS transition to finish
          setTimeout(function() {
            initCollapsedMenuTooltips();
          }, 100);
        }
      });
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class']
    });
  }, 500);

  // Show/hide password toggle buttons
  $(document).on('click', '.toggle-password', function() {
    var $input = $(this).closest('.input-group').find('input');
    var $icon = $(this).find('i');
    if ($input.attr('type') === 'password') {
      $input.attr('type', 'text');
      $icon.removeClass('bi-eye').addClass('bi-eye-slash');
    } else {
      $input.attr('type', 'password');
      $icon.removeClass('bi-eye-slash').addClass('bi-eye');
    }
  });
});
