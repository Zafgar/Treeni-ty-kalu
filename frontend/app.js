// Treeni-ty-kalu — selainkäyttöliittymä (vanilla JS, ei build-vaihetta).

const api = {
  async req(method, path, body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  },
  get(p) { return this.req("GET", p); },
  post(p, b) { return this.req("POST", p, b); },
  patch(p, b) { return this.req("PATCH", p, b); },
  del(p) { return this.req("DELETE", p); },
};

let exercisesCache = [];

// ---------- Välilehdet ----------
const TAB_LOADERS = {}; // täytetään myöhemmin: { tabName: async () => {...} }

document.querySelectorAll("nav#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav#tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    const loader = TAB_LOADERS[btn.dataset.tab];
    if (loader) loader();
  });
});

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const c of children) e.append(c?.nodeType ? c : document.createTextNode(c ?? ""));
  return e;
}

// =================== LIIKKEET ===================
async function loadExercises() {
  exercisesCache = await api.get("/api/exercises");
  const list = document.getElementById("exercise-list");
  list.innerHTML = "";
  if (!exercisesCache.length) {
    list.append(el("p", { class: "muted" }, "Ei liikkeitä vielä. Lisää ensimmäinen liike."));
  }
  for (const ex of exercisesCache) {
    const tags = [];
    if (ex.is_main_lift) tags.push(el("span", { class: "tag main" }, "pääliike"));
    if (ex.category) tags.push(el("span", { class: "tag" }, ex.category));
    if (ex.sport) tags.push(el("span", { class: "tag" }, ex.sport));
    const item = el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("strong", {}, ex.name),
        el("button", { class: "small danger", onclick: async () => {
          if (confirm(`Poista liike "${ex.name}"?`)) { await api.del(`/api/exercises/${ex.id}`); loadExercises(); }
        } }, "Poista")
      ),
      el("div", {}, ...tags)
    );
    if (ex.muscle_group) item.append(el("div", { class: "muted" }, ex.muscle_group));
    list.append(item);
  }
}

document.getElementById("new-exercise-btn").addEventListener("click", () => {
  const form = document.getElementById("exercise-form");
  form.classList.remove("hidden");
  form.innerHTML = "";
  const name = el("input", { placeholder: "Esim. Kyykky" });
  const category = el("input", { placeholder: "Kategoria (esim. jalat)" });
  const muscle = el("input", { placeholder: "Lihasryhmä" });
  const sport = el("input", { placeholder: "Laji (esim. voimanosto)" });
  const main = el("input", { type: "checkbox" });
  form.append(
    el("div", { class: "grid" },
      el("label", {}, "Nimi", name),
      el("label", {}, "Kategoria", category),
      el("label", {}, "Lihasryhmä", muscle),
      el("label", {}, "Laji", sport),
      el("label", {}, "Pääliike (total)", main)
    ),
    el("div", { class: "btn-row" },
      el("button", { class: "success", onclick: async () => {
        if (!name.value.trim()) return alert("Anna liikkeelle nimi.");
        try {
          await api.post("/api/exercises", {
            name: name.value.trim(),
            category: category.value.trim() || null,
            muscle_group: muscle.value.trim() || null,
            sport: sport.value.trim() || null,
            is_main_lift: main.checked,
          });
          form.classList.add("hidden");
          loadExercises();
        } catch (e) { alert("Virhe: " + e.message); }
      } }, "Tallenna"),
      el("button", { onclick: () => form.classList.add("hidden") }, "Peruuta")
    )
  );
});

