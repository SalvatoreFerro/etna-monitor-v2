/* global document, window */
(function () {
  const plotContainer = document.getElementById('tremor-plot');
  if (!plotContainer) {
    return;
  }

  const plotWrapper = document.querySelector('.tremor-plot-wrap');
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
  let mobileOverrides = null;
  if (isMobile && layout.meta && layout.meta.mobileOverrides) {
    mobileOverrides = layout.meta.mobileOverrides;
    if (mobileOverrides.margin) {
      layout.margin = { ...(layout.margin || {}), ...mobileOverrides.margin };
    }
    if (mobileOverrides.xaxis) {
      layout.xaxis = { ...(layout.xaxis || {}), ...mobileOverrides.xaxis };
    }
    if (mobileOverrides.yaxis) {
      layout.yaxis = { ...(layout.yaxis || {}), ...mobileOverrides.yaxis };
    }
  }

  const data = (figPayload.data || []).map((trace) => {
    if (!isMobile || !mobileOverrides || !mobileOverrides.lineWidth) {
      return trace;
    }
    return {
      ...trace,
      line: { ...(trace.line || {}), width: mobileOverrides.lineWidth },
    };
  });

  const relayoutToContainerHeight = () => {
    if (!plotWrapper || !window.Plotly || !plotContainer.data) {
      return;
    }
    const height = Math.round(plotWrapper.getBoundingClientRect().height || 0);
    if (!height) {
      return;
    }
    window.Plotly.relayout(plotContainer, { height });
  };

  let resizeTimer = null;
  const scheduleResize = () => {
    if (!isMobile) {
      return;
    }
    if (resizeTimer) {
      return;
    }
    resizeTimer = window.setTimeout(() => {
      resizeTimer = null;
      relayoutToContainerHeight();
    }, 100);
  };

  const triggerDeferredResize = () => {
    scheduleResize();
    window.setTimeout(scheduleResize, 150);
  };

  Promise.resolve(
    window.Plotly.react(
      plotContainer,
      data,
      layout,
      { responsive: true, displayModeBar: false }
    )
  ).then(() => {
    if (isMobile) {
      triggerDeferredResize();
    }
  });

  document.addEventListener('DOMContentLoaded', triggerDeferredResize);
  window.addEventListener('resize', scheduleResize);
  window.addEventListener('orientationchange', triggerDeferredResize);
})();
