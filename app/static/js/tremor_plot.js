/* global document, window */
(function () {
  const desktopPlot = document.getElementById('tremor-plot');
  const desktopFallback = document.getElementById('tremorPlotFallback');
  const modal = document.getElementById('tremorPlotModal');
  const modalPlot = document.getElementById('tremor-plot-modal');
  const modalFallback = document.getElementById('tremorModalFallback');
  const modalTrigger = document.getElementById('tremor-open-modal');
  const imageModalTrigger = document.querySelector('[data-image-modal-target]');
  const imageModal = document.getElementById('tremorImageModal');
  const imageModalImg = document.getElementById('tremorImageModalImg');
  const imageModalLink = document.getElementById('tremorImageModalLink');

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

  const computeModalHeight = () => {
    const height = window.innerHeight * 0.85;
    return Math.round(Math.min(900, Math.max(420, height)));
  };

  const renderPlot = (container, figPayload, heightOverride) => {
    if (!container || !figPayload || !window.Plotly) {
      return false;
    }
    const layout = { ...(figPayload.layout || {}) };
    if (heightOverride) {
      layout.height = heightOverride;
    }
    const data = figPayload.data || [];
    window.Plotly.react(container, data, layout, { responsive: true, displayModeBar: false });
    return true;
  };

  const setFallbackVisible = (fallback, visible) => {
    if (!fallback) {
      return;
    }
    fallback.hidden = !visible;
  };

  const isMobileViewport = () => window.innerWidth <= 768;

  if (desktopPlot && !isMobileViewport()) {
    const figPayload = parseFigPayload(desktopPlot);
    if (!renderPlot(desktopPlot, figPayload)) {
      setFallbackVisible(desktopFallback, true);
    } else {
      setFallbackVisible(desktopFallback, false);
      window.addEventListener('resize', () => window.Plotly?.Plots?.resize(desktopPlot));
    }
  }

  let modalRendered = false;
  const openModal = () => {
    if (!modal || !modalPlot) {
      return;
    }
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('tremor-modal-open');
    const figPayload = parseFigPayload(modalPlot);
    if (!modalRendered) {
      const rendered = renderPlot(modalPlot, figPayload, computeModalHeight());
      modalRendered = rendered;
      setFallbackVisible(modalFallback, !rendered);
    } else if (window.Plotly?.Plots?.resize) {
      window.Plotly.relayout(modalPlot, { height: computeModalHeight() });
      window.Plotly.Plots.resize(modalPlot);
    }
    window.setTimeout(() => {
      if (window.Plotly?.Plots?.resize) {
        window.Plotly.relayout(modalPlot, { height: computeModalHeight() });
        window.Plotly.Plots.resize(modalPlot);
      }
    }, 150);
  };

  const closeModal = () => {
    if (!modal) {
      return;
    }
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('tremor-modal-open');
  };

  const closeImageModal = () => {
    if (!imageModal) {
      return;
    }
    imageModal.hidden = true;
    imageModal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('tremor-modal-open');
  };

  if (modalTrigger) {
    modalTrigger.addEventListener('click', openModal);
  }

  if (modal) {
    modal.addEventListener('click', (event) => {
      if (event.target.closest('[data-modal-close]')) {
        closeModal();
      }
    });
  }

  if (imageModalTrigger && imageModal) {
    imageModalTrigger.addEventListener('click', () => {
      const src = imageModalTrigger.dataset.imageSrc;
      if (imageModalImg && src) {
        imageModalImg.src = src;
      }
      if (imageModalLink && src) {
        imageModalLink.href = src;
      }
      imageModal.hidden = false;
      imageModal.setAttribute('aria-hidden', 'false');
      document.body.classList.add('tremor-modal-open');
    });
    imageModal.addEventListener('click', (event) => {
      if (event.target.closest('[data-modal-close]')) {
        closeImageModal();
      }
    });
  }

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeModal();
      closeImageModal();
    }
  });

  window.addEventListener('resize', () => {
    if (!modal || modal.hidden || !modalPlot || !window.Plotly?.Plots?.resize) {
      return;
    }
    window.Plotly.relayout(modalPlot, { height: computeModalHeight() });
    window.Plotly.Plots.resize(modalPlot);
  });
})();