// =================== OHJELMAT ===================
async function loadPrograms() {
  const programs = await api.get("/api/programs");
  const list = document.getElementById("program-list");
  list.innerHTML = "";
  if (!programs.length) {
    list.append(el("p", { class: "muted" }, "Ei ohjelmia vielä."));
  }
  for (const p of programs) {
    const item = el("div", { class: "item" });
    item.append(el("div", { class: "row-between" },
      el("strong", {}, p.name),
      el("button", { class: "small danger", onclick: async () => {
        if (confirm(`Poista ohjelma "${p.name}"?`)) { await api.del(`/api/programs/${p.id}`); loadPrograms(); }
      } }, "Poista")
    ));
    const meta = [p.schedule_type === "cycle" ? "Sykli" : "Viikko"];
    if (p.goal) meta.push(p.goal);
    item.append(el("div", { class: "muted" }, meta.join(" · ")));
    for (const day of p.days) {
      const db = el("div", { class: "day-block " + (day.day_type === "rest" ? "rest" : "") });
      db.append(el("strong", {}, (day.label || `Päivä ${day.order_index + 1}`) +
        (day.day_type === "rest" ? " (lepo)" : "")));
      for (const pe of day.exercises) {
        const wTxt = pe.target_weight ? ` @ ${pe.target_weight}kg` : "";
        db.append(el("div", { class: "muted" },
          `${pe.exercise.name}: ${pe.target_sets}×${pe.target_reps}${wTxt}` +
          (pe.rest_seconds ? ` · palautus ${pe.rest_seconds}s` : "")));
      }
      if (day.day_type === "train") {
        db.append(el("button", { class: "small", onclick: async () => {
          const w = await api.post(`/api/workouts/from-program-day/${day.id}`);
          document.querySelector('nav#tabs button[data-tab="workouts"]').click();
          await loadWorkouts();
          openWorkoutEditor(w.id);
        } }, "Aloita treeni tästä"));
      }
      item.append(db);
    }
    list.append(item);
  }
}

document.getElementById("new-program-btn").addEventListener("click", () => {
  if (!exercisesCache.length) return alert("Lisää ensin liikkeitä Liikkeet-välilehdellä.");
  const editor = document.getElementById("program-editor");
  editor.classList.remove("hidden");
  editor.innerHTML = "";
  const name = el("input", { placeholder: "Ohjelman nimi" });
  const goal = el("input", { placeholder: "Tavoite (esim. voima)" });
  const type = el("select", {}, el("option", { value: "cycle" }, "Sykli (treeni/lepo)"),
    el("option", { value: "weekly" }, "Viikko"));
  const daysContainer = el("div", {});
  const days = []; // { dayType, label, exercises: [] }

  function renderDays() {
    daysContainer.innerHTML = "";
    days.forEach((day, di) => {
      const block = el("div", { class: "day-block " + (day.dayType === "rest" ? "rest" : "") });
      const labelInput = el("input", { value: day.label, placeholder: "Päivän nimi",
        oninput: (e) => (day.label = e.target.value) });
      const typeSel = el("select", { onchange: (e) => { day.dayType = e.target.value; renderDays(); } },
        el("option", { value: "train" }, "Treenipäivä"),
        el("option", { value: "rest" }, "Lepopäivä"));
      typeSel.value = day.dayType;
      block.append(el("div", { class: "btn-row" }, labelInput, typeSel,
        el("button", { class: "small danger", onclick: () => { days.splice(di, 1); renderDays(); } }, "Poista päivä")));
      if (day.dayType === "train") {
        day.exercises.forEach((pe, ei) => {
          const sel = el("select", { onchange: (e) => (pe.exercise_id = +e.target.value) });
          exercisesCache.forEach((ex) => sel.append(el("option", { value: ex.id }, ex.name)));
          sel.value = pe.exercise_id;
          const sets = el("input", { type: "number", value: pe.target_sets, oninput: (e) => (pe.target_sets = +e.target.value) });
          const reps = el("input", { type: "number", value: pe.target_reps, oninput: (e) => (pe.target_reps = +e.target.value) });
          const wt = el("input", { type: "number", step: "0.5", value: pe.target_weight ?? "", oninput: (e) => (pe.target_weight = e.target.value ? +e.target.value : null) });
          const rest = el("input", { type: "number", value: pe.rest_seconds ?? "", oninput: (e) => (pe.rest_seconds = e.target.value ? +e.target.value : null) });
          const scheme = el("input", { value: pe.rep_scheme ?? "", placeholder: "12,10,8", oninput: (e) => (pe.rep_scheme = e.target.value || null) });
          const pct = el("input", { value: pe.percent_scheme ?? "", placeholder: "75,80,80", oninput: (e) => (pe.percent_scheme = e.target.value || null) });
          block.append(el("div", { class: "btn-row" }, sel,
            el("label", {}, "sarjat", sets), el("label", {}, "toistot", reps),
            el("label", {}, "kg", wt), el("label", {}, "palautus s", rest),
            el("label", {}, "malli (toistot/sarja)", scheme),
            el("label", {}, "% 1RM", pct),
            el("button", { class: "small danger", onclick: () => { day.exercises.splice(ei, 1); renderDays(); } }, "x")));
        });
        block.append(el("button", { class: "small", onclick: () => {
          day.exercises.push({ exercise_id: exercisesCache[0].id, order_index: day.exercises.length, target_sets: 3, target_reps: 5, target_weight: null, rest_seconds: null });
          renderDays();
        } }, "+ Liike"));
      }
      daysContainer.append(block);
    });
  }

  editor.append(
    el("div", { class: "grid" }, el("label", {}, "Nimi", name), el("label", {}, "Tavoite", goal), el("label", {}, "Tyyppi", type)),
    daysContainer,
    el("div", { class: "btn-row" },
      el("button", { class: "small", onclick: () => { days.push({ dayType: "train", label: "", exercises: [] }); renderDays(); } }, "+ Treenipäivä"),
      el("button", { class: "small", onclick: () => { days.push({ dayType: "rest", label: "Lepo", exercises: [] }); renderDays(); } }, "+ Lepopäivä")),
    el("div", { class: "btn-row" },
      el("button", { class: "success", onclick: async () => {
        if (!name.value.trim()) return alert("Anna ohjelmalle nimi.");
        const payload = {
          name: name.value.trim(), goal: goal.value.trim() || null, schedule_type: type.value,
          days: days.map((d, i) => ({ order_index: i, day_type: d.dayType, label: d.label || null,
            exercises: d.exercises.map((e, ei) => ({ ...e, order_index: ei })) })),
        };
        try { await api.post("/api/programs", payload); editor.classList.add("hidden"); loadPrograms(); }
        catch (e) { alert("Virhe: " + e.message); }
      } }, "Tallenna ohjelma"),
      el("button", { onclick: () => editor.classList.add("hidden") }, "Peruuta"))
  );
  renderDays();
});

