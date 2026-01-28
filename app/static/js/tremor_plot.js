/* global document, window */
(function () {
  const plotContainer = document.getElementById('tremorPlot');
  if (!plotContainer) {
    return;
  }

  const fallback = document.getElementById('tremorPlotFallback');
  let figPayload = null;

  try {
    const raw = plotContainer.dataset.fig || '';
    if (raw) {
      figPayload = JSON.parse(raw);
    }
  } catch (error) {
    figPayload = null;
  }

  if (!figPayload || !window.Plotly) {
    if (fallback) {
      fallback.hidden = false;
    }
    return;
  }

  if (fallback) {
    fallback.hidden = true;
  }

  const layout = { ...(figPayload.layout || {}) };
  const isMobile = window.innerWidth <= 480;
  if (isMobile && layout.meta && layout.meta.mobileOverrides) {
    const mobileOverrides = layout.meta.mobileOverrides;
    if (mobileOverrides.margin) {
      layout.margin = { ...(layout.margin || {}), ...mobileOverrides.margin };
    }
    if (mobileOverrides.height) {
      layout.height = mobileOverrides.height;
    }
    if (mobileOverrides.xaxis) {
      layout.xaxis = { ...(layout.xaxis || {}), ...mobileOverrides.xaxis };
    }
    if (mobileOverrides.yaxis && mobileOverrides.yaxis.range) {
      layout.yaxis = { ...(layout.yaxis || {}), range: mobileOverrides.yaxis.range };
      if (mobileOverrides.yaxis.tickfont) {
        layout.yaxis.tickfont = mobileOverrides.yaxis.tickfont;
      }
    } else if (mobileOverrides.yaxis) {
      layout.yaxis = { ...(layout.yaxis || {}), ...mobileOverrides.yaxis };
    }
  }

  window.Plotly.react(
    plotContainer,
    figPayload.data || [],
    layout,
    { responsive: true, displayModeBar: false }
  );
})();
