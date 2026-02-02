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
const DEFAULT_THEME_COLORS = {
    dark: {
        line: '#4ade80',
        fill: 'rgba(74, 222, 128, 0.1)',
        grid: 'rgba(148, 163, 184, 0.14)',
        axis: 'rgba(148, 163, 184, 0.65)',
        threshold: '#fca5a5',
        hoverBg: 'rgba(8, 15, 30, 0.92)'
    },
    light: {
        line: '#1d4ed8',
        fill: 'rgba(37, 99, 235, 0.12)',
        grid: 'rgba(148, 163, 184, 0.35)',
        axis: '#475569',
        threshold: '#dc2626',
        hoverBg: '#f8fafc'
    }
};
const ANALYZE_HINT_KEY = 'dashboardAnalyzeHintSeen';

class EtnaDashboard {
    constructor() {
        this.ingvMode = localStorage.getItem('ingv-mode') === 'true';
        this.autoRefreshInterval = null;
        this.refreshCountdown = null;
        this.plotData = null;
        this.analyzeModeEnabled = false;
        this.focusModeOpen = false;
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
        this.setupTelegramValidation();
        this.setupThemeToggle();
        this.setupINGVMode();
        this.setupFocusMode();
        this.setupAutoRefresh();
        this.setupMissions();
        this.loadInitialData();

        if ('serviceWorker' in navigator) {
            const swVersion = window.__STATIC_ASSET_VERSION__ || 'v1';
            const swUrl = `/static/sw.js?v=${encodeURIComponent(swVersion)}`;
            navigator.serviceWorker.register(swUrl).catch(() => {});
        }
    }

    setupEventListeners() {
        const updateBtn = document.getElementById('update-btn');
        if (updateBtn) {
            updateBtn.addEventListener('click', () => this.forceUpdate());
        }

        const timeRange = document.getElementById('time-range');
        if (timeRange) {
            timeRange.addEventListener('change', () => this.loadData());
        }
        
        const thresholdSlider = document.getElementById('threshold-slider');
        const thresholdInput = document.getElementById('threshold-input');
        const saveThreshold = document.getElementById('save-threshold');
        
        if (thresholdSlider && thresholdInput) {
            thresholdSlider.addEventListener('input', (e) => {
                thresholdInput.value = e.target.value;
                this.updateActiveThresholdDisplay(parseFloat(e.target.value), 'user/custom');
            });
            
            thresholdInput.addEventListener('input', (e) => {
                thresholdSlider.value = e.target.value;
                this.updateActiveThresholdDisplay(parseFloat(e.target.value), 'user/custom');
            });
        }
        
        if (saveThreshold) {
            saveThreshold.addEventListener('click', () => this.saveThreshold());
        }
        
        const exportCSV = document.getElementById('export-csv');
        const exportPNG = document.getElementById('export-png');
        
        if (exportCSV) {
            exportCSV.addEventListener('click', () => this.exportData('csv'));
        }
        
        if (exportPNG) {
            exportPNG.addEventListener('click', () => this.exportData('png'));
        }

        const analyzeToggle = document.getElementById('dashboard-analyze-toggle');
        if (analyzeToggle) {
            analyzeToggle.addEventListener('click', () => this.toggleAnalyzeMode());
        }

        const resetView = document.getElementById('dashboard-reset-view');
        if (resetView) {
            resetView.addEventListener('click', () => this.resetPlotView());
        }

        this.updateAnalyzeUI();
        
        // Mission claim buttons
        this.setupMissionClaim();
    }
    
