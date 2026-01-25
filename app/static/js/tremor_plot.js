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
    if (mobileOverrides.yaxis && mobileOverrides.yaxis.range) {
      layout.yaxis = { ...(layout.yaxis || {}), range: mobileOverrides.yaxis.range };
    }
  }

  window.Plotly.react(
    plotContainer,
    figPayload.data || [],
    layout,
    { responsive: true, displayModeBar: false }
  );
})();
