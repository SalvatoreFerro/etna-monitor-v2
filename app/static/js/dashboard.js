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
        line: '#38bdf8',
        fill: 'rgba(56, 189, 248, 0.18)',
        grid: 'rgba(148, 163, 184, 0.2)',
        axis: '#94a3b8',
        threshold: '#f87171',
        hoverBg: 'rgba(15, 23, 42, 0.92)'
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

class EtnaDashboard {
    constructor() {
        this.ingvMode = localStorage.getItem('ingv-mode') === 'true';
        this.autoRefreshInterval = null;
        this.refreshCountdown = null;
        this.plotData = null;
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
        this.setupThemeToggle();
        this.setupINGVMode();
        this.setupAutoRefresh();
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
            });
            
            thresholdInput.addEventListener('input', (e) => {
                thresholdSlider.value = e.target.value;
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

    setupThemeToggle() {
        const themeToggle = document.getElementById('theme-toggle');
        const currentTheme = localStorage.getItem('theme') || 'dark';
        document.documentElement.setAttribute('data-theme', currentTheme);

        if (themeToggle) {
            themeToggle.addEventListener('click', () => {
                const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
                document.documentElement.setAttribute('data-theme', newTheme);
                localStorage.setItem('theme', newTheme);
                
                if (this.plotData) {
                    this.renderPlot(this.plotData);
                }
            });
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

        const thresholdSlider = document.getElementById('threshold-slider');
        let threshold = parseFloat(thresholdSlider?.value || 2.0);
        if (!Number.isFinite(threshold)) {
            threshold = 2.0;
        }

        const hasExistingPlot = Boolean(plotDiv.data && plotDiv.data.length);
        const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
        const themeColors = this.getThemeColors(isDark);

        if (this.ingvMode) {
            const layout = {
                title: 'ECBD - RMS (UTC Time)',
                title_font: { size: 14, color: 'black' },
                xaxis: {
                    title: '',
                    showgrid: true,
                    gridwidth: 1,
                    gridcolor: 'lightgray',
                    tickangle: -90,
                    tickformat: '%d/%m\n%H:%M'
                },
                yaxis: {
                    title: 'Amplitude (mV)',
                    type: 'log',
                    range: [Math.log10(LOG_SCALE_MIN), Math.log10(LOG_SCALE_MAX)],
                    showgrid: true,
                    gridwidth: 1,
                    gridcolor: 'lightgray',
                    tickvals: LOG_TICKS.map((tick) => tick.value),
                    ticktext: LOG_TICKS.map((tick) => tick.label)
                },
                template: 'plotly_white',
                plot_bgcolor: 'white',
                paper_bgcolor: 'white',
                font: { family: 'Arial', size: 10, color: 'black' },
                margin: { l: 60, r: 20, t: 40, b: 40 },
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
                    width: 1.6
                },
                hovertemplate: '<b>%{y:.2f} mV</b><br>%{x|%d/%m %H:%M}<extra></extra>',
                showlegend: false
            };

            const config = {
                displayModeBar: false,
                responsive: true,
                staticPlot: false
            };

            if (hasExistingPlot) {
                Plotly.react(plotDiv, [trace], layout, config);
            } else {
                Plotly.newPlot(plotDiv, [trace], layout, config);
            }
            return;
        }
        const { line: lineColor, fill: fillColor, grid: gridColor, axis: axisLineColor, threshold: thresholdColor, hoverBg } = themeColors;

        const minExponent = Math.log10(Math.min(...clampedValues));
        const maxExponent = Math.log10(Math.max(...clampedValues));
        const yRange = [
            Math.min(Math.log10(LOG_SCALE_MIN), Math.floor(minExponent * 10) / 10),
            Math.max(Math.log10(LOG_SCALE_MAX), Math.ceil(maxExponent * 10) / 10)
        ];

        const shapes = threshold > 0 ? [{
            type: 'line',
            x0: timestamps[0],
            x1: timestamps[timestamps.length - 1],
            y0: threshold,
            y1: threshold,
            line: { color: thresholdColor, width: 2, dash: 'dash' }
        }] : [];

        const trace = {
            x: timestamps,
            y: clampedValues,
            type: 'scatter',
            mode: 'lines',
            name: 'Segnale Tremore',
            line: { color: lineColor, width: 2.4, shape: 'spline', smoothing: 1.15 },
            fill: 'tozeroy',
            fillcolor: fillColor,
            hovertemplate: '<b>%{y:.2f} mV</b><br>%{x|%d/%m %H:%M}<extra></extra>',
            showlegend: false
        };

        const layout = {
            margin: { l: 64, r: 32, t: 48, b: 56 },
            hovermode: 'x unified',
            plot_bgcolor: 'rgba(0,0,0,0)',
            paper_bgcolor: 'rgba(0,0,0,0)',
            font: { color: isDark ? '#e2e8f0' : '#0f172a' },
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
                bgcolor: hoverBg,
                bordercolor: thresholdColor,
                font: { color: isDark ? '#f8fafc' : '#0f172a' }
            }
        };

        const config = {
            displayModeBar: false,
            displaylogo: false,
            responsive: true,
            staticPlot: false,
            modeBarButtonsToRemove: ['select2d', 'lasso2d']
        };

        if (hasExistingPlot) {
            Plotly.react(plotDiv, [trace], layout, config);
        } else {
            Plotly.newPlot(plotDiv, [trace], layout, config);
        }

        plotDiv.classList.add('loaded');
    }
    
    updateStats(data) {
        const lastUpdated = document.getElementById('last-updated');
        const dataPoints = document.getElementById('data-points');
        
        if (lastUpdated && data.last_ts) {
            lastUpdated.textContent = `Ultimo aggiornamento: ${new Date(data.last_ts).toLocaleString()}`;
        }
        
        if (dataPoints) {
            dataPoints.textContent = `${data.data.length} punti`;
        }
    }
    
    updateStatus(data) {
        const currentValue = document.getElementById('current-value');
        const statusIndicator = document.getElementById('status-indicator');
        const statusText = document.getElementById('status-text');
        
        if (currentValue && data.current_value !== undefined) {
            currentValue.textContent = data.current_value.toFixed(2);
        }
        
        if (statusIndicator && statusText) {
            const isAbove = data.above_threshold;
            statusIndicator.className = `status-indicator ${isAbove ? 'status-above' : 'status-below'}`;
            statusText.textContent = isAbove ? 'Sopra Soglia' : 'Sotto Soglia';
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
            
            if (response.ok) {
                this.showToast('Soglia salvata con successo', 'success');
                if (this.plotData) {
                    this.renderPlot(this.plotData);
                }
            } else {
                this.showToast('Errore nel salvare la soglia', 'error');
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