// =================== TREENIT ===================
async function loadWorkouts() {
  const workouts = await api.get("/api/workouts");
  const list = document.getElementById("workout-list");
  list.innerHTML = "";
  if (!workouts.length) list.append(el("p", { class: "muted" }, "Ei treenejä vielä."));
  for (const w of workouts) {
    const total = w.exercises.reduce((sum, we) =>
      sum + we.sets.reduce((s, set) => s + (set.completed ? set.reps * set.weight : 0), 0), 0);
    const item = el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("strong", {}, `${w.session_date} — ${w.name || "Treeni"}`),
        el("div", { class: "btn-row" },
          el("button", { class: "small", onclick: () => openWorkoutEditor(w.id) }, "Avaa"),
          el("button", { class: "small danger", onclick: async () => {
            if (confirm("Poista treeni?")) { await api.del(`/api/workouts/${w.id}`); loadWorkouts(); }
          } }, "Poista"))),
      el("div", { class: "muted" }, `${w.exercises.length} liikettä · kokonaiskuorma ${Math.round(total)} kg`)
    );
    list.append(item);
  }
}

document.getElementById("new-workout-btn").addEventListener("click", async () => {
  const w = await api.post("/api/workouts", { name: "Vapaa treeni", exercises: [] });
  await loadWorkouts();
  openWorkoutEditor(w.id);
});

