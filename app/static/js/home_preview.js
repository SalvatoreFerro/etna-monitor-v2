/**
 * Home Preview Chart Module
 * Handles chart rendering and updates for the home page preview
 */

let chartRetryCount = 0;
const chartMaxRetries = 3;

async function fetchCurva(limit = 2016) {
  try {
    const url = limit ? `/api/curva?limit=${limit}` : '/api/curva';
    const response = await fetch(url, {
      cache: 'no-store',
      headers: {
        'Cache-Control': 'no-cache'
      }
    });
    const data = await response.json();
    
    if (data.ok && data.data && data.data.length > 0) {
      console.log(`Home preview curva loaded: ${data.rows || data.data.length}, last_ts: ${data.last_ts}`);
      chartRetryCount = 0;
      return data;
    } else {
      throw new Error('Nessun dato disponibile');
    }
  } catch (error) {
    console.error('Error fetching curva for home preview:', error);
    if (chartRetryCount < chartMaxRetries) {
      chartRetryCount++;
      throw new Error('Caricamento dati da INGV, attendere...');
    } else {
      throw new Error('Errore di connessione persistente ai dati INGV');
    }
  }
}

function renderHomePreview(data) {
  if (!window.Plotly) {
    console.error('Plotly library not loaded');
    return;
  }
  
  const container = 'home-preview-plot';
  const timestamps = data.data.map(row => row.timestamp);
  const rawValues = data.data.map(row => row.value);
  const smoothWindow = 9;
  const smoothValues = rawValues.map((_, idx) => {
    const start = Math.max(0, idx - Math.floor(smoothWindow / 2));
    const end = Math.min(rawValues.length, idx + Math.ceil(smoothWindow / 2));
    const slice = rawValues.slice(start, end).filter(value => value > 0);
    if (!slice.length) return rawValues[idx];
    const sorted = slice.slice().sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length / 2)];
  });
  const threshold = 2.0; // Default threshold
  
  const rawTrace = {
    x: timestamps,
    y: rawValues,
    type: 'scatter',
    mode: 'lines',
    name: 'RAW (picchi reali)',
    line: { color: '#4ade80', width: 2 },
    showlegend: true
  };

  const smoothTrace = {
    x: timestamps,
    y: smoothValues,
    type: 'scatter',
    mode: 'lines',
    name: 'Trend (smoothed)',
    line: { color: '#22d3ee', width: 2 },
    opacity: 0.8,
    showlegend: true
  };

  const positiveValues = rawValues.filter(value => value > 0);
  const minVal = positiveValues.length ? Math.min(...positiveValues) : 0.1;
  const maxVal = positiveValues.length ? Math.max(...positiveValues) : 10;
  let logMin = isFinite(minVal) ? Math.floor(Math.log10(minVal)) : -1;
  let logMax = isFinite(maxVal) ? Math.ceil(Math.log10(maxVal)) : 1;
  if (logMin === logMax) {
    logMax += 1;
  }
  
  const layoutBase = {
    paper_bgcolor: '#151821',
    plot_bgcolor: '#151821',
    shapes: [{
      type: 'line',
      x0: timestamps[0],
      x1: timestamps[timestamps.length - 1],
      y0: threshold,
      y1: threshold,
      line: { color: '#ef4444', width: 2, dash: 'dash' }
    }]
  };

  const layout_desktop = {
    ...layoutBase,
    margin: { l: 60, r: 20, t: 20, b: 50 },
    xaxis: { 
      title: 'Data/Ora',
      showgrid: true, 
      gridcolor: 'rgba(255,255,255,0.1)',
      tickfont: { size: 11, color: '#e6e7ea' },
      titlefont: { size: 12, color: '#e6e7ea' },
      showticklabels: true,
      color: '#e6e7ea'
    },
    yaxis: { 
      title: 'mV',
      type: 'log', 
      range: [logMin, logMax],
      tickvals: [0.1, 1, 10],
      ticktext: ['10⁻¹', '10⁰', '10¹'],
      tickfont: { size: 11, color: '#e6e7ea' },
      titlefont: { size: 12, color: '#e6e7ea' },
      showgrid: true,
      gridcolor: 'rgba(255,255,255,0.1)',
      color: '#e6e7ea'
    },
    font: { color: '#e6e7ea', size: 12 },
    hoverlabel: { font: { size: 12 } },
    legend: { orientation: 'h', y: 1.05, x: 1, xanchor: 'right' }
  };

  const layout_mobile = {
    ...layoutBase,
    height: 460,
    autosize: true,
    margin: { l: 48, r: 14, t: 10, b: 32 },
    xaxis: { 
      title: 'Data/Ora',
      showgrid: true, 
      gridcolor: 'rgba(255,255,255,0.1)',
      tickfont: { size: 9, color: '#e6e7ea' },
      titlefont: { size: 10, color: '#e6e7ea' },
      showticklabels: true,
      color: '#e6e7ea'
    },
    yaxis: { 
      title: 'mV',
      type: 'log', 
      range: [logMin, logMax],
      tickvals: [0.1, 10],
      ticktext: ['10⁻¹', '10¹'],
      tickfont: { size: 9, color: '#e6e7ea' },
      titlefont: { size: 10, color: '#e6e7ea' },
      showgrid: true,
      gridcolor: 'rgba(255,255,255,0.1)',
      color: '#e6e7ea'
    },
    font: { color: '#e6e7ea', size: 10 },
    hoverlabel: { font: { size: 10 } },
    legend: { orientation: 'h', y: 1.05, x: 1, xanchor: 'right' }
  };

  const isMobile = window.matchMedia('(max-width: 768px)').matches;
  const layout = isMobile ? layout_mobile : layout_desktop;
  
  const config = { 
    displayModeBar: false, 
    responsive: true,
    staticPlot: false
  };
  
  return Plotly.newPlot(container, [rawTrace, smoothTrace], layout, config).then(() => {
    const loadingOverlay = document.getElementById('home-preview-loading');
    const plotContainer = document.getElementById(container);
    
    if (loadingOverlay) {
      loadingOverlay.style.display = 'none';
      loadingOverlay.classList.add('hidden');
    }
    
    if (plotContainer) {
      plotContainer.style.display = 'block';
      plotContainer.classList.add('loaded');
    }
    
    if (data.data && data.data.length > 0) {
      const currentValue = data.data[data.data.length - 1].value;
      if (window.updateActivityBadge) {
        window.updateActivityBadge(currentValue);
      }
    }
    
    window.addEventListener('resize', () => {
      if (document.getElementById(container)) {
        Plotly.Plots.resize(container);
      }
    });
  }).catch(error => {
    console.error('Error rendering home preview chart:', error);
    showNoDataMessage();
  });
}

