/* global window, document, fetch */
(function () {
  const CHART_ENDPOINT = '/api/curva?limit=168';
  const STATUS_ENDPOINT = '/api/status';
  const REQUEST_TIMEOUT = 5000;

  if (window.__chartReady) {
    return;
  }
  window.__chartReady = true;

  const plotElement = document.getElementById('home-preview-plot');
  const loadingElement = document.getElementById('home-preview-loading');
  const quickUpdateBtn = document.getElementById('quick-update-btn');
  const lastUpdateEl = document.getElementById('live-last-update');
  const pointsEl = document.getElementById('live-data-points');
  const activityBadge = document.getElementById('live-activity-badge');
  const statusIndicator = document.getElementById('live-status-indicator');
  const statusText = document.getElementById('live-status-text');
  const defaultLoadingMarkup = loadingElement ? loadingElement.innerHTML : '';

  if (!plotElement || !loadingElement) {
    return;
  }

  let resizeBound = false;

  function fetchWithTimeout(url, options = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
    const config = { ...options, signal: controller.signal };

    return fetch(url, config)
      .finally(() => window.clearTimeout(timer));
  }

  function showSpinner() {
    if (!loadingElement) return;
    loadingElement.innerHTML = defaultLoadingMarkup;
    loadingElement.hidden = false;
    loadingElement.setAttribute('aria-hidden', 'false');
  }

  function hideSpinner() {
    if (!loadingElement) return;
    loadingElement.hidden = true;
    loadingElement.setAttribute('aria-hidden', 'true');
  }

  function updateStatus(isOnline) {
    if (!statusIndicator || !statusText) return;
    statusIndicator.classList.toggle('online', isOnline);
    statusIndicator.classList.toggle('offline', !isOnline);
    statusText.textContent = isOnline ? 'Dati online' : 'Connessione assente';
  }

  function updateActivity(value) {
    if (!activityBadge) return;
    activityBadge.classList.remove('badge-low', 'badge-medium', 'badge-high');
    if (typeof value !== 'number' || Number.isNaN(value)) {
      activityBadge.textContent = 'Dati non disponibili';
      activityBadge.removeAttribute('aria-label');
      return;
    }

    let label = '';
    if (value <= 1) {
      activityBadge.classList.add('badge-low');
      label = 'Attività bassa';
    } else if (value <= 5) {
      activityBadge.classList.add('badge-medium');
      label = 'Attività moderata';
    } else {
      activityBadge.classList.add('badge-high');
      label = 'Attività elevata';
    }

    const text = `${value.toFixed(2)} mV · ${label}`;
    activityBadge.textContent = text;
    activityBadge.setAttribute('aria-label', `${label} (${value.toFixed(2)} millivolt)`);
  }

  function formatDate(value) {
    if (!value) return '--';
    try {
      const date = new Date(value);
      return date.toLocaleString('it-IT', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    } catch (error) {
      return value;
    }
  }

  function updateMetrics(payload) {
    const rows = Array.isArray(payload.data) ? payload.data : [];
    const lastRecord = rows.length ? rows[rows.length - 1] : null;
    const lastTimestamp = payload.last_ts || (lastRecord && lastRecord.timestamp);

    if (lastUpdateEl) {
      lastUpdateEl.textContent = formatDate(lastTimestamp);
    }
    if (pointsEl) {
      const count = typeof payload.rows === 'number' ? payload.rows : rows.length;
      pointsEl.textContent = count.toLocaleString('it-IT');
    }
    if (lastRecord && typeof lastRecord.value !== 'undefined') {
      updateActivity(Number(lastRecord.value));
    }
  }

  function showError(message) {
    if (!loadingElement) return;
    loadingElement.hidden = false;
    loadingElement.setAttribute('aria-hidden', 'false');
    loadingElement.innerHTML = '';
    const wrapper = document.createElement('div');
    wrapper.className = 'chart-error';
    wrapper.setAttribute('role', 'alert');
    const text = document.createElement('p');
    text.textContent = message;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-secondary btn-sm';
    button.textContent = 'Riprova';
    button.addEventListener('click', () => {
      loadChart().catch(() => {
        /* errors handled in loadChart */
      });
    });
    wrapper.appendChild(text);
    wrapper.appendChild(button);
    loadingElement.appendChild(wrapper);
  }

  function ensureResizeListener() {
    if (resizeBound) return;
    resizeBound = true;
    window.addEventListener('resize', () => {
      if (window.Plotly && plotElement && plotElement.data) {
        window.Plotly.Plots.resize(plotElement);
      }
    });
  }

  async function drawPlot(rows) {
    if (!window.Plotly) {
      throw new Error('Plotly non disponibile');
    }

    const timestamps = rows.map((row) => row.timestamp);
    const values = rows.map((row) => Number(row.value));

    const trace = {
      x: timestamps,
      y: values,
      type: 'scatter',
      mode: 'lines',
      name: 'Tremore',
      line: { color: '#00D2FF', width: 2 },
      hoverlabel: { bgcolor: '#0B1220', font: { color: '#F4F8FF' } }
    };

    const layout = {
      margin: { l: 52, r: 16, t: 20, b: 56 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#F4F8FF', size: 12 },
      xaxis: {
        title: 'Data/Ora',
        type: 'date',
        tickformat: '%d/%m/%Y %H:%M:%S',
        showgrid: true,
        gridcolor: 'rgba(0, 210, 255, 0.12)'
      },
      yaxis: {
        title: 'mV',
        type: 'log',
        showgrid: true,
        gridcolor: 'rgba(0, 210, 255, 0.12)'
      }
    };

    const config = {
      responsive: true,
      displayModeBar: false,
      scrollZoom: false,
      doubleClick: 'reset'
    };

    await window.Plotly.newPlot(plotElement, [trace], layout, config);
    plotElement.classList.add('loaded');
    plotElement.removeAttribute('aria-hidden');
    ensureResizeListener();
  }

  async function loadChart() {
    showSpinner();
    try {
      const response = await fetchWithTimeout(CHART_ENDPOINT, {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache' }
      });
      if (!response.ok) {
        throw new Error('Risposta non valida dal server');
      }
      const payload = await response.json();
      if (!payload.ok) {
        throw new Error(payload.error || 'Errore dati INGV');
      }
      if (!Array.isArray(payload.data) || !payload.data.length) {
        throw new Error('Dati non disponibili');
      }
      await drawPlot(payload.data);
      hideSpinner();
      updateMetrics(payload);
      updateStatus(true);
      return payload;
    } catch (error) {
      console.error('Errore caricamento curva', error);
      hideSpinner();
      const message = error && error.name === 'AbortError'
        ? 'Timeout di rete, riprova.'
        : (error && error.message ? error.message : 'Impossibile caricare il grafico');
      showError(message);
      updateStatus(false);
      throw error;
    }
  }

  async function refreshStatus() {
    try {
      const response = await fetchWithTimeout(STATUS_ENDPOINT, { cache: 'no-store' });
      if (!response.ok) {
        throw new Error('Risposta status non valida');
      }
      const payload = await response.json();
      if (payload.ok) {
        if (typeof payload.total_points === 'number' && pointsEl) {
          pointsEl.textContent = payload.total_points.toLocaleString('it-IT');
        }
        if (payload.last_update && lastUpdateEl) {
          lastUpdateEl.textContent = formatDate(payload.last_update);
        }
        if (typeof payload.current_value === 'number') {
          updateActivity(payload.current_value);
        }
        updateStatus(true);
      }
    } catch (error) {
      updateStatus(false);
    }
  }

  function bindQuickUpdate() {
    if (!quickUpdateBtn) return;
    quickUpdateBtn.addEventListener('click', async () => {
      if (quickUpdateBtn.disabled) return;
      const originalText = quickUpdateBtn.textContent;
      quickUpdateBtn.disabled = true;
      quickUpdateBtn.textContent = 'Aggiornamento…';
      try {
        await Promise.all([loadChart(), refreshStatus()]);
      } catch (error) {
        // handled in loadChart/refreshStatus
      } finally {
        quickUpdateBtn.disabled = false;
        quickUpdateBtn.textContent = originalText;
      }
    });
  }

  function setupMobileNavObserver() {
    const links = Array.from(document.querySelectorAll('.mobile-quick-link'));
    if (!('IntersectionObserver' in window) || !links.length) {
      return;
    }
    const targets = links
      .map((link) => ({ link, target: document.getElementById(link.dataset.target) }))
      .filter((item) => item.target);
    if (!targets.length) return;

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        targets.forEach(({ link, target }) => {
          if (target === entry.target) {
            link.classList.add('active');
          } else {
            link.classList.remove('active');
          }
        });
      });
    }, { rootMargin: '-30% 0px -60% 0px', threshold: 0.2 });

    targets.forEach(({ target }) => observer.observe(target));
  }

  function init() {
    loadChart().catch(() => {
      /* initial error handled in loadChart */
    });
    refreshStatus();
    bindQuickUpdate();
    setupMobileNavObserver();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