async function openWorkoutEditor(id) {
  const w = await api.get(`/api/workouts/${id}`);
  const editor = document.getElementById("workout-editor");
  editor.classList.remove("hidden");
  editor.innerHTML = "";
  editor.scrollIntoView({ behavior: "smooth" });

  const nameInput = el("input", { value: w.name || "", placeholder: "Treenin nimi" });
  const dateInput = el("input", { type: "date", value: w.session_date });
  const bw = el("input", { type: "number", step: "0.1", value: w.bodyweight ?? "", placeholder: "kg" });
  const notes = el("input", { value: w.notes || "", placeholder: "Huomiot" });

  async function saveMeta() {
    await api.patch(`/api/workouts/${id}`, {
      name: nameInput.value, session_date: dateInput.value,
      bodyweight: bw.value ? +bw.value : null, notes: notes.value,
    });
    loadWorkouts();
  }
  [nameInput, dateInput, bw, notes].forEach((i) => i.addEventListener("change", saveMeta));

  editor.append(el("div", { class: "row-between" },
    el("h3", {}, "Treenin muokkaus"),
    el("button", { class: "small", onclick: () => { editor.classList.add("hidden"); } }, "Sulje")));
  editor.append(el("div", { class: "grid" },
    el("label", {}, "Nimi", nameInput), el("label", {}, "Päivä", dateInput),
    el("label", {}, "Kehon paino", bw), el("label", {}, "Huomiot", notes)));

  for (const we of w.exercises) editor.append(renderWorkoutExercise(id, we));

  // Liikkeen lisäys
  const addSel = el("select", {});
  exercisesCache.forEach((ex) => addSel.append(el("option", { value: ex.id }, ex.name)));
  editor.append(el("div", { class: "exercise-block btn-row" }, addSel,
    el("button", { class: "small primary", onclick: async () => {
      if (!exercisesCache.length) return alert("Lisää ensin liikkeitä.");
      await api.post(`/api/workouts/${id}/exercises`, {
        exercise_id: +addSel.value, order_index: w.exercises.length,
        sets: [{ set_index: 0, reps: 5, weight: 0 }],
      });
      openWorkoutEditor(id);
    } }, "+ Lisää liike treeniin")));
}

function renderWorkoutExercise(workoutId, we) {
  const block = el("div", { class: "exercise-block" });
  block.append(el("div", { class: "row-between" },
    el("strong", {}, we.exercise.name),
    el("button", { class: "small danger", onclick: async () => {
      await api.del(`/api/workouts/exercises/${we.id}`); openWorkoutEditor(workoutId);
    } }, "Poista liike")));

  const table = el("table", {});
  table.append(el("tr", {},
    el("th", {}, "Sarja"), el("th", {}, "Toistot"), el("th", {}, "Paino"),
    el("th", {}, "RIR"), el("th", {}, "OK"), el("th", {}, "Huomio"), el("th", {}, "")));

  we.sets.forEach((set) => {
    const reps = el("input", { type: "number", value: set.reps });
    const weight = el("input", { type: "number", step: "0.5", value: set.weight });
    const rir = el("input", { type: "number", step: "0.5", value: set.rir ?? "" });
    const done = el("input", { type: "checkbox" });
    done.checked = set.completed;
    const note = el("input", { class: "notes", value: set.notes || "" });
    async function saveSet() {
      await api.patch(`/api/workouts/sets/${set.id}`, {
        set_index: set.set_index, reps: +reps.value, weight: +weight.value,
        rir: rir.value ? +rir.value : null, completed: done.checked, notes: note.value || null,
      });
      loadWorkouts();
    }
    [reps, weight, rir, done, note].forEach((i) => i.addEventListener("change", saveSet));
    table.append(el("tr", {},
      el("td", {}, String(set.set_index + 1)),
      el("td", {}, reps), el("td", {}, weight), el("td", {}, rir),
      el("td", {}, done), el("td", {}, note),
      el("td", {}, el("button", { class: "small danger", onclick: async () => {
        await api.del(`/api/workouts/sets/${set.id}`); openWorkoutEditor(workoutId);
      } }, "x"))));
  });
  block.append(table);
  block.append(el("button", { class: "small", onclick: async () => {
    const last = we.sets[we.sets.length - 1];
    await api.post(`/api/workouts/exercises/${we.id}/sets`, {
      set_index: we.sets.length, reps: last ? last.reps : 5, weight: last ? last.weight : 0,
    });
    openWorkoutEditor(workoutId);
  } }, "+ Sarja"));
  return block;
}

