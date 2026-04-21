const state = {
  summary: null,
  fights: [],
  actorsByFight: {},
  result: null,
};

const els = {
  path: document.getElementById("log-path"),
  selectLog: document.getElementById("select-log"),
  openLog: document.getElementById("open-log"),
  importSummary: document.getElementById("import-summary"),
  fightSelect: document.getElementById("fight-select"),
  actorSelect: document.getElementById("actor-select"),
  specSelect: document.getElementById("spec-select"),
  analyze: document.getElementById("analyze"),
  exportReport: document.getElementById("export-report"),
  heroTitle: document.getElementById("hero-title"),
  heroSubtitle: document.getElementById("hero-subtitle"),
  report: document.getElementById("report"),
};

const api = window.go?.main?.App || {
  async SelectLogFile() {
    return "";
  },
  async OpenLog() {
    return {
      path: "mock",
      eventCount: 0,
      fightCount: 0,
      actorCount: 0,
      fights: [],
    };
  },
  async ListActors() {
    return [];
  },
  async AnalyzeFight() {
    return null;
  },
  async ExportReport() {
    return "";
  },
};

els.selectLog.addEventListener("click", async () => {
  const path = await api.SelectLogFile();
  if (path) {
    els.path.value = path;
  }
});

els.openLog.addEventListener("click", async () => {
  try {
    const summary = await api.OpenLog(els.path.value);
    state.summary = summary;
    state.fights = summary.fights || [];
    renderImportSummary(summary);
    renderFightSelect();
    await refreshActors();
  } catch (error) {
    renderError(error);
  }
});

els.fightSelect.addEventListener("change", async () => {
  await refreshActors();
});

els.actorSelect.addEventListener("change", () => {
  populateSpecSelect();
});

els.analyze.addEventListener("click", async () => {
  try {
    const result = await api.AnalyzeFight(
      els.fightSelect.value,
      els.actorSelect.value,
      els.specSelect.value
    );
    state.result = result;
    renderResult(result);
  } catch (error) {
    renderError(error);
  }
});

els.exportReport.addEventListener("click", async () => {
  try {
    const path = await api.ExportReport(
      els.fightSelect.value,
      els.actorSelect.value,
      els.specSelect.value,
      "html"
    );
    els.heroSubtitle.textContent = `Report exported to ${path}`;
  } catch (error) {
    renderError(error);
  }
});

function renderImportSummary(summary) {
  els.importSummary.textContent = `${summary.fightCount} fights · ${summary.actorCount} actors · ${summary.eventCount} events`;
}

function renderFightSelect() {
  els.fightSelect.innerHTML = "";
  state.fights.forEach((fight) => {
    const option = document.createElement("option");
    option.value = fight.id;
    option.textContent = `${fight.name} · ${fight.kind} · ${Math.round(fight.duration)}s`;
    els.fightSelect.appendChild(option);
  });
}

async function refreshActors() {
  const fightID = els.fightSelect.value;
  if (!fightID) {
    return;
  }
  const actors = await api.ListActors(fightID);
  state.actorsByFight[fightID] = actors;
  els.actorSelect.innerHTML = "";
  actors.forEach((actor) => {
    const option = document.createElement("option");
    option.value = actor.id;
    option.textContent = `${actor.name}${actor.class && actor.class !== "Unknown" ? ` · ${actor.class}` : ""}`;
    els.actorSelect.appendChild(option);
  });
  populateSpecSelect();
}

function populateSpecSelect() {
  const fightID = els.fightSelect.value;
  const actorID = els.actorSelect.value;
  const actors = state.actorsByFight[fightID] || [];
  const actor = actors.find((item) => item.id === actorID);
  const specs = actor?.detectedSpecs?.length
    ? actor.detectedSpecs
    : [
        "frost_mage",
        "arcane_mage",
        "devastation_evoker",
        "augmentation_evoker",
        "unholy_death_knight",
        "feral_druid",
      ];
  els.specSelect.innerHTML = "";
  specs.forEach((specID) => {
    const option = document.createElement("option");
    option.value = specID;
    option.textContent = specID.replaceAll("_", " ");
    els.specSelect.appendChild(option);
  });
}

function renderResult(result) {
  if (!result) {
    return;
  }
  els.heroTitle.textContent = `${result.summary.fightName} · ${result.summary.actorName}`;
  els.heroSubtitle.textContent = `${result.summary.specName} · ${Math.round(result.summary.duration)}s · ${result.summary.contentSource}`;

  const scoreCards = (result.scores || [])
    .map(
      (score) => `
        <article class="score">
          <div class="eyebrow">${escape(score.label)}</div>
          <div class="score-value">${Math.round(score.value)}</div>
          <small>${escape(score.detail)}</small>
        </article>
      `
    )
    .join("");

  const findingCards = (result.findings || [])
    .map(
      (finding) => `
        <article class="finding ${escape(finding.severity || "info")}">
          <div class="eyebrow">${escape(finding.severity || "info")}</div>
          <h3>${escape(finding.title)}</h3>
          <p>${escape(finding.explanation)}</p>
          <p><strong>Recommendation:</strong> ${escape(finding.recommendation)}</p>
        </article>
      `
    )
    .join("");

  const sectionCards = (result.sections || [])
    .map(
      (section) => `
        <article class="section">
          <div class="eyebrow">${escape(section.title)}</div>
          <p>${escape(section.summary)}</p>
          ${(section.lines || []).map((line) => `<div class="metric-line">${escape(line)}</div>`).join("")}
        </article>
      `
    )
    .join("");

  const timeline = (result.timeline || [])
    .map(
      (entry) => `
        <article class="timeline-item">
          <div class="timestamp">${escape(entry.timestamp)}</div>
          <div>${escape(entry.label)}</div>
        </article>
      `
    )
    .join("");

  els.report.classList.remove("empty");
  els.report.innerHTML = `
    <div class="score-grid">${scoreCards}</div>
    <div class="section-grid">
      <div class="cluster">
        <article class="section">
          <div class="eyebrow">Summary</div>
          <p>${escape(result.summary.specName)} on ${escape(result.summary.fightName)} with ${result.summary.totalCasts} casts.</p>
        </article>
        <div class="cluster">${findingCards || `<article class="section"><p>No findings generated.</p></article>`}</div>
      </div>
      <div class="cluster">
        ${sectionCards}
        <article class="section">
          <div class="eyebrow">Timeline</div>
          <div class="timeline">${timeline}</div>
        </article>
      </div>
    </div>
  `;
}

function renderError(error) {
  const message = typeof error === "string" ? error : error?.message || "Unknown error";
  els.heroSubtitle.textContent = message;
}

function escape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