async function refreshHomePreview() {
  try {
    const data = await fetchCurva(2016);
    await renderHomePreview(data);
    return data;
  } catch (error) {
    console.error('Error refreshing home preview:', error);
    showNoDataMessage();
    throw error;
  }
}

function showNoDataMessage() {
  const container = document.getElementById('home-preview-plot');
  if (container) {
    container.innerHTML = `
      <div class="chart-placeholder">
        <svg width="60" height="60" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M3 3v18h18"/>
          <path d="M7 12l3-3 3 3 5-5"/>
        </svg>
        <p>Nessun dato sismico disponibile</p>
        <button onclick="quickUpdate()" class="btn btn-secondary btn-sm" style="margin-top: 12px;">
          Aggiorna Ora
        </button>
      </div>
    `;
  }
  
  const loadingOverlay = document.querySelector('#home-preview-loading');
  if (loadingOverlay) {
    loadingOverlay.classList.add('hidden');
  }
}

function initializeHomePreview() {
  const loadingOverlay = document.getElementById('home-preview-loading');
  if (loadingOverlay) {
    loadingOverlay.style.display = 'flex';
    loadingOverlay.classList.remove('hidden');
  }
  
  requestAnimationFrame(() => {
    setTimeout(() => {
      refreshHomePreview().catch(error => {
        console.error('Failed to initialize home preview:', error);
        showNoDataMessage();
      });
    }, 50);
  });
}

window.renderHomePreview = renderHomePreview;
window.refreshHomePreview = refreshHomePreview;
window.initializeHomePreview = initializeHomePreview;
