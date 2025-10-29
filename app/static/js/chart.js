/* global window, document, fetch */
(function () {
  const CHART_ENDPOINT = '/api/curva?limit=168';
  const STATUS_ENDPOINT = '/api/status';
  const FETCH_TIMEOUTS = [5000, 20000];
  const RETRY_DELAYS = [800];

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
  const bootstrapScript = document.getElementById('home-bootstrap-data');
  let bootstrapRows = [];
  if (bootstrapScript) {
    try {
      const parsed = JSON.parse(bootstrapScript.textContent || '[]');
      if (Array.isArray(parsed)) {
        bootstrapRows = parsed
          .map((row) => {
            if (!row) return null;
            const timestamp = row.timestamp || row[0];
            const value = row.value ?? row[1];
            const numericValue = Number(value);
            if (!timestamp || Number.isNaN(numericValue)) return null;
            return {
              timestamp: typeof timestamp === 'string' ? timestamp : String(timestamp),
              value: numericValue,
            };
          })
          .filter(Boolean);
      }
      bootstrapScript.remove();
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error('Impossibile analizzare i dati bootstrap del grafico', error);
      bootstrapRows = [];
    }
  }

  let resizeBound = false;
  let chartDrawn = false;
  let plotlyReadyPromise = null;
  let noticeTimer = null;
  let lastSuccessfulPayload = null;

  if (!plotElement || !loadingElement) {
    return;
  }

  function fetchWithTimeout(url, options = {}, timeout = FETCH_TIMEOUTS[0]) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeout);
    const config = { ...options, signal: controller.signal };

    return fetch(url, config)
      .finally(() => window.clearTimeout(timer));
  }

  function showSpinner() {
    if (!loadingElement) return;
    if (noticeTimer) {
      window.clearTimeout(noticeTimer);
      noticeTimer = null;
    }
    loadingElement.classList.remove('chart-notice');
    loadingElement.innerHTML = defaultLoadingMarkup;
    loadingElement.hidden = false;
    loadingElement.setAttribute('aria-hidden', 'false');
  }

  function hideSpinner() {
    if (!loadingElement) return;
    if (noticeTimer) {
      window.clearTimeout(noticeTimer);
      noticeTimer = null;
    }
    loadingElement.classList.remove('chart-notice');
    loadingElement.hidden = true;
    loadingElement.setAttribute('aria-hidden', 'true');
  }

  function updateStatus(state) {
    if (!statusIndicator || !statusText) return;
    let statusState;
    if (typeof state === 'string') {
      if (state === 'fallback') {
        statusState = 'fallback';
      } else if (state === 'offline') {
        statusState = 'offline';
      } else {
        statusState = 'online';
      }
    } else {
      statusState = state ? 'online' : 'offline';
    }
    statusIndicator.classList.toggle('online', statusState === 'online');
    statusIndicator.classList.toggle('offline', statusState === 'offline');
    statusIndicator.classList.toggle('fallback', statusState === 'fallback');

    if (statusState === 'fallback') {
      statusText.textContent = 'Dati backup';
    } else {
      statusText.textContent = statusState === 'online' ? 'Dati online' : 'Connessione assente';
    }
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
      loadChartWithRetry().catch((error) => {
        handleLoadError(error);
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

  function normalizeRows(rows) {
    if (!Array.isArray(rows)) return [];
    return rows
      .map((row) => {
        if (!row) return null;
        const timestamp = row.timestamp || row[0];
        const rawValue = row.value ?? row[1];
        const numericValue = Number(rawValue);
        if (!timestamp || Number.isNaN(numericValue)) return null;
        const sanitized = numericValue > 0 ? numericValue : 0.0001;
        return {
          timestamp: typeof timestamp === 'string' ? timestamp : String(timestamp),
          value: numericValue,
          plotValue: sanitized,
        };
      })
      .filter(Boolean);
  }

  function ensurePlotly() {
    if (window.Plotly) {
      return Promise.resolve(window.Plotly);
    }
    if (plotlyReadyPromise) {
      return plotlyReadyPromise;
    }

    plotlyReadyPromise = new Promise((resolve, reject) => {
      const step = 100;
      const timeout = 8000;
      let elapsed = 0;

      const checkReady = () => {
        if (window.Plotly) {
          resolve(window.Plotly);
          return true;
        }
        return false;
      };

      if (checkReady()) {
        return;
      }

      const poller = window.setInterval(() => {
        elapsed += step;
        if (checkReady()) {
          window.clearInterval(poller);
        } else if (elapsed >= timeout) {
          window.clearInterval(poller);
          reject(new Error('Plotly non disponibile'));
        }
      }, step);

      const script = Array.from(document.getElementsByTagName('script')).find((el) => el.src && el.src.includes('plotly'));
      if (script) {
        script.addEventListener('load', () => {
          if (checkReady()) {
            window.clearInterval(poller);
          }
        }, { once: true });
        script.addEventListener('error', () => {
          window.clearInterval(poller);
          reject(new Error('Plotly non disponibile'));
        }, { once: true });
      }
    }).catch((error) => {
      plotlyReadyPromise = null;
      throw error;
    });

    return plotlyReadyPromise;
  }

  async function drawPlot(rows) {
    const normalized = normalizeRows(rows);
    if (!normalized.length) {
      throw new Error('Dati non disponibili');
    }

    const plotly = await ensurePlotly();

    const timestamps = normalized.map((row) => row.timestamp);
    const values = normalized.map((row) => row.plotValue);

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

    if (chartDrawn) {
      await plotly.react(plotElement, [trace], layout, config);
    } else {
      await plotly.newPlot(plotElement, [trace], layout, config);
      chartDrawn = true;
    }
    plotElement.classList.add('loaded');
    plotElement.removeAttribute('aria-hidden');
    ensureResizeListener();
    hideSpinner();
  }

  async function loadChart(options = {}) {
    const { timeout = FETCH_TIMEOUTS[0], showLoader = true } = options;
    if (showLoader) {
      showSpinner();
    }
    try {
      const response = await fetchWithTimeout(CHART_ENDPOINT, {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache' }
      }, timeout);
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
      return payload;
    } catch (error) {
      console.error('Errore caricamento curva', error);
      throw error;
    }
  }

  async function loadChartWithRetry(options = {}) {
    let lastError;
    for (let attempt = 0; attempt < FETCH_TIMEOUTS.length; attempt += 1) {
      const timeout = FETCH_TIMEOUTS[Math.min(attempt, FETCH_TIMEOUTS.length - 1)];
      const showLoader = options.showLoader !== false ? attempt === 0 : false;
      try {
        const payload = await loadChart({ timeout, showLoader });
        return payload;
      } catch (error) {
        lastError = error;
        const isAbort = error && error.name === 'AbortError';
        if (!isAbort || attempt === FETCH_TIMEOUTS.length - 1) {
          break;
        }
        const delay = RETRY_DELAYS[Math.min(attempt, RETRY_DELAYS.length - 1)] || 0;
        if (delay) {
          await new Promise((resolve) => window.setTimeout(resolve, delay));
        }
      }
    }
    throw lastError;
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
        const fallbackActive = (lastSuccessfulPayload && lastSuccessfulPayload.source === 'fallback')
          || (statusIndicator && statusIndicator.classList.contains('fallback'));
        updateStatus(fallbackActive ? 'fallback' : 'online');
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
        const payload = await loadChartWithRetry({ showLoader: !chartDrawn });
        if (payload) {
          await drawPlot(payload.data);
          updateMetrics(payload);
          updateStatus(payload.source === 'fallback' ? 'fallback' : 'online');
          lastSuccessfulPayload = payload;
        }
      } catch (error) {
        handleLoadError(error, { keepExisting: chartDrawn });
      } finally {
        try {
          await refreshStatus();
        } catch (error) {
          updateStatus(false);
        }
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

  function handleLoadError(error, options = {}) {
    const { keepExisting = false } = options;
    const isAbort = error && error.name === 'AbortError';
    const message = isAbort
      ? 'Timeout di rete, riprova.'
      : (error && error.message ? error.message : 'Impossibile caricare il grafico');
    if (keepExisting && chartDrawn) {
      if (noticeTimer) {
        window.clearTimeout(noticeTimer);
        noticeTimer = null;
      }
      if (loadingElement) {
        loadingElement.classList.add('chart-notice');
        loadingElement.innerHTML = `<p>${message}</p>`;
        loadingElement.hidden = false;
        loadingElement.setAttribute('aria-hidden', 'false');
        noticeTimer = window.setTimeout(() => {
          if (!loadingElement) return;
          loadingElement.hidden = true;
          loadingElement.setAttribute('aria-hidden', 'true');
          loadingElement.classList.remove('chart-notice');
          noticeTimer = null;
        }, 6000);
      }
    } else {
      showError(message);
    }
    updateStatus('offline');
  }

  async function init() {
    if (bootstrapRows.length) {
      try {
        await drawPlot(bootstrapRows);
        updateMetrics({
          data: bootstrapRows,
          rows: bootstrapRows.length,
          last_ts: bootstrapRows[bootstrapRows.length - 1]
            ? bootstrapRows[bootstrapRows.length - 1].timestamp
            : undefined,
        });
        updateStatus('online');
      } catch (error) {
        console.error('Errore rendering dati bootstrap', error);
        showSpinner();
      }
    } else {
      showSpinner();
    }

    loadChartWithRetry({ showLoader: !chartDrawn })
      .then(async (payload) => {
        lastSuccessfulPayload = payload;
        await drawPlot(payload.data);
        updateMetrics(payload);
        updateStatus(payload.source === 'fallback' ? 'fallback' : 'online');
      })
      .catch((error) => {
        handleLoadError(error, { keepExisting: chartDrawn });
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
