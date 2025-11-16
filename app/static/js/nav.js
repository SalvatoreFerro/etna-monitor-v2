/* global window, document */
(function () {
  function initSiteNav() {
    const menu = document.querySelector('[data-site-nav-menu]');
    const toggle = document.querySelector('[data-site-nav-toggle]');

    if (!menu || !toggle) {
      return;
    }

    const desktopQuery = window.matchMedia('(min-width: 1024px)');
    let docClickListener = null;

    function setDocumentListeners(active) {
      if (active) {
        if (!docClickListener) {
          docClickListener = (event) => {
            if (event.target === toggle || toggle.contains(event.target)) {
              return;
            }
            if (!menu.contains(event.target)) {
              closeMenu();
            }
          };
          document.addEventListener('click', docClickListener, true);
          document.addEventListener('keydown', onKeyDown, true);
        }
      } else if (docClickListener) {
        document.removeEventListener('click', docClickListener, true);
        document.removeEventListener('keydown', onKeyDown, true);
        docClickListener = null;
      }
    }

    function openMenu() {
      menu.classList.add('is-open');
      menu.setAttribute('aria-hidden', 'false');
      toggle.setAttribute('aria-expanded', 'true');
      setDocumentListeners(true);
    }

    function closeMenu() {
      menu.classList.remove('is-open');
      const dropdowns = menu.querySelectorAll('[data-site-nav-dropdown]');
      dropdowns.forEach((dropdown) => dropdown.removeAttribute('open'));
      if (desktopQuery.matches) {
        menu.setAttribute('aria-hidden', 'false');
      } else {
        menu.setAttribute('aria-hidden', 'true');
      }
      toggle.setAttribute('aria-expanded', 'false');
      setDocumentListeners(false);
    }

    function syncToViewport() {
      if (desktopQuery.matches) {
        menu.classList.add('is-open');
        menu.setAttribute('aria-hidden', 'false');
        toggle.setAttribute('aria-expanded', 'false');
        setDocumentListeners(false);
      } else {
        closeMenu();
      }
    }

    function handleToggle(event) {
      if (desktopQuery.matches) {
        return;
      }
      event.preventDefault();
      const isOpen = menu.classList.contains('is-open');
      if (isOpen) {
        closeMenu();
      } else {
        openMenu();
      }
    }

    function handleMenuClick(event) {
      if (!desktopQuery.matches && event.target.closest('a')) {
        closeMenu();
      }
    }

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        closeMenu();
        toggle.focus({ preventScroll: true });
      }
    }

    syncToViewport();

    if (typeof desktopQuery.addEventListener === 'function') {
      desktopQuery.addEventListener('change', syncToViewport);
    } else if (typeof desktopQuery.addListener === 'function') {
      desktopQuery.addListener(syncToViewport);
    }

    toggle.addEventListener('click', handleToggle);
    menu.addEventListener('click', handleMenuClick);
  }

  function init() {
    initSiteNav();
    initUserMenu();
  }

  function initUserMenu() {
    const menus = document.querySelectorAll('[data-user-menu]');

    if (!menus.length) {
      return;
    }

    menus.forEach((menu) => {
      const trigger = menu.querySelector('[data-user-menu-trigger]');
      const dropdown = menu.querySelector('[data-user-menu-dropdown]');

      if (!trigger || !dropdown) {
        return;
      }

      function open() {
        menu.classList.add('is-open');
        trigger.setAttribute('aria-expanded', 'true');
        dropdown.removeAttribute('hidden');
      }

      function close() {
        menu.classList.remove('is-open');
        trigger.setAttribute('aria-expanded', 'false');
        dropdown.setAttribute('hidden', '');
      }

      function toggle(event) {
        event.preventDefault();
        if (menu.classList.contains('is-open')) {
          close();
        } else {
          open();
        }
      }

      function handleDocumentClick(event) {
        if (!menu.contains(event.target)) {
          close();
        }
      }

      function handleKeydown(event) {
        if (event.key === 'Escape') {
          close();
          trigger.focus({ preventScroll: true });
        }
      }

      close();

      trigger.addEventListener('click', toggle);
      menu.addEventListener('keydown', handleKeydown);
      document.addEventListener('click', handleDocumentClick, true);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
