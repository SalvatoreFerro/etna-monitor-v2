/* global window, document */
// UX_FIX_2025 Off-canvas navigation controller
(function () {
  const focusableSelector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])'
  ].join(',');

  const desktopMedia = window.matchMedia('(min-width: 992px)');
  let lastFocusedElement = null;
  let navElement;
  let navMenu;
  let navToggle;
  let navBackdrop;
  let userMenuToggle;
  let sectionToggles = [];
  let dropdownToggles = [];
  let closeButtons = [];
  let isMenuOpen = false;
  let scrollLockOrigin = 0;

  function isVisible(element) {
    if (!element) {
      return false;
    }

    const style = window.getComputedStyle(element);
    return style.visibility !== 'hidden' && style.display !== 'none';
  }

  function getFocusableElements(container) {
    if (!container) {
      return [];
    }

    return Array.from(container.querySelectorAll(focusableSelector)).filter((el) => {
      if (el.closest('[aria-hidden="true"]')) {
        return false;
      }
      return isVisible(el);
    });
  }

  function animateHamburger(expanded) {
    const lines = navToggle ? navToggle.querySelectorAll('.hamburger-line') : [];
    if (!lines.length) {
      return;
    }

    if (expanded) {
      lines[0].style.transform = 'rotate(45deg) translate(5px, 5px)';
      lines[1].style.opacity = '0';
      lines[2].style.transform = 'rotate(-45deg) translate(7px, -6px)';
    } else {
      lines[0].style.transform = '';
      lines[1].style.opacity = '1';
      lines[2].style.transform = '';
    }
  }

  function closeDropdown(dropdown) {
    if (!dropdown) {
      return;
    }

    dropdown.classList.remove('is-open');
    const toggle = dropdown.querySelector('.nav-dropdown-toggle');
    if (toggle) {
      toggle.setAttribute('aria-expanded', 'false');
    }
  }

  function closeAllDropdowns(exceptDropdown) {
    dropdownToggles.forEach((toggle) => {
      const wrapper = toggle.closest('.nav-dropdown');
      if (wrapper && wrapper !== exceptDropdown) {
        closeDropdown(wrapper);
      }
    });
  }

  function syncNavbarMetrics() {
    if (!navElement) {
      navElement = document.getElementById('mainNav');
    }

    if (!navElement) {
      return;
    }

    const navHeight = Math.round(navElement.getBoundingClientRect().height);
    if (navHeight > 0) {
      document.documentElement.style.setProperty('--navbar-height', `${navHeight}px`);
    }
  }

  function closeUserMenus(exceptToggle) {
    if (!userMenuToggles.length) {
      return;
    }

    userMenuToggles.forEach((toggle) => {
      if (toggle === exceptToggle) {
        return;
      }

      toggle.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
    });
  }

  function handleFocusTrap(event) {
    if (event.key !== 'Tab') {
      return;
    }

    const focusable = getFocusableElements(navMenu);
    if (navToggle) {
      focusable.unshift(navToggle);
    }
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

  function handleRovingFocus(event) {
    if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
      return;
    }

    const focusable = getFocusableElements(navMenu);
    if (!focusable.length) {
      return;
    }

    const currentIndex = focusable.indexOf(document.activeElement);
    if (currentIndex === -1) {
      return;
    }

    event.preventDefault();
    const direction = event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? -1 : 1;
    let nextIndex = currentIndex + direction;

    if (nextIndex < 0) {
      nextIndex = focusable.length - 1;
    }
    if (nextIndex >= focusable.length) {
      nextIndex = 0;
    }

    focusable[nextIndex].focus();
  }

  function setMenuOpen(open) {
    if (!navMenu || !navToggle) {
      return;
    }

    const isDesktopView = desktopMedia.matches;

    if (!isDesktopView) {
      navMenu.setAttribute('aria-hidden', String(!open));
    } else {
      navMenu.removeAttribute('aria-hidden');
    }

    if (open === isMenuOpen) {
      return;
    }

    isMenuOpen = open;
    navMenu.classList.toggle('is-open', open);
    if (!open) {
      navMenu.classList.remove('active', 'open');
    }
    navToggle.setAttribute('aria-expanded', String(open));
    navToggle.setAttribute('aria-label', open ? 'Chiudi il menu' : 'Apri il menu');
    navToggle.classList.toggle('is-active', open);
    document.body.classList.toggle('menu-open', open);
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) {
      scrollLockOrigin = window.scrollY || window.pageYOffset || 0;
    }
    animateHamburger(open);

    if (navBackdrop) {
      navBackdrop.hidden = !open;
      navBackdrop.setAttribute('aria-hidden', String(!open));
    }

    if (open) {
      lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const focusable = getFocusableElements(navMenu);
      const target = focusable.length ? focusable[0] : navMenu;
      window.requestAnimationFrame(() => {
        target.focus({ preventScroll: true });
      });
      navMenu.addEventListener('keydown', handleFocusTrap);
      navMenu.addEventListener('keydown', handleRovingFocus);
      document.addEventListener('keydown', onDocumentKeydown, true);
    } else {
      navMenu.removeEventListener('keydown', handleFocusTrap);
      navMenu.removeEventListener('keydown', handleRovingFocus);
      document.removeEventListener('keydown', onDocumentKeydown, true);
      closeAllDropdowns();
      closeUserMenus();

      if (!desktopMedia.matches) {
        closeAllSections();
      }

      if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
        lastFocusedElement.focus({ preventScroll: true });
      }
    }

    syncNavbarMetrics();
  }

  function onDocumentKeydown(event) {
    if (event.key === 'Escape' && isMenuOpen) {
      event.preventDefault();
      setMenuOpen(false);
    }
  }

  function toggleMenu(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    setMenuOpen(!isMenuOpen);
  }

  function onOutsideInteraction(event) {
    if (!isMenuOpen) {
      return;
    }

    if (!navMenu.contains(event.target) && !navToggle.contains(event.target)) {
      setMenuOpen(false);
    }
  }

  function bindTap(target, handler) {
    if (!target) {
      return;
    }

    let touched = false;

    const wrappedHandler = (event) => {
      if (event.type === 'touchstart') {
        touched = true;
      } else if (touched) {
        touched = false;
        return;
      }

      event.preventDefault();
      handler(event);
    };

    target.addEventListener('click', wrappedHandler);
    target.addEventListener('touchstart', wrappedHandler, { passive: false });
  }

  function closeAllSections(except) {
    sectionToggles.forEach((button) => {
      const section = button.closest('.nav-section');
      if (!section || section === except) {
        return;
      }

      button.setAttribute('aria-expanded', 'false');
      section.classList.remove('is-open');
    });
  }

  function onSectionToggle(event) {
    event.preventDefault();
    event.stopPropagation();
    const button = event.currentTarget;
    const section = button.closest('.nav-section');
    if (!section) {
      return;
    }

    if (button.getAttribute('aria-disabled') === 'true') {
      return;
    }

    const willOpen = button.getAttribute('aria-expanded') !== 'true';
    closeAllSections(section);
    button.setAttribute('aria-expanded', String(willOpen));
    section.classList.toggle('is-open', willOpen);
  }

  function onDropdownToggle(event) {
    event.preventDefault();
    event.stopPropagation();
    const toggle = event.currentTarget;
    const dropdown = toggle.closest('.nav-dropdown');
    if (!dropdown) {
      return;
    }

    const willOpen = toggle.getAttribute('aria-expanded') !== 'true';
    closeAllDropdowns(dropdown);
    toggle.setAttribute('aria-expanded', String(willOpen));
    dropdown.classList.toggle('is-open', willOpen);
  }

  function syncAccordionState() {
    const isDesktop = desktopMedia.matches;

    sectionToggles.forEach((button) => {
      const section = button.closest('.nav-section');
      if (!section) {
        return;
      }

      button.setAttribute('aria-expanded', String(isDesktop));
      section.classList.toggle('is-open', isDesktop);
      if (isDesktop) {
        button.setAttribute('aria-disabled', 'true');
        button.setAttribute('tabindex', '-1');
      } else {
        button.removeAttribute('aria-disabled');
        button.setAttribute('tabindex', '0');
      }
    });

    if (isDesktop) {
      dropdownToggles.forEach((toggle) => {
        const dropdown = toggle.closest('.nav-dropdown');
        closeDropdown(dropdown);
      });
      setMenuOpen(false);
    }
  }

  function handleResize() {
    syncAccordionState();
    if (navMenu) {
      const visualViewportHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
      navMenu.style.setProperty('--viewport-height', `${visualViewportHeight}px`);
    }

    syncNavbarMetrics();
  }

  function initNavigation() {
    navElement = document.getElementById('mainNav');
    navMenu = document.getElementById('navbar-menu');
    navToggle = document.getElementById('navToggle');
    navBackdrop = document.getElementById('navBackdrop');
    userMenuToggles = Array.from(document.querySelectorAll('.user-menu-toggle'));

    if (!navMenu || !navToggle) {
      return;
    }

    sectionToggles = Array.from(navMenu.querySelectorAll('.nav-section-toggle'));
    dropdownToggles = Array.from(navMenu.querySelectorAll('.nav-dropdown-toggle'));
    closeButtons = Array.from(navMenu.querySelectorAll('[data-nav-close]'));

    bindTap(navToggle, toggleMenu);

    if (navBackdrop) {
      bindTap(navBackdrop, () => setMenuOpen(false));
    }

    closeButtons.forEach((button) => {
      bindTap(button, () => setMenuOpen(false));
    });

    document.addEventListener('click', onOutsideInteraction, { capture: true });
    document.addEventListener('touchstart', onOutsideInteraction, { capture: true });

    window.addEventListener('scroll', () => {
      if (isMenuOpen) {
        const currentScroll = window.scrollY || window.pageYOffset || 0;
        if (Math.abs(currentScroll - scrollLockOrigin) > 150) {
          setMenuOpen(false);
        }
      }
      closeUserMenus();
    }, { passive: true });

    navMenu.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }

      const isNavLink = target.closest('a');
      const isDropdownToggle = target.closest('.nav-dropdown-toggle');
      if (isMenuOpen && isNavLink && !isDropdownToggle) {
        setMenuOpen(false);
      }
    });

    sectionToggles.forEach((button) => {
      bindTap(button, onSectionToggle);
    });

    dropdownToggles.forEach((toggle) => {
      bindTap(toggle, onDropdownToggle);
    });

    document.addEventListener('click', (event) => {
      dropdownToggles.forEach((toggle) => {
        const dropdown = toggle.closest('.nav-dropdown');
        if (dropdown && !dropdown.contains(event.target)) {
          closeDropdown(dropdown);
        }
      });

      if (userMenuToggles.length) {
        const target = event.target;
        const isInsideUserMenu = userMenuToggles.some((toggle) => {
          const dropdown = toggle.nextElementSibling;
          return toggle.contains(target) || (dropdown && dropdown.contains(target));
        });

        if (!isInsideUserMenu) {
          closeUserMenus();
        }
      }
    });

    document.addEventListener('touchstart', (event) => {
      dropdownToggles.forEach((toggle) => {
        const dropdown = toggle.closest('.nav-dropdown');
        if (dropdown && !dropdown.contains(event.target)) {
          closeDropdown(dropdown);
        }
      });

      if (userMenuToggles.length) {
        const target = event.target;
        const isInsideUserMenu = userMenuToggles.some((toggle) => {
          const dropdown = toggle.nextElementSibling;
          return toggle.contains(target) || (dropdown && dropdown.contains(target));
        });

        if (!isInsideUserMenu) {
          closeUserMenus();
        }
      }
    }, { passive: true });

    if (userMenuToggles.length) {
      userMenuToggles.forEach((toggle) => {
        const toggleUserMenu = (event) => {
          if (event) {
            event.stopPropagation();
          }
          const willOpen = toggle.getAttribute('aria-expanded') !== 'true';
          if (willOpen) {
            closeUserMenus(toggle);
          } else {
            closeUserMenus();
          }
          toggle.classList.toggle('is-open', willOpen);
          toggle.setAttribute('aria-expanded', String(willOpen));
        };

        bindTap(toggle, toggleUserMenu);
      });
    }

    desktopMedia.addEventListener('change', handleResize);
    window.addEventListener('resize', handleResize);
    window.addEventListener('orientationchange', handleResize);
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', handleResize);
    }
    syncAccordionState();
    handleResize();
  }

  window.EMNav = {
    init: initNavigation
  };

  window.addEventListener('load', syncNavbarMetrics);
})();
