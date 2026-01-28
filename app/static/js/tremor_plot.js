/* global document, window */
(function () {
  const desktopPlot = document.getElementById('tremor-plot');
  const desktopFallback = document.getElementById('tremorPlotFallback');
  const MOBILE_BREAKPOINT = 768;
  const MOBILE_TICK_FONT_SIZE = 12;
  const MOBILE_MARGIN = { l: 55, r: 15, t: 10, b: 45 };

  const parseFigPayload = (container) => {
    if (!container) {
      return null;
    }
    try {
      const raw = container.dataset.fig || '';
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  };

  const computePlotHeight = () => {
    const height = window.innerHeight * 0.72;
    return Math.round(Math.min(820, Math.max(520, height)));
  };

  const isMobileViewport = () => window.innerWidth <= MOBILE_BREAKPOINT;

  const buildMobileOverrides = () => ({
    height: computePlotHeight(),
    margin: MOBILE_MARGIN,
    'xaxis.tickfont.size': MOBILE_TICK_FONT_SIZE,
    'yaxis.tickfont.size': MOBILE_TICK_FONT_SIZE,
  });

  const buildDesktopOverrides = () => ({
    height: null,
  });

  const applyResponsiveLayout = (container) => {
    if (!container || !window.Plotly) {
      return;
    }
    const layoutUpdates = isMobileViewport() ? buildMobileOverrides() : buildDesktopOverrides();
    window.Plotly.relayout(container, layoutUpdates);
    window.requestAnimationFrame(() => {
      window.Plotly?.Plots?.resize(container);
    });
  };

  const renderPlot = (container, figPayload) => {
    if (!container || !figPayload || !window.Plotly) {
      return false;
    }
    const layout = { ...(figPayload.layout || {}) };
    const data = figPayload.data || [];
    window.Plotly.react(container, data, layout, { responsive: true, displayModeBar: false });
    applyResponsiveLayout(container);
    return true;
  };

  const setFallbackVisible = (fallback, visible) => {
    if (!fallback) {
      return;
    }
    fallback.hidden = !visible;
  };

  if (desktopPlot) {
    const figPayload = parseFigPayload(desktopPlot);
    if (!renderPlot(desktopPlot, figPayload)) {
      setFallbackVisible(desktopFallback, true);
    } else {
      setFallbackVisible(desktopFallback, false);
      const handleResize = () => applyResponsiveLayout(desktopPlot);
      window.addEventListener('resize', handleResize);
      window.addEventListener('orientationchange', handleResize);
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
          handleResize();
        }
      });
      window.requestAnimationFrame(handleResize);
    }
  }
})();
