(() => {
  const kpiMap = new Map();
  document.querySelectorAll("[data-kpi]").forEach((el) => {
    kpiMap.set(el.dataset.kpi, el);
  });

  const healthMap = new Map();
  document.querySelectorAll("[data-health]").forEach((el) => {
    healthMap.set(el.dataset.health, el);
  });

  const runsBody = document.getElementById("monitor-runs-body");
  const filtersForm = document.getElementById("monitor-filters");
  const refreshButton = document.querySelector("[data-action='refresh-runs']");
  const rangeButtons = document.querySelectorAll(".monitor-range-toggle [data-range]");

  const drawer = document.getElementById("monitor-drawer");
  const drawerSubtitle = document.getElementById("drawer-subtitle");
  const drawerJson = document.getElementById("drawer-json");
  const drawerSkipped = document.getElementById("drawer-skipped");
  const drawerError = document.getElementById("drawer-error");
  const drawerErrorType = document.getElementById("drawer-error-type");
  const drawerErrorMessage = document.getElementById("drawer-error-message");
  const drawerErrorTrace = document.getElementById("drawer-error-trace");

  const chartSent = document.getElementById("chart-sent");
  const chartFailures = document.getElementById("chart-failures");
  const chartDuration = document.getElementById("chart-duration");

  let currentRange = "24h";

  const formatDateTime = (value) => {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("it-IT", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(date);
  };

  const formatDuration = (value) => {
    if (value === null || value === undefined) return "--";
    return `${value.toFixed(1)} ms`;
  };

  const setStatusBadge = (value) => {
    const statusEl = kpiMap.get("status");
    const hintEl = kpiMap.get("status_hint");
    if (!statusEl) return;
    statusEl.classList.remove("monitor-status--ok", "monitor-status--degraded", "monitor-status--down");
    if (value === "OK") {
      statusEl.classList.add("monitor-status--ok");
      hintEl.textContent = "Ultimi run stabili";
    } else if (value === "DEGRADED") {
      statusEl.classList.add("monitor-status--degraded");
      hintEl.textContent = "Errori recenti ma cron attivo";
    } else {
      statusEl.classList.add("monitor-status--down");
      hintEl.textContent = "Possibile interruzione cron";
    }
    statusEl.textContent = value || "--";
  };

  const renderHealthChecks = (checks) => {
    if (!checks) return;
    const dbEl = healthMap.get("db_reachable");
    const csvEl = healthMap.get("csv_exists");
    const csvMtimeEl = healthMap.get("csv_mtime");
    const telegramEl = healthMap.get("telegram_configured");
    const premiumEl = healthMap.get("premium_chat_users");

    if (dbEl) dbEl.textContent = checks.db_reachable ? "OK" : "DOWN";
    if (csvEl) csvEl.textContent = checks.csv_exists ? "OK" : "MISSING";
    if (csvMtimeEl) csvMtimeEl.textContent = checks.csv_mtime ? formatDateTime(checks.csv_mtime) : "--";
    if (telegramEl) telegramEl.textContent = checks.telegram_configured ? "CONFIGURATO" : "ASSENTE";
    if (premiumEl) premiumEl.textContent = checks.premium_chat_users ?? "--";
  };

  const updateKpis = async () => {
    const response = await fetch(`/admin/api/monitor/kpis?range=${currentRange}`);
    if (!response.ok) return;
    const data = await response.json();

    setStatusBadge(data.status);
    if (kpiMap.get("last_run")) {
      kpiMap.get("last_run").textContent = data.last_run?.created_at
        ? formatDateTime(data.last_run.created_at)
        : "--";
    }
    if (kpiMap.get("last_run_hint")) {
      const lastRunOk = data.last_run?.ok;
      kpiMap.get("last_run_hint").textContent = lastRunOk === undefined ? "--" : (lastRunOk ? "OK" : "FAILED");
    }
    if (kpiMap.get("runs_total")) {
      kpiMap.get("runs_total").textContent = data.runs_total ?? "--";
    }
    if (kpiMap.get("failures_count")) {
      kpiMap.get("failures_count").textContent = `Errori: ${data.failures_count ?? "--"}`;
    }
    if (kpiMap.get("sent_total")) {
      kpiMap.get("sent_total").textContent = data.sent_total ?? "--";
    }
    if (kpiMap.get("skipped_total")) {
      kpiMap.get("skipped_total").textContent = data.skipped_total ?? "--";
    }
    if (kpiMap.get("csv_update")) {
      kpiMap.get("csv_update").textContent = data.last_csv_update?.csv_mtime
        ? formatDateTime(data.last_csv_update.csv_mtime)
        : "--";
    }
    if (kpiMap.get("csv_size")) {
      const size = data.last_csv_update?.csv_size_bytes;
      kpiMap.get("csv_size").textContent = size ? `${(size / 1024).toFixed(1)} KB` : "--";
    }
    if (kpiMap.get("last_point")) {
      kpiMap.get("last_point").textContent = data.last_point?.last_point_ts
        ? formatDateTime(data.last_point.last_point_ts)
        : "--";
    }
    if (kpiMap.get("moving_avg")) {
      const moving = data.last_point?.moving_avg;
      kpiMap.get("moving_avg").textContent = moving ? `Moving avg: ${moving.toFixed(2)}` : "--";
    }

    renderHealthChecks(data.health_checks);
  };

  const renderRuns = (runs) => {
    if (!runsBody) return;
    if (!runs || runs.length === 0) {
      runsBody.innerHTML = `<tr><td colspan="8" class="admin-empty">Nessun run trovato.</td></tr>`;
      return;
    }
    runsBody.innerHTML = runs
      .map((run) => {
        const okBadge = run.ok ? "<span class='monitor-badge monitor-badge--ok'>OK</span>" : "<span class='monitor-badge monitor-badge--fail'>FAIL</span>";
        return `
          <tr data-run-id="${run.id}">
            <td>${formatDateTime(run.created_at)}</td>
            <td>${run.job_type}</td>
            <td>${okBadge}</td>
            <td>${formatDuration(run.duration_ms)}</td>
            <td>${run.sent_count ?? "--"}</td>
            <td>${run.skipped_count ?? "--"}</td>
            <td>${run.reason ?? "--"}</td>
            <td>${formatDateTime(run.last_point_ts)}</td>
          </tr>
        `;
      })
      .join("");
  };

  const fetchRuns = async () => {
    const params = new URLSearchParams();
    if (filtersForm) {
      const formData = new FormData(filtersForm);
      formData.forEach((value, key) => {
        if (value) {
          params.set(key, value.toString());
        }
      });
    }
    params.set("limit", "100");
    const response = await fetch(`/admin/api/monitor/runs?${params.toString()}`);
    if (!response.ok) return;
    const data = await response.json();
    renderRuns(data.runs || []);
  };

  const openDrawer = async (runId) => {
    const response = await fetch(`/admin/api/monitor/runs/${runId}`);
    if (!response.ok) return;
    const run = await response.json();
    drawerSubtitle.textContent = `${run.job_type} • ${formatDateTime(run.created_at)}`;
    drawerJson.textContent = JSON.stringify(run.payload || run, null, 2);

    drawerSkipped.innerHTML = "";
    const skipped = run.skipped_by_reason || {};
    const skippedEntries = Object.entries(skipped);
    if (skippedEntries.length === 0) {
      drawerSkipped.innerHTML = "<p class='muted'>Nessun dato</p>";
    } else {
      skippedEntries.forEach(([reason, count]) => {
        const card = document.createElement("div");
        card.className = "monitor-skipped-card";
        card.innerHTML = `<span>${reason}</span><strong>${count}</strong>`;
        drawerSkipped.appendChild(card);
      });
    }

    if (run.error_type || run.error_message || run.traceback) {
      drawerError.open = true;
      drawerErrorType.textContent = run.error_type || "Errore";
      drawerErrorMessage.textContent = run.error_message || "--";
      drawerErrorTrace.textContent = run.traceback || "--";
    } else {
      drawerError.open = false;
      drawerErrorType.textContent = "--";
      drawerErrorMessage.textContent = "--";
      drawerErrorTrace.textContent = "--";
    }

    if (typeof drawer.showModal === "function") {
      drawer.showModal();
    } else {
      drawer.setAttribute("open", "");
    }
  };

  const loadCharts = async () => {
    if (!chartSent || !window.Plotly) return;
    const response = await fetch(`/admin/api/monitor/runs?job_type=check_alerts&range=${currentRange}&limit=250`);
    if (!response.ok) return;
    const data = await response.json();
    const runs = data.runs || [];
    const timestamps = runs.map((run) => run.created_at).reverse();

    const sentValues = runs.map((run) => run.sent_count || 0).reverse();
    const durationValues = runs.map((run) => run.duration_ms || 0).reverse();
    const failureValues = runs.map((run) => (run.ok ? 0 : 1)).reverse();

    const layoutBase = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#dfe6ff" },
      xaxis: { showgrid: false, color: "#9bb0d1" },
      yaxis: { gridcolor: "rgba(255,255,255,0.08)", zeroline: false },
      margin: { l: 40, r: 20, t: 30, b: 40 },
    };

    window.Plotly.react(
      chartSent,
      [{ x: timestamps, y: sentValues, type: "scatter", mode: "lines+markers", name: "Sent" }],
      { ...layoutBase, title: "Notifiche inviate" }
    );
    window.Plotly.react(
      chartFailures,
      [{ x: timestamps, y: failureValues, type: "bar", name: "Failed runs" }],
      { ...layoutBase, title: "Run falliti" }
    );
    window.Plotly.react(
      chartDuration,
      [{ x: timestamps, y: durationValues, type: "scatter", mode: "lines+markers", name: "Duration (ms)" }],
      { ...layoutBase, title: "Durata (ms)" }
    );
  };

  if (refreshButton) {
    refreshButton.addEventListener("click", () => {
      fetchRuns();
      updateKpis();
    });
  }

  if (filtersForm) {
    filtersForm.addEventListener("change", () => {
      fetchRuns();
    });
  }

  if (runsBody) {
    runsBody.addEventListener("click", (event) => {
      const row = event.target.closest("tr[data-run-id]");
      if (!row) return;
      openDrawer(row.dataset.runId);
    });
  }

  document.querySelectorAll("[data-action='close-drawer']").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (drawer?.close) {
        drawer.close();
      } else {
        drawer.removeAttribute("open");
      }
    });
  });

  rangeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      rangeButtons.forEach((el) => el.classList.remove("is-active"));
      btn.classList.add("is-active");
      currentRange = btn.dataset.range || "24h";
      updateKpis();
      loadCharts();
    });
  });

  updateKpis();
  fetchRuns();
  loadCharts();
})();
