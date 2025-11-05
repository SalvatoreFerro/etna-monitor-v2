/* global window, document, fetch */
(function () {
  const CURVA_ENDPOINT = '/api/curva';
  const STATUS_ENDPOINT = '/api/status';
  const FORCE_UPDATE_ENDPOINT = '/api/force_update';
  const DEFAULT_LIMIT = 2016;
  const LIMIT_BOUNDS = { min: 1, max: 4032 };
  const FETCH_TIMEOUTS = [5000, 20000];
  const RETRY_DELAYS = [800];
  const LOG_SCALE_MIN = 0.1;
  const LOG_SCALE_MAX = 10;
  const LOG_TICKS = [
    { value: 0.1, label: '10⁻¹' },
    { value: 0.2, label: '0.2' },
    { value: 0.5, label: '0.5' },
    { value: 1, label: '1' },
    { value: 2, label: '2' },
    { value: 5, label: '5' },
    { value: 10, label: '10¹' }
  ];
  const PRIMARY_LINE_COLOR_DARK = '#4ade80';
  const PRIMARY_LINE_COLOR_LIGHT = '#0f172a';
  const PRIMARY_FILL_COLOR_DARK = 'rgba(74, 222, 128, 0.08)';
  const PRIMARY_FILL_COLOR_LIGHT = 'rgba(15, 23, 42, 0.08)';
  const GRID_COLOR_DARK = '#1f2937';
  const GRID_COLOR_LIGHT = '#e2e8f0';
  const AXIS_LINE_COLOR_DARK = '#334155';
  const AXIS_LINE_COLOR_LIGHT = '#94a3b8';
  const THRESHOLD_COLOR_DARK = '#ef4444';
  const THRESHOLD_COLOR_LIGHT = '#b91c1c';
  const HOVER_BG_DARK = 'rgba(15, 23, 42, 0.92)';
  const HOVER_BG_LIGHT = '#f8fafc';
  const THRESHOLD_LEVEL = 4;

  const plotElement = document.getElementById('home-preview-plot');
  const loadingElement = document.getElementById('home-preview-loading');
  const quickUpdateBtn = document.getElementById('quick-update-btn');
  const rangeButtons = Array.from(document.querySelectorAll('.chart-range-btn'));
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
  let currentLimit = DEFAULT_LIMIT;

  if (rangeButtons.length) {
    const activeButton = getActiveRangeButton() || rangeButtons[0];
    currentLimit = resolveLimitFromButton(activeButton);
    setActiveRangeButton(activeButton);
  }

  if (!plotElement || !loadingElement) {
    return;
  }

  if (window.__chartReady) {
    return;
  }
  window.__chartReady = true;

  function fetchWithTimeout(url, options = {}, timeout = FETCH_TIMEOUTS[0]) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeout);
    const config = { ...options, signal: controller.signal };

    return fetch(url, config)
      .finally(() => window.clearTimeout(timer));
  }

  function clampLimit(value) {
    if (!Number.isFinite(value)) {
      return DEFAULT_LIMIT;
    }
    const integer = Math.trunc(value);
    if (integer < LIMIT_BOUNDS.min) {
      return LIMIT_BOUNDS.min;
    }
    if (integer > LIMIT_BOUNDS.max) {
      return LIMIT_BOUNDS.max;
    }
    return integer;
  }

  function resolveLimitFromButton(button) {
    if (!button) {
      return DEFAULT_LIMIT;
    }
    const parsed = Number(button.dataset.limit);
    if (!Number.isFinite(parsed)) {
      return DEFAULT_LIMIT;
    }
    return clampLimit(parsed);
  }

  function buildCurvaUrl(limit) {
    const params = new URLSearchParams();
    const resolved = clampLimit(limit);
    params.set('limit', String(resolved));
    return `${CURVA_ENDPOINT}?${params.toString()}`;
  }

  function getActiveRangeButton() {
    return rangeButtons.find((button) => button.classList.contains('is-active')) || null;
  }

  function setActiveRangeButton(button) {
    rangeButtons.forEach((item) => {
      item.classList.toggle('is-active', item === button);
    });
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
      loadChartWithRetry(currentLimit).catch((error) => {
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
        return {
          timestamp: typeof timestamp === 'string' ? timestamp : String(timestamp),
          value: numericValue,
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

    const filtered = normalized.filter((row) => Number.isFinite(row.value) && row.value > 0);
    if (!filtered.length) {
      throw new Error('Dati non compatibili con scala logaritmica');
    }

    const plotly = await ensurePlotly();

    const timestamps = filtered.map((row) => row.timestamp);
    const values = filtered.map((row) => row.value);
    const clampedValues = values.map((value) => (value >= LOG_SCALE_MIN ? value : LOG_SCALE_MIN));
    const lineColor = PRIMARY_LINE_COLOR_DARK;
    const fillColor = PRIMARY_FILL_COLOR_DARK;
    const gridColor = GRID_COLOR_DARK;
    const axisLineColor = AXIS_LINE_COLOR_DARK;
    const thresholdColor = THRESHOLD_COLOR_DARK;

    const minExponent = Math.log10(Math.min(...clampedValues));
    const maxExponent = Math.log10(Math.max(...clampedValues));
    const yRange = [
      Math.min(Math.log10(LOG_SCALE_MIN), Math.floor(minExponent * 10) / 10),
      Math.max(Math.log10(LOG_SCALE_MAX), Math.ceil(maxExponent * 10) / 10)
    ];

    const trace = {
      x: timestamps,
      y: clampedValues,
      type: 'scatter',
      mode: 'lines',
      name: 'Tremore',
      line: { color: lineColor, width: 2.4, shape: 'spline', smoothing: 1.15 },
      fill: 'tozeroy',
      fillcolor: fillColor,
      hovertemplate: '<b>%{y:.2f} mV</b><br>%{x|%d/%m %H:%M}<extra></extra>',
      showlegend: false
    };

    const shapes = [];
    if (Number.isFinite(THRESHOLD_LEVEL) && THRESHOLD_LEVEL > 0) {
      shapes.push({
        type: 'line',
        x0: timestamps[0],
        x1: timestamps[timestamps.length - 1],
        y0: THRESHOLD_LEVEL,
        y1: THRESHOLD_LEVEL,
        line: { color: thresholdColor, width: 2, dash: 'dash' }
      });
    }

    const layout = {
      margin: { l: 64, r: 32, t: 24, b: 56 },
      hovermode: 'x unified',
      plot_bgcolor: 'rgba(0,0,0,0)',
      paper_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#e2e8f0' },
      xaxis: {
        type: 'date',
        title: '',
        showgrid: true,
        gridcolor: gridColor,
        linewidth: 1,
        linecolor: axisLineColor,
        hoverformat: '%d/%m %H:%M',
        tickfont: { size: 12 },
        ticks: 'outside',
        tickcolor: axisLineColor
      },
      yaxis: {
        title: 'Ampiezza (mV)',
        type: 'log',
        range: yRange,
        showgrid: true,
        gridcolor: gridColor,
        linewidth: 1,
        linecolor: axisLineColor,
        tickfont: { size: 12 },
        tickvals: LOG_TICKS.map((tick) => tick.value),
        ticktext: LOG_TICKS.map((tick) => tick.label),
        ticksuffix: ' mV',
        exponentformat: 'power',
        minor: { ticklen: 4, showgrid: false },
        zeroline: false
      },
      shapes,
      hoverlabel: {
        bgcolor: HOVER_BG_DARK,
        bordercolor: thresholdColor,
        font: { color: '#f8fafc' }
      }
    };

    const config = {
      displayModeBar: false,
      displaylogo: false,
      responsive: true,
      staticPlot: false,
      modeBarButtonsToRemove: ['select2d', 'lasso2d']
    };

    if (chartDrawn) {
      await plotly.react(plotElement, [trace], layout, config);
    } else {
      await plotly.newPlot(plotElement, [trace], layout, config);
      chartDrawn = true;
    }
    plotElement.classList.add('loaded');
    plotElement.removeAttribute('aria-hidden');
    plotElement.style.display = 'block';
    ensureResizeListener();
    hideSpinner();
  }

  async function loadChart(limit, options = {}) {
    const { timeout = FETCH_TIMEOUTS[0], showLoader = true } = options;
    if (showLoader) {
      showSpinner();
    }
    try {
      const response = await fetchWithTimeout(buildCurvaUrl(limit), {
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

  async function loadChartWithRetry(limit, options = {}) {
    let lastError;
    for (let attempt = 0; attempt < FETCH_TIMEOUTS.length; attempt += 1) {
      const timeout = FETCH_TIMEOUTS[Math.min(attempt, FETCH_TIMEOUTS.length - 1)];
      const showLoader = options.showLoader !== false ? attempt === 0 : false;
      try {
        const payload = await loadChart(limit, { timeout, showLoader });
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

  async function forceUpdateCurva() {
    const timeout = FETCH_TIMEOUTS[FETCH_TIMEOUTS.length - 1] || FETCH_TIMEOUTS[0];
    try {
      const response = await fetchWithTimeout(FORCE_UPDATE_ENDPOINT, {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache' }
      }, timeout);
      if (!response.ok) {
        throw new Error('Impossibile contattare il servizio INGV');
      }
      const payload = await response.json();
      if (!payload.ok) {
        throw new Error(payload.error || 'Aggiornamento INGV non riuscito');
      }
      return payload;
    } catch (error) {
      console.error('Errore forza aggiornamento curva', error);
      if (error && error.name === 'AbortError') {
        throw new Error('Timeout durante l\'aggiornamento dei dati INGV');
      }
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('Aggiornamento INGV non riuscito');
    }
  }

  async function performQuickUpdate(options = {}) {
    const { showLoader = !chartDrawn } = options;
    await forceUpdateCurva();
    const payload = await loadChartWithRetry(currentLimit, { showLoader });
    if (payload) {
      lastSuccessfulPayload = payload;
      await drawPlot(payload.data);
      updateMetrics(payload);
      updateStatus(payload.source === 'fallback' ? 'fallback' : 'online');
    }
    return payload;
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
        await performQuickUpdate({ showLoader: !chartDrawn });
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

  async function runGlobalQuickUpdate() {
    if (quickUpdateBtn && !quickUpdateBtn.disabled) {
      quickUpdateBtn.click();
      return;
    }

    try {
      await performQuickUpdate({ showLoader: true });
      await refreshStatus();
    } catch (error) {
      handleLoadError(error, { keepExisting: chartDrawn });
    }
  }

  function bindRangeSelector() {
    if (!rangeButtons.length) return;
    rangeButtons.forEach((button) => {
      button.addEventListener('click', async () => {
        const desiredLimit = resolveLimitFromButton(button);
        if (desiredLimit === currentLimit) {
          return;
        }

        const previousButton = getActiveRangeButton();
        const previousLimit = currentLimit;
        currentLimit = desiredLimit;
        setActiveRangeButton(button);

        try {
          const payload = await loadChartWithRetry(currentLimit, { showLoader: true });
          if (payload) {
            lastSuccessfulPayload = payload;
            await drawPlot(payload.data);
            updateMetrics(payload);
            updateStatus(payload.source === 'fallback' ? 'fallback' : 'online');
          }
        } catch (error) {
          currentLimit = previousLimit;
          const fallbackButton = rangeButtons.find((item) => resolveLimitFromButton(item) === currentLimit) || previousButton;
          setActiveRangeButton(fallbackButton);
          handleLoadError(error, { keepExisting: chartDrawn });
        } finally {
          try {
            await refreshStatus();
          } catch (statusError) {
            updateStatus(false);
          }
        }
      });
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

    loadChartWithRetry(currentLimit, { showLoader: !chartDrawn })
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
    bindRangeSelector();
    bindQuickUpdate();
    setupMobileNavObserver();
  }

  if (typeof window !== 'undefined') {
    window.quickUpdate = runGlobalQuickUpdate;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
