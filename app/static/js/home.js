/* global window, document */
(function () {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return;
  }

  const reduceMotionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

  function prefersReducedMotion() {
    return reduceMotionQuery ? reduceMotionQuery.matches : false;
  }

  function handleScroll(button) {
    const targetSelector = button.getAttribute('data-scroll-target');
    if (!targetSelector) {
      return;
    }

    const target = document.querySelector(targetSelector);
    if (!target) {
      return;
    }

    const behavior = prefersReducedMotion() ? 'auto' : 'smooth';
    target.scrollIntoView({ behavior, block: 'start' });
  }

  const scrollButtons = document.querySelectorAll('[data-scroll-target]');
  scrollButtons.forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      handleScroll(button);
    });
  });

  function updateToggleState(button, panel, expanded) {
    const labelExpanded = button.getAttribute('data-label-open') || 'Nascondi';
    const labelCollapsed = button.getAttribute('data-label-closed') || 'Espandi';
    const labelElement = button.querySelector('.home-section__toggle-label');

    if (expanded) {
      panel.removeAttribute('hidden');
    } else {
      panel.setAttribute('hidden', '');
    }

    button.setAttribute('aria-expanded', expanded ? 'true' : 'false');

    if (labelElement) {
      labelElement.textContent = expanded ? labelExpanded : labelCollapsed;
    }
  }

  const collapseButtons = document.querySelectorAll('[data-collapse-target]');
  collapseButtons.forEach((button) => {
    const targetSelector = button.getAttribute('data-collapse-target');
    if (!targetSelector) {
      return;
    }

    const panel = document.querySelector(targetSelector);
    if (!panel) {
      return;
    }

    const initiallyExpanded = !panel.hasAttribute('hidden');
    updateToggleState(button, panel, initiallyExpanded);

    button.addEventListener('click', (event) => {
      event.preventDefault();
      const isExpanded = button.getAttribute('aria-expanded') === 'true';
      updateToggleState(button, panel, !isExpanded);
    });
  });

  function getStorage(type) {
    try {
      return window[type];
    } catch (error) {
      return null;
    }
  }

  const popupOverlay = document.querySelector('[data-popup-overlay]');
  if (popupOverlay) {
    const localStore = getStorage('localStorage');
    const sessionStore = getStorage('sessionStorage');
    const dismissedKey = 'etnaPopupDismissed';
    const sessionKey = 'etnaPopupSessionShown';
    const closeButton = popupOverlay.querySelector('[data-popup-close]');

    function hasDismissed() {
      return localStore && localStore.getItem(dismissedKey) === 'true';
    }

    function hasShownThisSession() {
      return sessionStore && sessionStore.getItem(sessionKey) === 'true';
    }

    function markSessionShown() {
      if (sessionStore) {
        sessionStore.setItem(sessionKey, 'true');
      }
    }

    function showPopup() {
      if (popupOverlay.hasAttribute('hidden')) {
        popupOverlay.removeAttribute('hidden');
      }
      markSessionShown();
      window.removeEventListener('scroll', handleScrollForPopup);
    }

    function hidePopup(permanent) {
      popupOverlay.setAttribute('hidden', '');
      if (permanent && localStore) {
        localStore.setItem(dismissedKey, 'true');
      }
    }

    function handleScrollForPopup() {
      if (hasDismissed() || hasShownThisSession()) {
        window.removeEventListener('scroll', handleScrollForPopup);
        return;
      }

      const doc = document.documentElement;
      const scrollHeight = Math.max(doc.scrollHeight - window.innerHeight, 1);
      const scrollTop = window.scrollY || doc.scrollTop || 0;
      const progress = scrollTop / scrollHeight;

      if (progress >= 0.6) {
        showPopup();
      }
    }

    if (!hasDismissed() && !hasShownThisSession()) {
      window.addEventListener('scroll', handleScrollForPopup, { passive: true });
    }

    if (closeButton) {
      closeButton.addEventListener('click', () => hidePopup(true));
    }

    popupOverlay.addEventListener('click', (event) => {
      if (event.target === popupOverlay) {
        hidePopup(true);
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !popupOverlay.hasAttribute('hidden')) {
        hidePopup(true);
      }
    });
  }
})();
