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

})();
