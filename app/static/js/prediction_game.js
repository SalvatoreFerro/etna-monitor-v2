(function () {
  const form = document.querySelector('[data-prediction-form]');
  const feedback = document.querySelector('[data-prediction-feedback]');

  if (form) {
    const predictionInput = form.querySelector('input[name="prediction"]');
    const choices = form.querySelectorAll('[data-prediction-choice]');

    const submitPrediction = async (value) => {
      if (!predictionInput) return;
      predictionInput.value = value;
      if (feedback) {
        feedback.textContent = 'Invio previsione…';
      }
      try {
        const response = await fetch('/api/predictions', {
          method: 'POST',
          headers: {
            'X-Requested-With': 'fetch',
          },
          body: new FormData(form),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || 'Errore durante il salvataggio');
        }
        window.location.reload();
      } catch (error) {
        if (feedback) {
          feedback.textContent = error.message || 'Errore durante il salvataggio.';
        }
      }
    };

    choices.forEach((button) => {
      button.addEventListener('click', () => {
        const value = button.getAttribute('data-prediction-choice');
        if (value) {
          submitPrediction(value);
        }
      });
    });
  }

  const countdownEl = document.querySelector('[data-prediction-countdown]');
  if (countdownEl) {
    const resolvesAtRaw = countdownEl.getAttribute('data-resolves-at');
    const resolvesAt = resolvesAtRaw ? new Date(resolvesAtRaw) : null;

    const formatCountdown = () => {
      if (!resolvesAt || Number.isNaN(resolvesAt.getTime())) {
        countdownEl.textContent = 'Countdown non disponibile.';
        return;
      }
      const now = new Date();
      const diffMs = resolvesAt.getTime() - now.getTime();
      if (diffMs <= 0) {
        countdownEl.textContent = 'In valutazione…';
        return;
      }
      const diffSeconds = Math.floor(diffMs / 1000);
      const hours = Math.floor(diffSeconds / 3600);
      const minutes = Math.floor((diffSeconds % 3600) / 60);
      const seconds = diffSeconds % 60;
      countdownEl.textContent = `Mancano ${hours}h ${minutes}m ${seconds}s`;
    };

    formatCountdown();
    window.setInterval(formatCountdown, 1000);
  }
})();
