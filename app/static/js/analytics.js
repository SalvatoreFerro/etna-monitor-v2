(() => {
  const TRACK_ENDPOINT = '/api/status';

  const sendFallback = (eventName, params = {}) => {
    try {
      const url = new URL(TRACK_ENDPOINT, window.location.origin);
      url.searchParams.set('track', eventName);
      if (params.location) {
        url.searchParams.set('location', params.location);
      }
      fetch(url.toString(), {
        method: 'GET',
        keepalive: true,
        headers: {
          'X-Tracking-Event': '1'
        }
      }).catch(() => {});
    } catch (error) {
      // Swallow tracking errors.
    }
  };

  const trackEvent = (eventName, params = {}) => {
    if (!eventName) {
      return;
    }
    if (typeof window.gtag === 'function') {
      window.gtag('event', eventName, params);
      return;
    }
    sendFallback(eventName, params);
  };

  const trackClicks = () => {
    document.querySelectorAll('[data-track-event]').forEach((element) => {
      if (element.dataset.trackBound === 'true') {
        return;
      }
      element.dataset.trackBound = 'true';
      element.addEventListener('click', () => {
        trackEvent(element.dataset.trackEvent, {
          location: element.dataset.trackLocation || undefined
        });
      });
    });
  };

  const trackViews = () => {
    const viewElements = document.querySelectorAll('[data-track-view]');
    if (!viewElements.length) {
      return;
    }

    if (!('IntersectionObserver' in window)) {
      viewElements.forEach((element) => {
        trackEvent(element.dataset.trackView, {
          location: element.dataset.trackLocation || undefined
        });
      });
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) {
          return;
        }
        const element = entry.target;
        trackEvent(element.dataset.trackView, {
          location: element.dataset.trackLocation || undefined
        });
        observer.unobserve(element);
      });
    }, { threshold: 0.4 });

    viewElements.forEach((element) => observer.observe(element));
  };

  document.addEventListener('DOMContentLoaded', () => {
    trackClicks();
    trackViews();
  });

  window.etnaTrackEvent = trackEvent;
})();
