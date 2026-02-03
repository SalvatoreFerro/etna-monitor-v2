/* global document, window */
(function () {
  const desktopPlot = document.getElementById('tremor-plot');
  const desktopFallback = document.getElementById('tremorPlotFallback');
  const MOBILE_BREAKPOINT = 768;
  const MOBILE_TICK_FONT_SIZE = 11;
  const MOBILE_MARGIN = { l: 44, r: 12, t: 8, b: 42 };
  const MOBILE_Y_AXIS_STANDOFF = 4;
  const MOBILE_MARKER_LABEL = 'ORA';
  const MOBILE_MARKER_COLOR = '#22d3ee';
  const MOBILE_MARKER_SIZE = 10;

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

  const computePlotHeight = (container) => {
    const containerHeight = container?.getBoundingClientRect?.().height;
    if (containerHeight && Number.isFinite(containerHeight)) {
      return Math.round(containerHeight);
    }
    const height = window.innerHeight * 0.66;
    return Math.round(Math.min(520, Math.max(320, height)));
  };

  const isMobileViewport = () => window.innerWidth <= MOBILE_BREAKPOINT;

  const extractMobileOverrides = (layout) => {
    const metaOverrides = layout?.meta?.mobileOverrides || {};
    const metaMargin = metaOverrides.margin || {};
    return {
      margin: {
        l: Math.min(metaMargin.l ?? MOBILE_MARGIN.l, MOBILE_MARGIN.l),
        r: Math.min(metaMargin.r ?? MOBILE_MARGIN.r, MOBILE_MARGIN.r),
        t: Math.min(metaMargin.t ?? MOBILE_MARGIN.t, MOBILE_MARGIN.t),
        b: Math.min(metaMargin.b ?? MOBILE_MARGIN.b, MOBILE_MARGIN.b),
      },
      xaxis: metaOverrides.xaxis || {},
      yaxis: metaOverrides.yaxis || {},
      lineWidth: metaOverrides.lineWidth,
    };
  };

  const getYTitleText = (layout) => {
    const title = layout?.yaxis?.title;
    if (!title) {
      return '';
    }
    if (typeof title === 'string') {
      return title;
    }
    return title.text || '';
  };

  const buildMobileOverrides = (layout, container) => {
    const mobileOverrides = extractMobileOverrides(layout);
    return {
      height: computePlotHeight(container),
      margin: mobileOverrides.margin,
      'xaxis.tickfont.size': mobileOverrides.xaxis?.tickfont?.size || MOBILE_TICK_FONT_SIZE,
      'xaxis.nticks': mobileOverrides.xaxis?.nticks,
      'yaxis.tickfont.size': mobileOverrides.yaxis?.tickfont?.size || MOBILE_TICK_FONT_SIZE,
      'yaxis.nticks': mobileOverrides.yaxis?.nticks,
      'yaxis.title.text': '',
      'yaxis.title.standoff': MOBILE_Y_AXIS_STANDOFF,
    };
  };

  const buildDesktopOverrides = (layout) => ({
    height: null,
    margin: layout?.margin || null,
    'yaxis.title.text': getYTitleText(layout),
    'yaxis.title.standoff': layout?.yaxis?.title?.standoff,
    'yaxis.nticks': layout?.yaxis?.nticks,
    'xaxis.nticks': layout?.xaxis?.nticks,
  });

  const adjustShapeOpacity = (shapes, opacityMultiplier) =>
    (shapes || []).map((shape) => {
      const fill = shape.fillcolor;
      if (!fill || typeof fill !== 'string' || !fill.startsWith('rgba')) {
        return shape;
      }
      const match = fill.match(/rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/);
      if (!match) {
        return shape;
      }
      const nextOpacity = Math.max(0, Math.min(1, parseFloat(match[4]) * opacityMultiplier));
      return {
        ...shape,
        fillcolor: `rgba(${match[1]}, ${match[2]}, ${match[3]}, ${nextOpacity})`,
      };
    });

  const adjustRgbaOpacity = (color, opacityMultiplier) => {
    if (!color || typeof color !== 'string' || !color.startsWith('rgba')) {
      return color;
    }
    const match = color.match(/rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/);
    if (!match) {
      return color;
    }
    const nextOpacity = Math.max(0, Math.min(1, parseFloat(match[4]) * opacityMultiplier));
    return `rgba(${match[1]}, ${match[2]}, ${match[3]}, ${nextOpacity})`;
  };

  const applyResponsiveLayout = (
    container,
    { baseLayout, baseShapes, baseLineWidth, baseYTitleText, baseYTitleStandoff, baseTrace } = {},
  ) => {
    if (!container || !window.Plotly) {
      return;
    }
    const isMobile = isMobileViewport();
    const layoutUpdates = isMobile
      ? buildMobileOverrides(baseLayout, container)
      : buildDesktopOverrides(baseLayout);
    if (!isMobile && baseYTitleText !== undefined) {
      layoutUpdates['yaxis.title.text'] = baseYTitleText;
      layoutUpdates['yaxis.title.standoff'] = baseYTitleStandoff;
    }
    if (isMobile && baseShapes?.length) {
      layoutUpdates.shapes = adjustShapeOpacity(baseShapes, 0.55);
    }
    if (!isMobile && baseShapes?.length) {
      layoutUpdates.shapes = baseShapes;
    }
    window.Plotly.relayout(container, layoutUpdates);
    window.requestAnimationFrame(() => {
      window.Plotly?.Plots?.resize(container);
    });
    if (baseLineWidth || baseTrace) {
      const targetWidth = baseLineWidth
        ? (isMobile ? Math.max(0.8, Math.round(baseLineWidth * 0.75 * 10) / 10) : baseLineWidth)
        : undefined;
      const traceUpdates = {};
      if (targetWidth) {
        traceUpdates['line.width'] = targetWidth;
      }
      if (isMobile) {
        traceUpdates.mode = 'lines';
        if (baseTrace?.fill) {
          traceUpdates.fill = 'none';
        }
        if (baseTrace?.fillcolor) {
          traceUpdates.fillcolor = adjustRgbaOpacity(baseTrace.fillcolor, 0.45);
        }
        if (baseTrace?.opacity !== undefined) {
          traceUpdates.opacity = Math.min(0.75, baseTrace.opacity);
        }
      } else if (baseTrace) {
        if (baseTrace.mode) {
          traceUpdates.mode = baseTrace.mode;
        }
        if (baseTrace.fill !== undefined) {
          traceUpdates.fill = baseTrace.fill;
        }
        if (baseTrace.fillcolor) {
          traceUpdates.fillcolor = baseTrace.fillcolor;
        }
        if (baseTrace.opacity !== undefined) {
          traceUpdates.opacity = baseTrace.opacity;
        }
      }
      if (Object.keys(traceUpdates).length) {
        window.Plotly.restyle(container, traceUpdates, [0]);
      }
    }
  };

  let mobileMarkerTraceIndex = null;

  const updateMobileMarker = (container, data) => {
    if (!container || !window.Plotly || !data?.length) {
      return;
    }
    const primaryTrace = data[0];
    const lastX = primaryTrace?.x?.[primaryTrace.x.length - 1];
    const lastY = primaryTrace?.y?.[primaryTrace.y.length - 1];
    if (!lastX || lastY === undefined || lastY === null) {
      return;
    }
    if (!isMobileViewport()) {
      if (mobileMarkerTraceIndex !== null) {
        window.Plotly.deleteTraces(container, mobileMarkerTraceIndex);
        mobileMarkerTraceIndex = null;
      }
      return;
    }
    if (mobileMarkerTraceIndex !== null) {
      return;
    }
    const markerTrace = {
      x: [lastX],
      y: [lastY],
      mode: 'markers+text',
      text: [MOBILE_MARKER_LABEL],
      textposition: 'top center',
      textfont: {
        size: 10,
        color: '#e2e8f0',
      },
      marker: {
        size: MOBILE_MARKER_SIZE,
        color: MOBILE_MARKER_COLOR,
        line: { width: 1, color: '#0f172a' },
      },
      hoverinfo: 'skip',
      showlegend: false,
      cliponaxis: false,
    };
    window.Plotly.addTraces(container, markerTrace).then((traceIndexes) => {
      mobileMarkerTraceIndex = Array.isArray(traceIndexes) ? traceIndexes[0] : traceIndexes;
    });
  };

  const renderPlot = (container, figPayload) => {
    if (!container || !figPayload || !window.Plotly) {
      return false;
    }
    const layout = { ...(figPayload.layout || {}) };
    const data = figPayload.data || [];
    const baseShapes = layout.shapes ? JSON.parse(JSON.stringify(layout.shapes)) : null;
    const baseLineWidth = data[0]?.line?.width;
    const baseTrace = data[0] ? { ...data[0] } : null;
    const baseYTitleText = getYTitleText(layout);
    const baseYTitleStandoff = layout?.yaxis?.title?.standoff;
    mobileMarkerTraceIndex = null;
    window.Plotly.react(container, data, layout, { responsive: true, displayModeBar: false });
    applyResponsiveLayout(container, {
      baseLayout: layout,
      baseShapes,
      baseLineWidth,
      baseYTitleText,
      baseYTitleStandoff,
      baseTrace,
    });
    updateMobileMarker(container, data);
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
      const handleResize = () => {
        const baseLayout = desktopPlot.layout || figPayload.layout || {};
        const baseShapes = baseLayout.shapes || figPayload.layout?.shapes || null;
        const baseLineWidth = desktopPlot.data?.[0]?.line?.width || figPayload.data?.[0]?.line?.width;
        const baseTrace = desktopPlot.data?.[0] || figPayload.data?.[0] || null;
        const baseYTitleText = getYTitleText(baseLayout || figPayload.layout || {});
        const baseYTitleStandoff = baseLayout?.yaxis?.title?.standoff || figPayload.layout?.yaxis?.title?.standoff;
        applyResponsiveLayout(desktopPlot, {
          baseLayout,
          baseShapes,
          baseLineWidth,
          baseYTitleText,
          baseYTitleStandoff,
          baseTrace,
        });
        updateMobileMarker(desktopPlot, desktopPlot.data || figPayload.data || []);
      };
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
