/* global window, document */
(function () {
  const STORAGE_KEY = 'em_nav_selection_v2';

  function getStorage() {
    try {
      const { localStorage } = window;
      const testKey = '__em_nav_test__';
      localStorage.setItem(testKey, '1');
      localStorage.removeItem(testKey);
      return localStorage;
    } catch (error) {
      return null;
    }
  }

  function init() {
    const container = document.querySelector('[data-nav-multiselect]');
    const selectedContainer = document.querySelector('[data-nav-selected]');
    if (!container || !selectedContainer) {
      return;
    }

    const toggle = container.querySelector('[data-nav-toggle]');
    const menu = container.querySelector('[data-nav-menu]');
    const applyBtn = container.querySelector('[data-nav-apply]');
    const resetBtn = container.querySelector('[data-nav-reset]');
    const countEl = container.querySelector('[data-nav-count]');
    const options = Array.from(container.querySelectorAll('[data-nav-option]'));
    const currentEndpoint = selectedContainer.dataset.navCurrentEndpoint || '';

    if (!toggle || !menu || !options.length) {
      return;
    }

    const storage = getStorage();
    let isOpen = false;

    function closeMenu() {
      if (!isOpen) return;
      isOpen = false;
      menu.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      container.classList.remove('is-open');
      document.removeEventListener('click', onDocumentClick);
      document.removeEventListener('keydown', onKeyDown, true);
    }

    function openMenu() {
      if (isOpen) return;
      isOpen = true;
      menu.hidden = false;
      toggle.setAttribute('aria-expanded', 'true');
      container.classList.add('is-open');
      document.addEventListener('click', onDocumentClick);
      document.addEventListener('keydown', onKeyDown, true);

      const firstOption = menu.querySelector('input[type="checkbox"]');
      if (firstOption) {
        window.requestAnimationFrame(() => {
          firstOption.focus({ preventScroll: true });
        });
      }
    }

    function onDocumentClick(event) {
      if (!container.contains(event.target)) {
        closeMenu();
      }
    }

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        closeMenu();
      }
    }

    function getCheckedValues() {
      return options.filter((option) => option.checked).map((option) => option.value);
    }

    function setChecked(values) {
      const valid = Array.isArray(values) ? values : [];
      options.forEach((option) => {
        option.checked = valid.includes(option.value);
      });
    }

    function getDefaultSelection() {
      return options
        .filter((option) => option.dataset.default === 'true')
        .map((option) => option.value);
    }

    function updateCount(values) {
      if (countEl) {
        countEl.textContent = values.length.toString();
      }
      const label = values.length === 1 ? 'sezione rapida selezionata' : 'sezioni rapide selezionate';
      toggle.setAttribute('aria-label', `Apri il menu delle ${label}`);
    }

    function renderSelected(values) {
      selectedContainer.innerHTML = '';

      if (!values.length) {
        const empty = document.createElement('span');
        empty.className = 'nav-empty';
        empty.textContent = 'Scegli le sezioni da mostrare';
        selectedContainer.appendChild(empty);
        return;
      }

      values.forEach((value) => {
        const option = options.find((item) => item.value === value);
        if (!option) return;
        const chip = document.createElement('a');
        chip.className = 'nav-chip';
        chip.href = option.dataset.url || '#';
        chip.textContent = option.dataset.label || value;
        chip.dataset.endpoint = value;
        if (currentEndpoint && currentEndpoint === value) {
          chip.classList.add('is-active');
        }
        selectedContainer.appendChild(chip);
      });
    }

    function persist(values) {
      if (!storage) return;
      try {
        storage.setItem(STORAGE_KEY, JSON.stringify(values));
      } catch (error) {
        // Ignore storage errors silently
      }
    }

    function applySelection(values, { persistSelection = true } = {}) {
      setChecked(values);
      updateCount(values);
      renderSelected(values);
      if (persistSelection) {
        persist(values);
      }
    }

    function getStoredSelection() {
      if (!storage) return null;
      try {
        const raw = storage.getItem(STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return null;
        return parsed.filter((value) => options.some((option) => option.value === value));
      } catch (error) {
        return null;
      }
    }

    function handleApply() {
      const values = getCheckedValues();
      applySelection(values);
      closeMenu();
    }

    function handleReset() {
      const defaults = getDefaultSelection();
      applySelection(defaults);
      closeMenu();
    }

    function handleToggle(event) {
      event.preventDefault();
      if (isOpen) {
        closeMenu();
      } else {
        openMenu();
      }
    }

    function handleOptionChange() {
      updateCount(getCheckedValues());
    }

    const initialSelection = getStoredSelection() || getDefaultSelection();
    applySelection(initialSelection, { persistSelection: false });

    toggle.addEventListener('click', handleToggle);
    options.forEach((option) => {
      option.addEventListener('change', handleOptionChange);
    });
    if (applyBtn) {
      applyBtn.addEventListener('click', handleApply);
    }
    if (resetBtn) {
      resetBtn.addEventListener('click', handleReset);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
