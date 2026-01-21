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

  window.Plotly.react(
    plotContainer,
    figPayload.data || [],
    figPayload.layout || {},
    { responsive: true, displayModeBar: false }
  );
})();
