(() => {
  "use strict";

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) {
      try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* private mode */ }
    },
  };
  const script = document.currentScript;
  const siteRoot = new URL("../", script ? script.src : location.href);

  // ---- times: relative when recent, the reader's own clock otherwise ----

  const clock = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
  const dayClock = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const full = new Intl.DateTimeFormat(undefined, { dateStyle: "full", timeStyle: "short" });

  function ago(d) {
    const s = (Date.now() - d) / 1000;
    if (s < 90) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return null;
  }

  function paintTimes() {
    // A past day in the archive reads as dates; "23 h ago" means nothing there.
    const archive = document.body.classList.contains("page-archive");
    for (const t of $$("time[datetime]")) {
      const d = new Date(t.getAttribute("datetime"));
      if (Number.isNaN(d.getTime())) continue;
      t.title = full.format(d);
      if (t.classList.contains("when")) t.textContent = clock.format(d);
      else if (archive && !t.classList.contains("built")) t.textContent = dayClock.format(d);
      else t.textContent = ago(d) || dayClock.format(d);
    }
  }

  // ---- the river, grouped by the reader's own days ----

  function regroupDays() {
    const list = $(".items");
    if (!list) return;
    $$("li.day", list).forEach((li) => li.remove());
    const fmt = new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long" });
    const today = new Date().toDateString();
    const yesterday = new Date(Date.now() - 86400000).toDateString();
    let last = null;
    for (const li of $$("li.item", list)) {
      const d = new Date($("time", li).getAttribute("datetime"));
      const key = d.toDateString();
      if (key === last) continue;
      last = key;
      const head = document.createElement("li");
      head.className = "day";
      const h3 = document.createElement("h3");
      h3.textContent = key === today ? "Today" : key === yesterday ? "Yesterday" : fmt.format(d);
      head.append(h3);
      li.before(head);
    }
  }

  // ---- filtering: by a trend chip, by typed words, or both ----

  const trendIds = (() => {
    try { return JSON.parse($("#trend-ids")?.textContent || "{}"); } catch { return {}; }
  })();
  let activeTrend = null;
  const filterBox = $(".filter");

  function applyFilter() {
    const list = $(".items");
    if (!list) return;
    const q = (filterBox?.value || "").trim();
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const ids = activeTrend ? new Set(trendIds[activeTrend] || []) : null;
    let shown = 0;
    let day = null;
    let dayHas = false;
    const closeDay = () => { if (day) day.hidden = !dayHas; };
    for (const li of list.children) {
      if (li.classList.contains("day")) {
        closeDay();
        day = li;
        dayHas = false;
        continue;
      }
      const hay = li.textContent.toLowerCase();
      const ok = (!ids || ids.has(li.dataset.id)) && words.every((w) => hay.includes(w));
      li.hidden = !ok;
      if (ok) { shown += 1; dayHas = true; }
    }
    closeDay();

    const filtering = Boolean(ids || words.length);
    const top = $(".top");
    if (top) top.hidden = filtering;
    const state = $(".filter-state");
    if (state) {
      state.hidden = !filtering;
      if (filtering) {
        const chip = activeTrend && $(`.chip[data-trend="${CSS.escape(activeTrend)}"]`);
        let msg = `${shown} ${shown === 1 ? "story" : "stories"}`;
        if (chip) msg += ` about “${chip.dataset.label}”`;
        if (words.length) msg += ` matching “${q}”`;
        $(".filter-text", state).textContent = msg;
      }
    }
    const empty = $(".empty");
    if (empty) empty.hidden = !filtering || shown > 0;
    for (const b of $$(".chip[data-trend]")) {
      b.setAttribute("aria-pressed", String(b.dataset.trend === activeTrend));
    }
  }

  function setTrend(key) {
    activeTrend = key && trendIds[key] ? key : null;
    const url = new URL(location.href);
    url.hash = activeTrend ? `trend=${encodeURIComponent(activeTrend)}` : "";
    history.replaceState(null, "", activeTrend ? url : url.pathname + url.search);
    applyFilter();
  }

  for (const chip of $$(".chip[data-trend]")) {
    chip.addEventListener("click", () => {
      setTrend(chip.dataset.trend === activeTrend ? null : chip.dataset.trend);
      if (activeTrend) $(".river")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
  filterBox?.addEventListener("input", applyFilter);
  filterBox?.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { filterBox.value = ""; applyFilter(); filterBox.blur(); }
  });
  $(".clear")?.addEventListener("click", () => {
    if (filterBox) filterBox.value = "";
    setTrend(null);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    const el = document.activeElement;
    if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
    if (!filterBox) return;
    e.preventDefault();
    filterBox.focus();
  });

  // ---- summaries in the river ----

  const sums = $(".show-sums");
  if (sums) {
    sums.checked = store.get("sums") === "1";
    document.body.classList.toggle("show-sums", sums.checked);
    sums.addEventListener("change", () => {
      document.body.classList.toggle("show-sums", sums.checked);
      store.set("sums", sums.checked ? "1" : null);
    });
  }

  // ---- theme: system, light, dark ----

  const themes = [
    { id: null, glyph: "◐", label: "Colour theme: follows the system" },
    { id: "light", glyph: "☀", label: "Colour theme: light" },
    { id: "dark", glyph: "☾", label: "Colour theme: dark" },
  ];
  const themeBtn = $(".theme");
  function showTheme() {
    const cur = document.documentElement.dataset.theme || null;
    const t = themes.find((x) => x.id === cur) || themes[0];
    if (themeBtn) {
      themeBtn.textContent = t.glyph;
      themeBtn.setAttribute("aria-label", t.label);
      themeBtn.title = t.label;
    }
  }
  themeBtn?.addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || null;
    const next = themes[(themes.findIndex((x) => x.id === cur) + 1) % themes.length];
    if (next.id) document.documentElement.dataset.theme = next.id;
    else delete document.documentElement.dataset.theme;
    store.set("theme", next.id);
    showTheme();
  });

  // ---- thumbnails that fail or are too small to be photos ----

  for (const img of $$(".thumb img")) {
    const drop = () => img.closest(".thumb")?.remove();
    const check = () => { if (img.naturalWidth < 80) drop(); };
    if (img.complete && img.getAttribute("src")) check();
    else {
      img.addEventListener("load", check);
      img.addEventListener("error", drop);
    }
  }

  // ---- a newer build: offer to reload ----

  const built = $("time.built")?.getAttribute("datetime");
  let offered = false;
  async function checkFresh() {
    if (offered || document.hidden || !built) return;
    try {
      const r = await fetch(new URL("build.json", siteRoot), { cache: "no-store" });
      const j = await r.json();
      if (j.built * 1000 > Date.parse(built)) {
        offered = true;
        const b = document.createElement("button");
        b.type = "button";
        b.className = "fresh";
        b.textContent = "New stories — reload";
        b.addEventListener("click", () => location.reload());
        document.body.append(b);
      }
    } catch { /* offline, or the file is not there yet */ }
  }

  // ---- go ----

  paintTimes();
  regroupDays();
  showTheme();
  const m = location.hash.match(/^#trend=(.+)$/);
  if (m) setTrend(decodeURIComponent(m[1]));
  else applyFilter();
  setInterval(paintTimes, 60 * 1000);
  setInterval(checkFresh, 10 * 60 * 1000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { paintTimes(); checkFresh(); } });
})();
