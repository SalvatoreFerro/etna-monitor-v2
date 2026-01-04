(() => {
  const kpiMap = new Map();
  document.querySelectorAll("[data-kpi]").forEach((el) => {
    kpiMap.set(el.dataset.kpi, el);
  });

  const runsBody = document.getElementById("monitor-runs-body");
  const refreshButton = document.querySelector("[data-action='refresh-runs']");
  const rangeButtons = document.querySelectorAll(".monitor-range-toggle [data-range]");

  const drawer = document.getElementById("monitor-drawer");
  const drawerSubtitle = document.getElementById("drawer-subtitle");
  const drawerJson = document.getElementById("drawer-json");

  const chartRuns = document.getElementById("chart-runs");
  const chartSent = document.getElementById("chart-sent");
  const chartErrors = document.getElementById("chart-errors");

  let currentRange = "24h";
  let runsById = new Map();

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

  const setStatusBadge = (value, hint) => {
    const statusEl = kpiMap.get("status");
    const hintEl = kpiMap.get("status_hint");
    if (!statusEl) return;
    statusEl.classList.remove("monitor-status--ok", "monitor-status--degraded", "monitor-status--down");
    if (value === "GREEN") {
      statusEl.classList.add("monitor-status--ok");
      hintEl.textContent = hint || "Cron attivo nelle ultime 2 ore";
    } else if (value === "YELLOW") {
      statusEl.classList.add("monitor-status--degraded");
      hintEl.textContent = hint || "Ultimo run oltre 2 ore fa";
    } else {
      statusEl.classList.add("monitor-status--down");
      hintEl.textContent = hint || "Ultimo run oltre 4 ore fa o con errore";
    }
    statusEl.textContent = value || "--";
  };

  const updateKpis = async () => {
    const response = await fetch("/admin/cron/summary");
    if (!response.ok) return;
    const data = await response.json();

    const lastRun = data.last_run;
    const lastRunTimestamp = lastRun?.started_at || lastRun?.created_at;
    const lastRunDate = lastRunTimestamp ? new Date(lastRunTimestamp) : null;
    const now = new Date();
    const ageHours = lastRunDate ? (now - lastRunDate) / 36e5 : null;
    let statusValue = "RED";
    if (lastRunDate && lastRun?.status !== "error") {
      if (ageHours < 2) {
        statusValue = "GREEN";
      } else if (ageHours < 4) {
        statusValue = "YELLOW";
      }
    }
    setStatusBadge(statusValue);

    if (kpiMap.get("last_run_time")) {
      kpiMap.get("last_run_time").textContent = lastRunTimestamp
        ? formatDateTime(lastRunTimestamp)
        : "--";
    }
    if (kpiMap.get("last_run_hint")) {
      if (!lastRunDate) {
        kpiMap.get("last_run_hint").textContent = "--";
      } else if (lastRun?.status === "error") {
        kpiMap.get("last_run_hint").textContent = "Ultimo run con errore";
      } else {
        kpiMap.get("last_run_hint").textContent = `Ultimo run ${Math.round(ageHours * 10) / 10}h fa`;
      }
    }
    if (kpiMap.get("runs_24h")) {
      kpiMap.get("runs_24h").textContent = data.runs_24h ?? "--";
    }
    if (kpiMap.get("errors_24h")) {
      kpiMap.get("errors_24h").textContent = `Errori: ${data.errors_24h ?? "--"}`;
    }
    if (kpiMap.get("sent_24h")) {
      kpiMap.get("sent_24h").textContent = data.sent_24h ?? "--";
    }
    if (kpiMap.get("skipped_24h")) {
      kpiMap.get("skipped_24h").textContent = data.skipped_24h ?? "--";
    }
  };

  const renderRuns = (runs) => {
    if (!runsBody) return;
    runsById = new Map();
    runs.forEach((run) => runsById.set(String(run.id), run));
    if (!runs || runs.length === 0) {
      runsBody.innerHTML = `<tr><td colspan="6" class="admin-empty">Nessun run trovato.</td></tr>`;
      return;
    }
    runsBody.innerHTML = runs
      .map((run) => {
        const statusBadge =
          run.status === "success"
            ? "<span class='monitor-badge monitor-badge--ok'>OK</span>"
            : "<span class='monitor-badge monitor-badge--fail'>ERROR</span>";
        return `
          <tr data-run-id="${run.id}">
            <td>${formatDateTime(run.started_at || run.created_at)}</td>
            <td>${statusBadge}</td>
            <td>${formatDuration(run.duration_ms)}</td>
            <td>${run.sent_count ?? "--"}</td>
            <td>${run.skipped_count ?? "--"}</td>
            <td><button class="btn btn-ghost" type="button" data-action="view-diagnostic">Apri</button></td>
          </tr>
        `;
      })
      .join("");
  };

  const fetchRuns = async () => {
    const response = await fetch("/admin/cron/runs?limit=50");
    if (!response.ok) return;
    const data = await response.json();
    renderRuns(data.runs || []);
  };

  const openDrawer = (runId) => {
    const run = runsById.get(String(runId));
    if (!run) return;
    const jobLabel = run.job_type || "check-alerts";
    drawerSubtitle.textContent = `${jobLabel} • ${formatDateTime(run.started_at || run.created_at)}`;
    const diagnostic = run.diagnostic_json || {};
    drawerJson.textContent = JSON.stringify(diagnostic, null, 2);

    if (typeof drawer.showModal === "function") {
      drawer.showModal();
    } else {
      drawer.setAttribute("open", "");
    }
  };

  const loadCharts = async () => {
    if (!chartSent || !window.Plotly) return;
    const response = await fetch(`/admin/cron/runs?range=${currentRange}&limit=250`);
    if (!response.ok) return;
    const data = await response.json();
    const runs = data.runs || [];
    const bucketMs = currentRange === "7d" ? 24 * 60 * 60 * 1000 : 60 * 60 * 1000;
    const buckets = new Map();

    runs.forEach((run) => {
      const timestamp = run.started_at || run.created_at;
      if (!timestamp) return;
      const date = new Date(timestamp);
      const bucketTime = new Date(Math.floor(date.getTime() / bucketMs) * bucketMs).toISOString();
      if (!buckets.has(bucketTime)) {
        buckets.set(bucketTime, { runs: 0, sent: 0, errors: 0 });
      }
      const bucket = buckets.get(bucketTime);
      bucket.runs += 1;
      bucket.sent += run.sent_count || 0;
      if (run.status === "error") {
        bucket.errors += 1;
      }
    });

    const sortedKeys = Array.from(buckets.keys()).sort();
    const timestamps = sortedKeys.map((key) => new Date(key));
    const runValues = sortedKeys.map((key) => buckets.get(key).runs);
    const sentValues = sortedKeys.map((key) => buckets.get(key).sent);
    const errorValues = sortedKeys.map((key) => buckets.get(key).errors);

    const layoutBase = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#dfe6ff" },
      xaxis: { showgrid: false, color: "#9bb0d1" },
      yaxis: { gridcolor: "rgba(255,255,255,0.08)", zeroline: false },
      margin: { l: 40, r: 20, t: 30, b: 40 },
    };

    if (chartRuns) {
      window.Plotly.react(
        chartRuns,
        [{ x: timestamps, y: runValues, type: "scatter", mode: "lines+markers", name: "Runs" }],
        { ...layoutBase, title: "Runs over time" }
      );
    }
    window.Plotly.react(
      chartSent,
      [{ x: timestamps, y: sentValues, type: "scatter", mode: "lines+markers", name: "Sent" }],
      { ...layoutBase, title: "Alerts sent" }
    );
    if (chartErrors) {
      window.Plotly.react(
        chartErrors,
        [{ x: timestamps, y: errorValues, type: "bar", name: "Errors" }],
        { ...layoutBase, title: "Errors" }
      );
    }
  };

  if (refreshButton) {
    refreshButton.addEventListener("click", () => {
      fetchRuns();
      updateKpis();
    });
  }

  if (runsBody) {
    runsBody.addEventListener("click", (event) => {
      const row = event.target.closest("tr[data-run-id]");
      if (!row) return;
      if (event.target.matches("[data-action='view-diagnostic']")) {
        openDrawer(row.dataset.runId);
      }
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
