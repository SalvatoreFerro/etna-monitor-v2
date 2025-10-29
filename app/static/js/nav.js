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
      menu.removeAttribute('hidden');
      menu.setAttribute('aria-hidden', 'false');
      toggle.setAttribute('aria-expanded', 'true');
      setDocumentListeners(true);
    }

    function closeMenu() {
      menu.classList.remove('is-open');
      if (!desktopQuery.matches) {
        menu.setAttribute('hidden', '');
        menu.setAttribute('aria-hidden', 'true');
      } else {
        menu.removeAttribute('hidden');
        menu.setAttribute('aria-hidden', 'false');
      }
      toggle.setAttribute('aria-expanded', 'false');
      setDocumentListeners(false);
    }

    function syncToViewport() {
      if (desktopQuery.matches) {
        menu.classList.add('is-open');
        menu.removeAttribute('hidden');
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
      const isOpen = menu.classList.contains('is-open') && !menu.hasAttribute('hidden');
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
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