// =================== PAINOLASKURI ===================
document.getElementById("calc-btn").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  try {
    const r = await api.post("/api/engine/convert-scheme", {
      current_weight: +v("c-weight"), current_sets: +v("c-sets"), current_reps: +v("c-reps"),
      current_rir: v("c-rir") ? +v("c-rir") : null,
      target_sets: +v("c-tsets"), target_reps: +v("c-treps"),
      target_rir: v("c-trir") ? +v("c-trir") : null, increment: +v("c-inc"),
    });
    document.getElementById("calc-result").innerHTML = "";
    document.getElementById("calc-result").append(
      el("div", { class: "result-box" },
        el("div", {}, `${r.from_scheme} → ${r.to_scheme}`),
        el("div", { class: "big" }, `${r.suggested_weight_rounded} kg`),
        el("div", { class: "muted" }, r.note)));
  } catch (e) { alert("Virhe: " + e.message); }
});

// =================== CANVAS-GRAAFI (ei riippuvuuksia) ===================
const CHART_COLORS = ["#4f8cff", "#34d399", "#f59e0b", "#ef4444", "#a78bfa", "#ec4899", "#22d3ee"];

function drawLineChart(canvas, series, opts = {}) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const pad = { l: 50, r: 16, t: 16, b: 36 };
  const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;

  const allPts = series.flatMap((s) => s.points);
  if (!allPts.length) {
    ctx.fillStyle = "#9aa3b2"; ctx.font = "14px system-ui";
    ctx.fillText("Ei dataa vielä — kirjaa treenejä nähdäksesi kehityksen.", pad.l, H / 2);
    return;
  }
  const xs = allPts.map((p) => p.x), ys = allPts.map((p) => p.y);
  let minX = Math.min(...xs), maxX = Math.max(...xs);
  let minY = Math.min(...ys), maxY = Math.max(...ys);
  if (minX === maxX) maxX = minX + 1;
  // Hieman ilmaa ylä/alarajaan
  const yPad = (maxY - minY) * 0.1 || 5;
  minY = Math.max(0, minY - yPad); maxY = maxY + yPad;

  const xPix = (x) => pad.l + ((x - minX) / (maxX - minX)) * plotW;
  const yPix = (y) => pad.t + plotH - ((y - minY) / (maxY - minY)) * plotH;

  // Ruudukko + y-akselin arvot
  ctx.strokeStyle = "#2e333f"; ctx.fillStyle = "#9aa3b2"; ctx.font = "11px system-ui";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (plotH / 4) * i;
    const val = maxY - ((maxY - minY) / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillText(Math.round(val) + (opts.unit || ""), 6, y + 3);
  }
  // X-akselin päivämäärät (alku ja loppu)
  const fmt = (ms) => new Date(ms).toLocaleDateString("fi-FI", { day: "numeric", month: "numeric", year: "2-digit" });
  ctx.fillText(fmt(minX), pad.l, H - 12);
  ctx.textAlign = "right"; ctx.fillText(fmt(maxX), W - pad.r, H - 12); ctx.textAlign = "left";

  series.forEach((s, idx) => {
    const color = s.color || CHART_COLORS[idx % CHART_COLORS.length];
    const pts = [...s.points].sort((a, b) => a.x - b.x);
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2;
    ctx.beginPath();
    pts.forEach((p, i) => { const X = xPix(p.x), Y = yPix(p.y); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    ctx.stroke();
    pts.forEach((p) => { ctx.beginPath(); ctx.arc(xPix(p.x), yPix(p.y), 3, 0, Math.PI * 2); ctx.fill(); });
  });
}

// =================== YLEISNÄKYMÄ ===================
async function loadOverview() {
  const o = await api.get("/api/stats/overview");
  const cards = document.getElementById("overview-cards");
  cards.innerHTML = "";
  const card = (label, val) => el("div", { class: "card" },
    el("div", { class: "muted" }, label), el("div", { class: "big" }, String(val)));
  cards.append(card("Treenejä", o.total_workouts), card("Liikkeitä", o.total_exercises),
    card("Ohjelmia", o.total_programs));

  const recs = await api.get("/api/stats/records?main_only=true");
  const rdiv = document.getElementById("overview-records");
  rdiv.innerHTML = "";
  if (!recs.length) rdiv.append(el("p", { class: "muted" }, "Ei vielä dataa pääliikkeistä."));
  else rdiv.append(recordsTable(recs));

  const recent = document.getElementById("overview-recent");
  recent.innerHTML = "";
  if (!o.recent_workouts.length) recent.append(el("p", { class: "muted" }, "Ei treenejä."));
  for (const w of o.recent_workouts) {
    recent.append(el("div", { class: "muted" }, `${w.date} — ${w.name || "Treeni"} (${w.exercises} liikettä)`));
  }
}

function recordsTable(recs) {
  const t = el("table", {});
  t.append(el("tr", {}, el("th", {}, "Liike"), el("th", {}, "Nyt 1RM"),
    el("th", {}, "Paras sarja"), el("th", {}, "Ennätys"), el("th", {}, "Treenattu")));
  recs.forEach((r) => {
    const bs = r.current_best_set;
    t.append(el("tr", {},
      el("td", {}, r.exercise_name + (r.is_main_lift ? " ⭐" : "")),
      el("td", {}, `${r.current_1rm} kg`),
      el("td", {}, bs ? `${bs.weight}×${bs.reps}${bs.rir != null ? ` (RIR ${bs.rir})` : ""}` : "—"),
      el("td", {}, `${r.best_ever_1rm} kg`),
      el("td", {}, r.last_trained || "—")));
  });
  return t;
}

// =================== KEHITYS (graafit) ===================
let selectedProgress = new Set();

async function loadProgress() {
  renderProgressChips();
  await loadSports();
  await loadRecordsTable();
}

function renderProgressChips() {
  const search = document.getElementById("progress-search").value.toLowerCase();
  const chips = document.getElementById("progress-chips");
  chips.innerHTML = "";
  exercisesCache
    .filter((ex) => ex.name.toLowerCase().includes(search))
    .slice(0, 30)
    .forEach((ex) => {
      const active = selectedProgress.has(ex.id);
      chips.append(el("button", { class: "small" + (active ? " primary" : ""), onclick: () => {
        active ? selectedProgress.delete(ex.id) : selectedProgress.add(ex.id);
        renderProgressChips(); drawProgressChart();
      } }, ex.name));
    });
}

async function drawProgressChart() {
  const series = [];
  const legend = document.getElementById("progress-legend");
  legend.innerHTML = "";
  let idx = 0;
  for (const id of selectedProgress) {
    const h = await api.get(`/api/stats/exercises/${id}/history`);
    const color = CHART_COLORS[idx % CHART_COLORS.length];
    series.push({
      points: h.points.map((p) => ({ x: new Date(p.date).getTime(), y: p.estimated_1rm })),
      color,
    });
    legend.append(el("span", { class: "tag", style: `color:${color};border-color:${color}` }, h.exercise_name));
    idx++;
  }
  drawLineChart(document.getElementById("progress-chart"), series, { unit: "kg" });
}

document.getElementById("progress-search").addEventListener("input", renderProgressChips);

// ---- Lajitotal ----
async function loadSports() {
  const sports = await api.get("/api/stats/sports");
  const sel = document.getElementById("sport-select");
  const prev = sel.value;
  sel.innerHTML = "";
  if (!sports.length) {
    sel.append(el("option", { value: "" }, "(ei lajeja — merkitse pääliikkeille laji)"));
    document.getElementById("total-summary").innerHTML = "";
    drawLineChart(document.getElementById("total-chart"), []);
    return;
  }
  sports.forEach((s) => sel.append(el("option", { value: s }, s)));
  if (sports.includes(prev)) sel.value = prev;
  await drawTotal();
}

document.getElementById("sport-select").addEventListener("change", drawTotal);

async function drawTotal() {
  const sport = document.getElementById("sport-select").value;
  if (!sport) return;
  const t = await api.get(`/api/stats/total?sport=${encodeURIComponent(sport)}`);
  const sum = document.getElementById("total-summary");
  sum.innerHTML = "";
  sum.append(el("div", { class: "result-box" },
    el("div", {}, `${sport} — tämänhetkinen total`),
    el("div", { class: "big" }, `${t.total_mid} kg`),
    el("div", { class: "muted" }, `Haarukka ${t.total_low}–${t.total_high} kg`),
    el("div", { class: "muted" }, t.per_lift.map((l) => `${l.exercise_name}: ${l.current_1rm}kg`).join(" · "))));
  drawLineChart(document.getElementById("total-chart"),
    [{ points: t.timeline.map((p) => ({ x: new Date(p.date).getTime(), y: p.total })) }], { unit: "kg" });
}

// ---- Ennätystaulukko ----
async function loadRecordsTable() {
  const recs = await api.get("/api/stats/records");
  window._allRecords = recs;
  renderRecordsTable();
}
function renderRecordsTable() {
  const search = (document.getElementById("records-search").value || "").toLowerCase();
  const div = document.getElementById("records-table");
  div.innerHTML = "";
  const recs = (window._allRecords || []).filter((r) => r.exercise_name.toLowerCase().includes(search));
  if (!recs.length) div.append(el("p", { class: "muted" }, "Ei dataa."));
  else div.append(recordsTable(recs));
}
document.getElementById("records-search").addEventListener("input", renderRecordsTable);

// =================== VALMIIT POHJAT ===================
document.getElementById("template-btn").addEventListener("click", async () => {
  if (!exercisesCache.length) return alert("Lisää ensin liikkeitä.");
  const panel = document.getElementById("template-panel");
  panel.classList.toggle("hidden");
  if (panel.classList.contains("hidden")) return;
  panel.innerHTML = "";
  const templates = await api.get("/api/templates");
  const tSel = el("select", {});
  templates.forEach((t) => tSel.append(el("option", { value: t.id }, t.name)));
  const guidance = el("div", { class: "muted" });
  const updateGuidance = () => {
    const t = templates.find((x) => x.id === tSel.value);
    guidance.textContent = t ? `${t.rep_scheme} @ ${t.percent_scheme}% — ${t.guidance}` : "";
  };
  tSel.addEventListener("change", updateGuidance);
  // Pääliikkeiden valinta (checkboxit)
  const liftBoxes = exercisesCache.map((ex) => {
    const cb = el("input", { type: "checkbox", value: ex.id });
    if (ex.is_main_lift) cb.checked = true;
    return { ex, cb };
  });
  const liftList = el("div", { class: "btn-row" });
  liftBoxes.forEach(({ ex, cb }) => liftList.append(el("label", { class: "tag" }, cb, " " + ex.name)));
  panel.append(
    el("label", {}, "Pohja", tSel), guidance,
    el("div", { class: "muted" }, "Valitse pääliikkeet joille jakso rakennetaan:"), liftList,
    el("div", { class: "btn-row" },
      el("button", { class: "success", onclick: async () => {
        const ids = liftBoxes.filter((b) => b.cb.checked).map((b) => +b.cb.value);
        if (!ids.length) return alert("Valitse vähintään yksi liike.");
        await api.post("/api/templates/build", { template_id: tSel.value, exercise_ids: ids });
        panel.classList.add("hidden"); loadPrograms();
      } }, "Luo ohjelma pohjasta"),
      el("button", { onclick: () => panel.classList.add("hidden") }, "Peruuta")));
  updateGuidance();
});

// ---------- Välilehtien laiskat lataukset ----------
TAB_LOADERS.overview = loadOverview;
TAB_LOADERS.progress = loadProgress;

// ---------- Käynnistys ----------
(async function init() {
  await loadExercises();
  await loadPrograms();
  await loadWorkouts();
  await loadOverview();
})();
