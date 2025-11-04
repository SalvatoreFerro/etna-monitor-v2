/* global window, document */
(function () {
  const STORAGE_KEY = 'em_onboarding_seen_v2';
  const SESSION_KEY = 'em_onboarding_session_lock';

  function initOnboarding() {
    const overlay = document.querySelector('[data-onboarding]');
    if (!overlay) {
      return;
    }

    const steps = Array.from(overlay.querySelectorAll('[data-onboarding-step]'));
    const nextButton = overlay.querySelector('[data-onboarding-next]');
    const skipButton = overlay.querySelector('[data-onboarding-skip]');
    const closeButton = overlay.querySelector('[data-onboarding-close]');
    const progressLabel = overlay.querySelector('[data-onboarding-progress]');
    const triggers = document.querySelectorAll('[data-onboarding-trigger]');

    if (!steps.length || !nextButton || !skipButton || !progressLabel) {
      return;
    }

    let currentIndex = 0;

    function updateStep(newIndex) {
      currentIndex = Math.min(Math.max(newIndex, 0), steps.length - 1);
      steps.forEach((step) => {
        const index = Number(step.getAttribute('data-step-index'));
        step.hidden = index !== currentIndex;
      });
      progressLabel.textContent = String(currentIndex + 1);
      if (currentIndex === steps.length - 1) {
        nextButton.textContent = 'Fine';
      } else {
        nextButton.textContent = 'Avanti';
      }
    }

    function openOverlay(manual = false) {
      overlay.hidden = false;
      overlay.classList.add('is-visible');
      document.body.classList.add('onboarding-open');
      updateStep(0);
      if (manual) {
        sessionStorage.setItem(SESSION_KEY, 'manual');
      }
    }

    function closeOverlay(markSeen = true) {
      overlay.classList.remove('is-visible');
      document.body.classList.remove('onboarding-open');
      window.setTimeout(() => {
        overlay.hidden = true;
      }, 250);
      if (markSeen) {
        try {
          localStorage.setItem(STORAGE_KEY, '1');
        } catch (error) {
          /* ignore storage errors */
        }
      }
    }

    nextButton.addEventListener('click', () => {
      if (currentIndex >= steps.length - 1) {
        closeOverlay();
        return;
      }
      updateStep(currentIndex + 1);
    });

    skipButton.addEventListener('click', () => {
      closeOverlay();
    });

    if (closeButton) {
      closeButton.addEventListener('click', () => {
        closeOverlay();
      });
    }

    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) {
        closeOverlay(false);
      }
    });

    triggers.forEach((trigger) => {
      trigger.addEventListener('click', () => {
        openOverlay(true);
      });
    });

    let shouldAutoOpen = true;
    try {
      shouldAutoOpen = !localStorage.getItem(STORAGE_KEY);
    } catch (error) {
      shouldAutoOpen = true;
    }

    if (shouldAutoOpen && !sessionStorage.getItem(SESSION_KEY)) {
      window.setTimeout(() => {
        openOverlay();
        sessionStorage.setItem(SESSION_KEY, 'auto');
      }, 1200);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOnboarding);
  } else {
    initOnboarding();
  }
})();
