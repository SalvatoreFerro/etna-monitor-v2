/* global window, document */
(function () {
  const focusableSelector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])'
  ].join(',');

  const DESKTOP_BREAKPOINT = 1024;
  const desktopMedia = window.matchMedia(`(min-width: ${DESKTOP_BREAKPOINT}px)`);

  let nav;
  let menu;
  let toggle;
  let backdrop;
  let previousFocus = null;
  let isOpen = false;

  function getFocusableElements(container) {
    if (!container) return [];
    return Array.from(container.querySelectorAll(focusableSelector)).filter((el) => {
      if (el.closest('[hidden]')) return false;
      const style = window.getComputedStyle(el);
      return style.display !== 'none' && style.visibility !== 'hidden';
    });
  }

  function trapFocus(event) {
    if (event.key !== 'Tab' || !isOpen || desktopMedia.matches) return;

    const focusable = getFocusableElements(menu);
    if (!focusable.length) {
      event.preventDefault();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function closeMenu(focusToggle = true) {
    if (!menu || !toggle) return;

    isOpen = false;
    menu.classList.remove('is-open');
    menu.setAttribute('aria-hidden', 'true');
    menu.setAttribute('hidden', '');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Apri il menu di navigazione');
    document.removeEventListener('keydown', trapFocus, true);
    document.removeEventListener('keydown', onKeydownEscape, true);
    document.body.classList.remove('nav-locked');
    document.body.style.overflow = '';

    if (backdrop) {
      backdrop.hidden = true;
      backdrop.setAttribute('aria-hidden', 'true');
    }

    if (focusToggle && previousFocus && typeof previousFocus.focus === 'function') {
      previousFocus.focus({ preventScroll: true });
    }
  }

  function openMenu() {
    if (!menu || !toggle) return;

    isOpen = true;
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    menu.removeAttribute('hidden');
    menu.setAttribute('aria-hidden', 'false');
    menu.classList.add('is-open');
    toggle.setAttribute('aria-expanded', 'true');
    toggle.setAttribute('aria-label', 'Chiudi il menu di navigazione');
    document.addEventListener('keydown', trapFocus, true);
    document.addEventListener('keydown', onKeydownEscape, true);
    document.body.classList.add('nav-locked');
    document.body.style.overflow = 'hidden';

    if (backdrop) {
      backdrop.hidden = false;
      backdrop.setAttribute('aria-hidden', 'false');
    }

    const focusable = getFocusableElements(menu);
    const target = focusable.length ? focusable[0] : menu;
    window.requestAnimationFrame(() => target.focus({ preventScroll: true }));
  }

  function onToggleClick(event) {
    event.preventDefault();
    if (desktopMedia.matches) return;
    if (isOpen) {
      closeMenu();
    } else {
      openMenu();
    }
  }

  function onKeydownEscape(event) {
    if (event.key === 'Escape' && isOpen) {
      event.preventDefault();
      closeMenu();
    }
  }

  function syncMode() {
    if (!menu || !toggle) return;

    if (desktopMedia.matches) {
      closeMenu(false);
      menu.removeAttribute('hidden');
      menu.removeAttribute('aria-hidden');
      menu.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Apri il menu di navigazione');
      if (backdrop) {
        backdrop.hidden = true;
        backdrop.setAttribute('aria-hidden', 'true');
      }
      document.body.classList.remove('nav-locked');
      document.body.style.overflow = '';
    } else {
      menu.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
      if (!isOpen && !menu.hasAttribute('hidden')) {
        menu.setAttribute('hidden', '');
      }
    }
  }

  function init() {
    nav = document.getElementById('mainNav');
    menu = document.querySelector('[data-nav-menu]');
    toggle = document.querySelector('[data-nav-toggle]');
    backdrop = document.querySelector('[data-nav-backdrop]');

    if (!nav || !menu || !toggle) {
      return;
    }

    toggle.addEventListener('click', onToggleClick);

    if (backdrop) {
      backdrop.addEventListener('click', () => closeMenu());
    }

    menu.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (desktopMedia.matches) return;
      if (target.closest('a')) {
        closeMenu(false);
      }
    });

    desktopMedia.addEventListener('change', syncMode);
    window.addEventListener('resize', syncMode);
    window.addEventListener('orientationchange', syncMode);

    syncMode();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