    setupMissionClaim() {
        const claimButtons = document.querySelectorAll('[data-mission-claim]');
        claimButtons.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.preventDefault();
                const missionId = btn.dataset.missionId;
                if (!missionId) return;
                
                const originalText = btn.textContent;
                btn.disabled = true;
                btn.textContent = 'Riscattando...';
                
                try {
                    const response = await fetch(`/api/missions/${missionId}/claim`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            csrf_token: this.getCSRFToken()
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (data.ok) {
                        this.showToast(`✓ Ricompensa riscattata! +${data.points_awarded} punti`, 'success');
                        setTimeout(() => window.location.reload(), 1500);
                    } else {
                        this.showToast(`✕ Errore: ${data.error || 'Impossibile riscattare'}`, 'error');
                        btn.disabled = false;
                        btn.textContent = originalText;
                    }
                } catch (error) {
                    console.error('Mission claim error:', error);
                    this.showToast('✕ Errore di rete', 'error');
                    btn.disabled = false;
                    btn.textContent = originalText;
                }
            });
        });
    }

    setupTelegramValidation() {
        const chatInput = document.getElementById('chat_id');
        const validationEl = document.getElementById('chat-id-validation');

        if (!chatInput || !validationEl) {
            return;
        }

        const updateStatus = () => {
            const value = chatInput.value.trim();
            if (!value) {
                validationEl.textContent = '';
                validationEl.classList.remove('is-valid', 'is-invalid');
                return;
            }

            const numeric = /^[0-9]+$/.test(value);
            const nonZero = numeric && !/^0+$/.test(value);

            if (numeric && nonZero) {
                validationEl.textContent = 'ID valido';
                validationEl.classList.add('is-valid');
                validationEl.classList.remove('is-invalid');
            } else {
                validationEl.textContent = 'ID non valido';
                validationEl.classList.add('is-invalid');
                validationEl.classList.remove('is-valid');
            }
        };

        chatInput.addEventListener('input', updateStatus);
        chatInput.addEventListener('blur', updateStatus);
        updateStatus();
    }

    setupFocusMode() {
        const plotDiv = document.getElementById('tremor-plot');
        const focusModal = document.getElementById('tremor-focus-modal');
        const focusClose = document.getElementById('focus-close');
        const focusReset = document.getElementById('focus-reset-view');
        const focusBackdrop = focusModal?.querySelector('[data-focus-close]');

        if (!plotDiv || !focusModal) {
            return;
        }

        // Tap/click sul grafico per entrare in modalità Focus (mobile-first).
        plotDiv.addEventListener('click', (event) => {
            if (!this.shouldOpenFocus(event)) return;
            this.openFocusMode();
        });

        plotDiv.addEventListener('keydown', (event) => {
            if ((event.key === 'Enter' || event.key === ' ') && this.shouldOpenFocus(event)) {
                event.preventDefault();
                this.openFocusMode();
            }
        });

        if (focusClose) {
            focusClose.addEventListener('click', () => this.closeFocusMode());
        }

        if (focusBackdrop) {
            focusBackdrop.addEventListener('click', () => this.closeFocusMode());
        }

        if (focusReset) {
            focusReset.addEventListener('click', () => this.resetFocusView());
        }

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && this.focusModeOpen) {
                this.closeFocusMode();
            }
        });

        window.addEventListener('resize', () => {
            if (this.focusModeOpen && window.Plotly) {
                const focusPlot = document.getElementById('tremor-plot-focus');
                if (focusPlot && focusPlot.data) {
                    Plotly.Plots.resize(focusPlot);
                }
            }
        });
    }

    shouldOpenFocus(event) {
        if (this.focusModeOpen || this.analyzeModeEnabled) return false;
        if (event && event.target && event.target.closest && event.target.closest('.modebar')) return false;
        return true;
    }

    openFocusMode() {
        const focusModal = document.getElementById('tremor-focus-modal');
        const focusClose = document.getElementById('focus-close');
        const plotDiv = document.getElementById('tremor-plot');

        if (!focusModal || !plotDiv || !window.Plotly) {
            return;
        }

        this.focusModeOpen = true;
        focusModal.classList.add('is-open');
        focusModal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('focus-modal-open');
        this.renderFocusPlot(plotDiv);

        if (focusClose) {
            focusClose.focus();
        }
    }

    closeFocusMode() {
        const focusModal = document.getElementById('tremor-focus-modal');
        if (!focusModal) return;

        this.focusModeOpen = false;
        focusModal.classList.remove('is-open');
        focusModal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('focus-modal-open');
    }

    resetFocusView() {
        const focusPlot = document.getElementById('tremor-plot-focus');
        if (focusPlot && window.Plotly && focusPlot.data) {
            Plotly.relayout(focusPlot, {
                'xaxis.autorange': true,
                'yaxis.autorange': true,
                dragmode: 'pan'
            });
        }
    }

    renderFocusPlot(basePlotDiv) {
        const focusPlot = document.getElementById('tremor-plot-focus');
        if (!focusPlot || !basePlotDiv || !basePlotDiv.data) return;

        const focusLayout = this.buildFocusLayout(basePlotDiv.layout);
        const focusConfig = {
            displayModeBar: false,
            displaylogo: false,
            responsive: true,
            staticPlot: false,
            scrollZoom: true,
            doubleClick: 'reset',
            modeBarButtonsToRemove: ['select2d', 'lasso2d']
        };

        Plotly.react(focusPlot, basePlotDiv.data, focusLayout, focusConfig);
    }

    buildFocusLayout(baseLayout = {}) {
        const focusLayout = {
            ...baseLayout,
            margin: { l: 72, r: 40, t: 56, b: 72 },
            dragmode: 'pan',
            hovermode: 'x'
        };

        if (focusLayout.xaxis) {
            focusLayout.xaxis = {
                ...focusLayout.xaxis,
                automargin: true,
                tickfont: { ...(focusLayout.xaxis.tickfont || {}), size: 13 },
                tickpadding: 8,
                fixedrange: false
            };
        }

        if (focusLayout.yaxis) {
            focusLayout.yaxis = {
                ...focusLayout.yaxis,
                automargin: true,
                tickfont: { ...(focusLayout.yaxis.tickfont || {}), size: 13 },
                tickpadding: 8,
                fixedrange: false
            };
        }

        return focusLayout;
    }

    getTickFormatStops() {
        return [
            { dtickrange: [null, 3600000], value: '%H:%M' },
            { dtickrange: [3600000, 86400000], value: '%d %b' },
            { dtickrange: [86400000, 604800000], value: '%d %b' },
            { dtickrange: [604800000, 'M1'], value: '%d %b' },
            { dtickrange: ['M1', 'M12'], value: '%b %Y' },
            { dtickrange: ['M12', null], value: '%Y' }
        ];
    }

    getSelectedLimit() {
        const select = document.getElementById('time-range');
        const defaultLimit = 2016;
        if (!select) {
            return defaultLimit;
        }
        const parsed = parseInt(select.value, 10);
        if (Number.isNaN(parsed)) {
            return defaultLimit;
        }
        const clamped = Math.min(Math.max(parsed, 1), 4032);
        return clamped;
    }

    getCssVariable(name, fallback) {
        const value = getComputedStyle(document.documentElement).getPropertyValue(name);
        return value ? value.trim() : fallback;
    }

    getThemeColors(isDark) {
        const defaults = isDark ? DEFAULT_THEME_COLORS.dark : DEFAULT_THEME_COLORS.light;
        return {
            line: this.getCssVariable('--chart-line-color', defaults.line),
            fill: this.getCssVariable('--chart-fill-color', defaults.fill),
            grid: this.getCssVariable('--chart-grid-color', defaults.grid),
            axis: this.getCssVariable('--chart-axis-color', defaults.axis),
            threshold: this.getCssVariable('--chart-threshold-color', defaults.threshold),
            hoverBg: this.getCssVariable('--chart-hover-bg', defaults.hoverBg)
        };
    }

    getActiveThresholdData() {
        const thresholdElement = document.getElementById('active-threshold');
        if (!thresholdElement) {
            return { threshold: 2.0, source: 'default', debug: false };
        }
        const thresholdValue = parseFloat(thresholdElement.dataset.threshold);
        return {
            threshold: Number.isFinite(thresholdValue) ? thresholdValue : 2.0,
            source: thresholdElement.dataset.source || 'default',
            debug: thresholdElement.dataset.debug === '1'
        };
    }

    getActiveThreshold() {
        const thresholdSlider = document.getElementById('threshold-slider');
        if (thresholdSlider) {
            const sliderValue = parseFloat(thresholdSlider.value);
            if (Number.isFinite(sliderValue)) {
                return sliderValue;
            }
        }
        return this.getActiveThresholdData().threshold;
    }

    updateActiveThresholdDisplay(thresholdValue, sourceOverride) {
        const thresholdElement = document.getElementById('active-threshold');
        if (!thresholdElement) {
            return;
        }
        const { source } = this.getActiveThresholdData();
        const resolvedSource = sourceOverride || source || 'default';
        const normalizedValue = Number.isFinite(thresholdValue)
            ? thresholdValue
            : this.getActiveThresholdData().threshold;
        thresholdElement.dataset.threshold = normalizedValue.toFixed(2);
        thresholdElement.dataset.source = resolvedSource;
        const label = resolvedSource === 'user/custom' ? 'personalizzata' : 'default';
        thresholdElement.textContent = `Soglia attiva: ${normalizedValue.toFixed(2)} mV (${label})`;
    }

    updateDebugThresholdLabel(currentValue, thresholdValue, source) {
        const { debug } = this.getActiveThresholdData();
        if (!debug) {
            return;
        }
        const debugLabel = document.getElementById('debug-threshold');
        if (!debugLabel) {
            return;
        }
        const safeCurrent = Number.isFinite(currentValue) ? currentValue.toFixed(2) : '--';
        const safeThreshold = Number.isFinite(thresholdValue) ? thresholdValue.toFixed(2) : '--';
        debugLabel.textContent = `DEBUG: threshold_used_for_badge=${safeThreshold} | source=${source} | current=${safeCurrent}`;
    }

    setupThemeToggle() {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('theme', 'dark');
        
        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            themeToggle.style.display = 'none';
        }
    }
    
    setupINGVMode() {
        const ingvToggle = document.getElementById('ingv-mode');
        if (ingvToggle) {
            ingvToggle.checked = this.ingvMode;
            ingvToggle.addEventListener('change', (e) => {
                this.ingvMode = e.target.checked;
                localStorage.setItem('ingv-mode', this.ingvMode);
                
                if (this.plotData) {
                    this.renderPlot(this.plotData);
                }
                
                this.showToast(
                    this.ingvMode ? 'Modalità INGV attivata' : 'Modalità moderna attivata',
                    'info'
                );
            });
        }
    }
    
    setupAutoRefresh() {
        const autoRefresh = document.getElementById('auto-refresh');
        if (autoRefresh) {
            const savedInterval = localStorage.getItem('auto-refresh') || '300000';
            autoRefresh.value = savedInterval;
            
            autoRefresh.addEventListener('change', (e) => {
                const interval = parseInt(e.target.value);
                localStorage.setItem('auto-refresh', interval);
                this.setAutoRefresh(interval);
            });
            
            this.setAutoRefresh(parseInt(savedInterval));
        }
    }
    
    setAutoRefresh(interval) {
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
        }
        
        if (this.refreshCountdown) {
            clearInterval(this.refreshCountdown);
        }
        
        if (interval > 0) {
            this.autoRefreshInterval = setInterval(() => {
                this.loadData();
            }, interval);
            
            this.startCountdown(interval);
        }
    }
    
    startCountdown(interval) {
        let remaining = interval / 1000;
        const countdownElement = document.getElementById('refresh-countdown');
        
        this.refreshCountdown = setInterval(() => {
            remaining--;
            if (countdownElement) {
                const minutes = Math.floor(remaining / 60);
                const seconds = remaining % 60;
                countdownElement.textContent = `Prossimo aggiornamento: ${minutes}:${seconds.toString().padStart(2, '0')}`;
            }
            
            if (remaining <= 0) {
                remaining = interval / 1000;
            }
        }, 1000);
    }
    
    async loadInitialData() {
        await this.loadData();
        await this.loadStatus();
    }
    
    async loadData() {
        try {
            const limit = this.getSelectedLimit();
            const response = await fetch(`/api/curva?limit=${limit}`);
            const data = await response.json();
            
            if (data.ok && data.data) {
                this.plotData = data;
                this.renderPlot(data);
                this.updateStats(data);
            } else {
                this.showNoDataMessage();
            }
        } catch (error) {
            console.error('Error loading data:', error);
            this.showToast('Errore nel caricamento dati', 'error');
        }
    }
    
    async loadStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();
            
            if (data.ok) {
                this.updateStatus(data);
            }
        } catch (error) {
            console.error('Errore nel caricamento stato:', error);
        }
    }

    isThresholdTrace(trace) {
        if (!trace) return false;
        const name = (trace.name || '').toLowerCase();
        const dash = trace?.line?.dash;
        if (name.includes('soglia') || name.includes('threshold')) {
            return true;
        }
        if (dash && dash !== 'solid') {
            return true;
        }
        return false;
    }

    isGreenLine(color) {
        if (!color || typeof color !== 'string') return false;
        const normalized = color.toLowerCase();
        const knownGreens = ['#4ade80', '#00aa00', '#22c55e', '#16a34a', '#4caf50', '#2ecc71'];
        if (knownGreens.includes(normalized)) {
            return true;
        }
        if (normalized.includes('green')) {
            return true;
        }
        const rgbMatch = normalized.match(/rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)/);
        if (!rgbMatch) {
            return false;
        }
        const [r, g, b] = rgbMatch.slice(1).map((value) => parseInt(value, 10));
        return g > r + 20 && g > b + 20;
    }

    applyMobileTraceOverrides(traces, { isMobile } = {}) {
        if (!isMobile || !Array.isArray(traces)) {
            return traces;
        }

        const cloned = traces.map((trace) => ({
            ...trace,
            line: trace?.line ? { ...trace.line } : undefined,
            marker: trace?.marker ? { ...trace.marker } : undefined
        }));

        const dataRichIndexes = cloned
            .map((trace, index) => {
                const hasDenseData = Array.isArray(trace?.x) && Array.isArray(trace?.y)
                    && trace.x.length > 2
                    && trace.y.length > 2;
                return hasDenseData ? index : null;
            })
            .filter((index) => index !== null);

        const primaryIndexes = new Set();
        cloned.forEach((trace, index) => {
            const name = (trace.name || '').toLowerCase();
            if (name.includes('tremore')) {
                primaryIndexes.add(index);
            } else if (this.isGreenLine(trace?.line?.color)) {
                primaryIndexes.add(index);
            }
        });

        if (!primaryIndexes.size && dataRichIndexes.length === 1) {
            primaryIndexes.add(dataRichIndexes[0]);
        }

        const fallbackWidthIndexes = new Set();
        if (!primaryIndexes.size) {
            cloned.forEach((trace, index) => {
                if (this.isThresholdTrace(trace)) {
                    return;
                }
                const dash = trace?.line?.dash;
                if (this.isGreenLine(trace?.line?.color) || !dash || dash === 'solid') {
                    fallbackWidthIndexes.add(index);
                }
            });
        }

        cloned.forEach((trace, index) => {
            if (this.isThresholdTrace(trace)) {
                return;
            }
            trace.mode = 'lines';
            if (trace.marker) {
                trace.marker = { ...trace.marker, size: 0 };
            }
            if (trace.fill !== undefined) {
                trace.fill = null;
            }
            if (primaryIndexes.has(index) || fallbackWidthIndexes.has(index)) {
                if (!trace.line) {
                    trace.line = {};
                }
                trace.line.width = 0.8;
            }
        });

        return cloned;
    }
    
    renderPlot(data) {
        const plotDiv = document.getElementById('tremor-plot');
        if (!plotDiv) return;

        const rows = Array.isArray(data.data) ? data.data : [];
        const normalized = rows
            .map((row) => {
                if (!row) return null;
                const timestamp = row.timestamp || row[0];
                const rawValue = row.value ?? row[1];
                const numericValue = Number(rawValue);
                if (!timestamp || Number.isNaN(numericValue)) return null;
                return { timestamp, value: numericValue };
            })
            .filter((row) => row && Number.isFinite(row.value) && row.value > 0);

        if (!normalized.length) {
            this.showNoDataMessage();
            return;
        }

        console.log(`curva loaded: ${data.rows}, last_ts: ${data.last_ts}`);

        const timestamps = normalized.map((row) => row.timestamp);
        const values = normalized.map((row) => row.value);
        const clampedValues = values.map((value) => (value >= LOG_SCALE_MIN ? value : LOG_SCALE_MIN));

        const threshold = this.getActiveThreshold();
        const { source, debug } = this.getActiveThresholdData();
        if (debug) {
            console.info(`plot_threshold=${threshold.toFixed(2)} source=${source}`);
        }

        const hasExistingPlot = Boolean(plotDiv.data && plotDiv.data.length);
        const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        const themeColors = this.getThemeColors(isDark);
        const isMobile = window.matchMedia('(max-width: 640px)').matches;
        const tickFormatStops = this.getTickFormatStops();
        const fontFamily = "'Inter', 'Roboto', 'Helvetica Neue', 'Arial', sans-serif";

        const mobileMargins = { l: 48, r: 12, t: 18, b: 42 };

        if (this.ingvMode) {
            const layout = {
                title: 'ECBD - RMS (UTC Time)',
                title_font: { size: 14, color: 'black' },
                dragmode: this.analyzeModeEnabled ? 'select' : 'pan',
                xaxis: {
                    title: '',
                    showgrid: true,
                    gridwidth: 1,
                    gridcolor: 'lightgray',
                    tickangle: -90,
                    tickformat: '%d/%m\n%H:%M',
                    tickfont: { size: 10 }
                },
                yaxis: {
                    title: 'Amplitude (mV)',
                    type: 'log',
                    range: [Math.log10(LOG_SCALE_MIN), Math.log10(LOG_SCALE_MAX)],
                    showgrid: true,
                    gridwidth: 1,
                    gridcolor: 'lightgray',
                    tickvals: LOG_TICKS.map((tick) => tick.value),
                    ticktext: LOG_TICKS.map((tick) => tick.label),
                    tickfont: { size: 10 }
                },
                template: 'plotly_white',
                plot_bgcolor: 'white',
                paper_bgcolor: 'white',
                font: { family: 'Arial', size: 12, color: 'black' },
                autosize: true,
                margin: isMobile ? mobileMargins : { l: 60, r: 18, t: 36, b: 40 },
                showlegend: false,
                shapes: threshold > 0 ? [{
                    type: 'line',
                    x0: timestamps[0],
                    x1: timestamps[timestamps.length - 1],
                    y0: threshold,
                    y1: threshold,
                    line: { color: themeColors.threshold || '#FF0000', width: 1, dash: 'solid' }
                }] : []
            };

            const trace = {
                x: timestamps,
                y: clampedValues,
                type: 'scatter',
                mode: 'lines',
                name: 'RMS',
                line: {
                    color: '#00AA00',
                    width: isMobile ? 1.0 : 1.6
                },
                hovertemplate: '<b>%{y:.2f} mV</b><br>%{x|%d/%m %H:%M}<extra></extra>',
                showlegend: false
            };
            const traces = this.applyMobileTraceOverrides([trace], { isMobile });

            const config = {
                displayModeBar: false,
                responsive: true,
                staticPlot: false,
                scrollZoom: false,
                doubleClick: false
            };

            if (hasExistingPlot) {
                Plotly.react(plotDiv, traces, layout, config);
            } else {
                Plotly.newPlot(plotDiv, traces, layout, config);
            }
            this.applyInteractionState(plotDiv);
            this.syncFocusPlot(plotDiv);
            return;
        }
        const { line: lineColor, fill: fillColor, grid: gridColor, axis: axisLineColor, threshold: thresholdColor, hoverBg } = themeColors;

        const minExponent = Math.log10(Math.min(...clampedValues));
        const maxExponent = Math.log10(Math.max(...clampedValues));
        const yRange = [
            Math.min(Math.log10(LOG_SCALE_MIN), Math.floor(minExponent * 10) / 10),
            Math.max(Math.log10(LOG_SCALE_MAX), Math.ceil(maxExponent * 10) / 10)
        ];

        // Linea soglia con etichetta discreta per mantenere chiarezza scientifica.
        const shapes = threshold > 0 ? [{
            type: 'line',
            x0: timestamps[0],
            x1: timestamps[timestamps.length - 1],
            y0: threshold,
            y1: threshold,
            line: { color: thresholdColor, width: 1, dash: 'dash' }
        }] : [];

        const annotations = threshold > 0 ? [{
            x: timestamps[timestamps.length - 1],
            y: threshold,
            xref: 'x',
            yref: 'y',
            text: 'Soglia di attenzione',
            showarrow: false,
            xanchor: 'right',
            yanchor: 'bottom',
            xshift: -6,
            yshift: 6,
            font: { size: 11, color: thresholdColor }
        }] : [];

        const trace = {
            x: timestamps,
            y: clampedValues,
            type: 'scatter',
            mode: 'lines',
            name: 'Segnale Tremore',
            line: {
                color: lineColor,
                width: isMobile ? 1.0 : 2,
                shape: 'spline',
                smoothing: 1.1
            },
            fill: isMobile ? 'none' : 'tozeroy',
            fillcolor: isMobile ? undefined : fillColor,
            hovertemplate: '%{x|%d %b %Y %H:%M}<br><b>%{y:.2f} mV</b><extra></extra>',
            showlegend: false
        };
        const traces = this.applyMobileTraceOverrides([trace], { isMobile });

        const layout = {
            autosize: true,
            margin: isMobile ? mobileMargins : { l: 64, r: 36, t: 48, b: 56 },
            hovermode: 'x',
            dragmode: this.analyzeModeEnabled ? 'select' : 'pan',
            plot_bgcolor: 'rgba(0,0,0,0)',
            paper_bgcolor: 'rgba(0,0,0,0)',
            font: { color: isDark ? '#e2e8f0' : '#0f172a', family: fontFamily, size: 12 },
            xaxis: {
                type: 'date',
                title: '',
                showgrid: true,
                gridcolor: gridColor,
                gridwidth: 0.6,
                linewidth: 1,
                linecolor: axisLineColor,
                hoverformat: '%d/%m %H:%M',
                tickfont: { size: 10 },
                tickpadding: isMobile ? 8 : 6,
                nticks: isMobile ? 4 : 6,
                tickformatstops: tickFormatStops,
                automargin: true,
                ticks: 'outside',
                tickcolor: axisLineColor
            },
            yaxis: {
                title: 'Ampiezza (mV)',
                type: 'log',
                range: yRange,
                showgrid: true,
                gridcolor: gridColor,
                gridwidth: 0.6,
                linewidth: 1,
                linecolor: axisLineColor,
                tickfont: { size: 10 },
                tickpadding: isMobile ? 8 : 6,
                tickvals: LOG_TICKS.map((tick) => tick.value),
                ticktext: LOG_TICKS.map((tick) => tick.label),
                ticksuffix: ' mV',
                exponentformat: 'power',
                minor: { ticklen: 4, showgrid: false },
                zeroline: false,
                automargin: true
            },
            shapes,
            annotations,
            hoverlabel: {
                bgcolor: hoverBg,
                bordercolor: thresholdColor,
                font: { color: isDark ? '#f8fafc' : '#0f172a', family: fontFamily, size: 12 }
            }
        };

        const config = {
            displayModeBar: false,
            displaylogo: false,
            responsive: true,
            staticPlot: false,
            scrollZoom: false,
            doubleClick: false,
            modeBarButtonsToRemove: ['select2d', 'lasso2d']
        };

        if (hasExistingPlot) {
            Plotly.react(plotDiv, traces, layout, config);
        } else {
            Plotly.newPlot(plotDiv, traces, layout, config);
        }

        plotDiv.classList.add('loaded');
        this.applyInteractionState(plotDiv);
        this.syncFocusPlot(plotDiv);
    }

    syncFocusPlot(plotDiv) {
        if (!this.focusModeOpen || !plotDiv) return;
        this.renderFocusPlot(plotDiv);
    }
    
    updateStats(data) {
        const lastUpdated = document.getElementById('last-updated');
        const dataPoints = document.getElementById('data-points');
        const trendStatus = document.getElementById('trend-status');
        
        const updatedAt = data.updated_at || data.last_ts;
        if (lastUpdated && updatedAt) {
            const timestampLabel = new Date(updatedAt).toLocaleString();
            const staleSuffix = data.is_stale ? ' · dato non aggiornato' : '';
            lastUpdated.textContent = `Ultimo aggiornamento: ${timestampLabel}${staleSuffix}`;
        }
        
        if (dataPoints) {
            dataPoints.textContent = `${data.data.length} punti`;
        }

        if (trendStatus) {
            const rows = Array.isArray(data.data) ? data.data : [];
            const values = rows
                .map((row) => {
                    if (!row) return null;
                    const rawValue = row.value ?? row[1];
                    const numericValue = Number(rawValue);
                    return Number.isFinite(numericValue) ? numericValue : null;
                })
                .filter((value) => value !== null);
            if (values.length >= 2) {
                const latest = values[values.length - 1];
                const previous = values[values.length - 2];
                const delta = latest - previous;
                const threshold = Math.max(0.02, Math.abs(latest) * 0.01);
                let label = 'Stabile';
                let className = 'trend-indicator trend-flat';
                if (delta > threshold) {
                    label = 'In salita';
                    className = 'trend-indicator trend-up';
                } else if (delta < -threshold) {
                    label = 'In calo';
                    className = 'trend-indicator trend-down';
                }
                trendStatus.textContent = label;
                trendStatus.className = className;
            } else {
                trendStatus.textContent = '--';
                trendStatus.className = 'trend-indicator';
            }
        }
    }
    
    updateStatus(data) {
        const currentValue = document.getElementById('current-value');
        const statusIndicator = document.getElementById('status-indicator');
        const statusText = document.getElementById('status-text');
        
        if (currentValue && data.current_value !== undefined && data.current_value !== null) {
            currentValue.textContent = data.current_value.toFixed(2);
        }
        
        if (statusIndicator && statusText) {
            const threshold = this.getActiveThreshold();
            const source = this.getActiveThresholdData().source;
            const currentValue = Number.isFinite(data.current_value) ? data.current_value : null;
            const isAbove = currentValue !== null ? currentValue > threshold : false;
            let levelClass = 'status-level-green';
            let levelLabel = 'Basso';
            if (currentValue !== null) {
                if (currentValue >= 2) {
                    levelClass = 'status-level-red';
                    levelLabel = 'Critico';
                } else if (currentValue >= 1) {
                    levelClass = 'status-level-orange';
                    levelLabel = 'Alto';
                } else if (currentValue >= 0.5) {
                    levelClass = 'status-level-yellow';
                    levelLabel = 'Moderato';
                }
            }
            statusIndicator.className = `status-indicator ${levelClass}`;
            statusText.textContent = currentValue !== null
                ? `${levelLabel}${isAbove ? ' · Sopra soglia' : ''}`
                : '--';
            this.updateActiveThresholdDisplay(threshold, source);
            this.updateDebugThresholdLabel(data.current_value, threshold, source);
        }
    }

    updateAnalyzeUI() {
        const analyzeToggle = document.getElementById('dashboard-analyze-toggle');
        const analyzeHint = document.getElementById('dashboard-analyze-hint');
        const analyzeStatus = document.getElementById('dashboard-analyze-status');
        if (analyzeToggle) {
            analyzeToggle.classList.toggle('is-active', this.analyzeModeEnabled);
            analyzeToggle.setAttribute('aria-pressed', this.analyzeModeEnabled ? 'true' : 'false');
            analyzeToggle.textContent = this.analyzeModeEnabled ? 'Analizza: attivo' : 'Analizza';
        }
        if (analyzeHint) {
            analyzeHint.textContent = this.analyzeModeEnabled
                ? 'Trascina sul grafico per selezionare l’intervallo da analizzare.'
                : 'Suggerimento: premi Analizza e trascina sul grafico per selezionare un intervallo.';
        }
        if (analyzeStatus) {
            analyzeStatus.classList.toggle('is-active', this.analyzeModeEnabled);
            analyzeStatus.setAttribute('aria-hidden', this.analyzeModeEnabled ? 'false' : 'true');
        }
    }

    applyInteractionState(plotDiv) {
        if (!plotDiv) return;
        plotDiv.classList.toggle('is-analyze-active', this.analyzeModeEnabled);
        this.updateAnalyzeUI();
    }

    toggleAnalyzeMode() {
        this.analyzeModeEnabled = !this.analyzeModeEnabled;
        const plotDiv = document.getElementById('tremor-plot');
        this.applyInteractionState(plotDiv);
        if (this.analyzeModeEnabled) {
            this.highlightAnalyzeHintOnce();
        }
        if (plotDiv && window.Plotly && plotDiv.data) {
            Plotly.relayout(plotDiv, {
                dragmode: this.analyzeModeEnabled ? 'select' : 'pan'
            });
            if (!this.analyzeModeEnabled) {
                Plotly.restyle(plotDiv, { selectedpoints: [null] });
            }
        }
    }

    resetPlotView() {
        const plotDiv = document.getElementById('tremor-plot');
        this.analyzeModeEnabled = false;
        this.applyInteractionState(plotDiv);
        if (plotDiv && window.Plotly && plotDiv.data) {
            Plotly.relayout(plotDiv, {
                'xaxis.autorange': true,
                'yaxis.autorange': true,
                dragmode: 'pan'
            }).then(() => {
                Plotly.restyle(plotDiv, { selectedpoints: [null] });
            });
        }
    }

    highlightAnalyzeHintOnce() {
        const analyzeHint = document.getElementById('dashboard-analyze-hint');
        if (!analyzeHint) return;
        let alreadySeen = false;
        try {
            alreadySeen = localStorage.getItem(ANALYZE_HINT_KEY) === '1';
        } catch (error) {
            alreadySeen = false;
        }
        if (alreadySeen) return;
        analyzeHint.classList.add('is-highlighted');
        window.setTimeout(() => analyzeHint.classList.remove('is-highlighted'), 4000);
        try {
            localStorage.setItem(ANALYZE_HINT_KEY, '1');
        } catch (error) {
            // No-op if storage is unavailable.
        }
    }
    
    async forceUpdate() {
        const updateBtn = document.getElementById('update-btn');
        const originalText = updateBtn?.innerHTML;
        
        try {
            if (updateBtn) {
                updateBtn.disabled = true;
                updateBtn.innerHTML = '<span class="loading-spinner"></span> Aggiornamento...';
            }
            
            const response = await fetch('/api/force_update', { method: 'POST' });
            const result = await response.json();
            
            if (result.ok) {
                this.showToast(`Dati aggiornati! ${result.rows} punti elaborati.`, 'success');
                await this.loadData();
                await this.loadStatus();
            } else {
                this.showToast(`Aggiornamento fallito: ${result.error}`, 'error');
            }
        } catch (error) {
            this.showToast('Errore di rete durante aggiornamento', 'error');
        } finally {
            if (updateBtn) {
                updateBtn.disabled = false;
                updateBtn.innerHTML = originalText;
            }
        }
    }
    
    async saveThreshold() {
        const thresholdInput = document.getElementById('threshold-input');
        const threshold = parseFloat(thresholdInput?.value);
        
        if (!threshold || threshold < 0.1 || threshold > 10) {
            this.showToast('La soglia deve essere tra 0.1 e 10 mV', 'error');
            return;
        }
        
        try {
            const response = await fetch('/dashboard/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `threshold=${threshold}`
            });

            let payload = null;
            try {
                payload = await response.json();
            } catch (parseError) {
                payload = null;
            }

            if (response.ok) {
                this.showToast('Soglia salvata con successo', 'success');
                this.updateActiveThresholdDisplay(threshold, 'user/custom');
                if (this.plotData) {
                    this.renderPlot(this.plotData);
                }
            } else {
                const message = payload?.message || 'Errore nel salvare la soglia';
                this.showToast(message, 'error');
            }
        } catch (error) {
            this.showToast('Errore di rete', 'error');
        }
    }
    
    async exportData(format) {
        try {
            if (format === 'csv') {
                const limit = this.getSelectedLimit();
                const response = await fetch(`/api/curva?limit=${limit}`);
                const data = await response.json();
                
                if (data.ok && data.data) {
                    const csv = this.convertToCSV(data.data);
                    this.downloadFile(csv, 'etna-tremor-data.csv', 'text/csv');
                }
            } else if (format === 'png') {
                const plotDiv = document.getElementById('tremor-plot');
                if (plotDiv) {
                    Plotly.toImage(plotDiv, { format: 'png', width: 1200, height: 600 })
                        .then(dataUrl => {
                            const link = document.createElement('a');
                            link.download = 'etna-tremor-chart.png';
                            link.href = dataUrl;
                            link.click();
                        });
                }
            }
        } catch (error) {
            this.showToast('Esportazione fallita', 'error');
        }
    }
    
    convertToCSV(data) {
        const headers = ['timestamp', 'value'];
        const rows = data.map(row => [row.timestamp, row.value]);
        return [headers, ...rows].map(row => row.join(',')).join('\n');
    }
    
    downloadFile(content, filename, contentType) {
        const blob = new Blob([content], { type: contentType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        link.click();
        URL.revokeObjectURL(url);
    }
    
    showNoDataMessage() {
        const plotDiv = document.getElementById('tremor-plot');
        if (plotDiv) {
            plotDiv.innerHTML = `
                <div class="no-data-message" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 420px; text-align: center; color: var(--text-secondary);">
                    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" style="margin-bottom: 16px; opacity: 0.5;">
                        <path d="M3 3v18h18"/>
                        <path d="M7 12l3-3 3 3 5-5"/>
                    </svg>
                    <h3 style="margin: 0 0 8px 0; font-size: 18px;">Nessun dato disponibile</h3>
                    <p style="margin: 0 0 16px 0; opacity: 0.7;">I dati del tremore vulcanico verranno caricati automaticamente</p>
                    <button onclick="window.location.reload()" class="btn btn-primary" style="padding: 8px 16px; border: none; border-radius: 6px; background: #007aff; color: white; cursor: pointer;">
                        Aggiorna Ora
                    </button>
                </div>
            `;
        }
    }
    
    setupMissions() {
        const claimButtons = document.querySelectorAll('[data-mission-claim]');
        claimButtons.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.preventDefault();
                const missionId = btn.dataset.missionId;
                if (!missionId) return;
                
                // Disable button during request
                btn.disabled = true;
                btn.textContent = 'Riscatto...';
                
                try {
                    const csrfToken = this.getCSRFToken();
                    const response = await fetch(`/api/missions/${missionId}/claim`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ csrf_token: csrfToken })
                    });
                    
                    const result = await response.json();
                    
                    if (result.ok) {
                        this.showToast(`Missione riscattata! +${result.points_awarded} punti`, 'success');
                        // Reload page after brief delay
                        setTimeout(() => window.location.reload(), 1500);
                    } else {
                        const errorMessages = {
                            'mission_not_found': 'Missione non trovata',
                            'unauthorized': 'Non autorizzato',
                            'mission_not_completed': 'Missione non ancora completata',
                            'invalid_csrf': 'Sessione scaduta, ricarica la pagina'
                        };
                        const errorMsg = errorMessages[result.error] || 'Errore nel riscattare la missione';
                        this.showToast(errorMsg, 'error');
                        btn.disabled = false;
                        btn.textContent = 'Riscatta';
                    }
                } catch (error) {
                    console.error('Error claiming mission:', error);
                    this.showToast('Errore di connessione', 'error');
                    btn.disabled = false;
                    btn.textContent = 'Riscatta';
                }
            });
        });
    }
    
    getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.content;
        
        // Fallback: try to find in a hidden input
        const input = document.querySelector('input[name="csrf_token"]');
        if (input) return input.value;
        
        return '';
    }
    
    showToast(message, type = 'info', duration = 5000) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        const icon = type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ';
        toast.innerHTML = `
            <span class="toast-icon">${icon}</span>
            <span class="toast-message">${message}</span>
        `;
        
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'slideOutRight 300ms ease-in forwards';
            setTimeout(() => container.removeChild(toast), 300);
        }, duration);
    }
}

function toggleAlert(alertType, enabled) {
    fetch('/dashboard/alerts/toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: `alert_type=${alertType}&enabled=${enabled}`
    }).then(response => {
        if (response.ok) {
            window.location.reload();
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    new EtnaDashboard();
});
