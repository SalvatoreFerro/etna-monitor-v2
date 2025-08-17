/**
 * Home Preview Chart Module
 * Handles chart rendering and updates for the home page preview
 */

async function fetchCurva(limit = 168) {
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
      return data;
    } else {
      throw new Error('No data available');
    }
  } catch (error) {
    console.error('Error fetching curva for home preview:', error);
    throw error;
  }
}

function renderHomePreview(data) {
  if (!window.Plotly) {
    console.error('Plotly library not loaded');
    return;
  }
  
  const container = 'home-preview-plot';
  const timestamps = data.data.map(row => row.timestamp);
  const values = data.data.map(row => row.value);
  const threshold = 2.0; // Default threshold
  
  const trace = {
    x: timestamps,
    y: values,
    type: 'scatter',
    mode: 'lines',
    name: 'Tremor',
    line: { color: '#00AA00', width: 2 },
    showlegend: false
  };
  
  const layout = {
    margin: { l: 40, r: 10, t: 30, b: 40 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    xaxis: { 
      showgrid: false, 
      tickfont: { size: 10 },
      showticklabels: true
    },
    yaxis: { 
      type: 'log', 
      range: [-1, 2], // 0.1 to 100 range
      tickfont: { size: 10 },
      showgrid: true,
      gridcolor: 'rgba(255,255,255,0.1)'
    },
    font: { color: '#e6e7ea', size: 10 },
    shapes: [{
      type: 'line',
      x0: timestamps[0],
      x1: timestamps[timestamps.length - 1],
      y0: threshold,
      y1: threshold,
      line: { color: '#ef4444', width: 2, dash: 'dash' }
    }]
  };
  
  const config = { 
    displayModeBar: false, 
    responsive: true,
    staticPlot: false
  };
  
  return Plotly.newPlot(container, [trace], layout, config).then(() => {
    const loadingOverlay = document.querySelector('#home-preview-loading');
    if (loadingOverlay) {
      loadingOverlay.classList.add('hidden');
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
    const data = await fetchCurva(168); // Last 7 days at 1h intervals ≈ 168 points
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
        <p>No data available</p>
        <button onclick="quickUpdate()" class="btn btn-secondary btn-sm" style="margin-top: 12px;">
          Update Now
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
  requestAnimationFrame(() => {
    setTimeout(() => {
      refreshHomePreview().catch(error => {
        console.error('Failed to initialize home preview:', error);
      });
    }, 100);
  });
}

window.renderHomePreview = renderHomePreview;
window.refreshHomePreview = refreshHomePreview;
window.initializeHomePreview = initializeHomePreview;
