// Treeni-ty-kalu — selainkäyttöliittymä (vanilla JS, ei build-vaihetta).

// Profiililukon token (jos lukko käytössä). Tallennetaan localStorageen, jotta
// kirjautuminen säilyy sovelluksen avausten välillä.
function authToken() { return localStorage.getItem("authToken") || null; }
function setAuthToken(t) {
  if (t) localStorage.setItem("authToken", t); else localStorage.removeItem("authToken");
}

const api = {
  async req(method, path, body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    const tok = authToken();
    if (tok) opts.headers["Authorization"] = "Bearer " + tok;
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      // Token puuttuu tai vanhentui -> takaisin lukitusnäyttöön.
      setAuthToken(null);
      if (typeof showLockScreen === "function") showLockScreen();
      throw new Error("Kirjautuminen vaaditaan.");
    }
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
let currentProfileId = null;
let profilesCache = [];
const expandedExercises = new Set(); // tehdyt liikkeet jotka pidetään auki muokkausta varten

// Arvioitu 1RM (Epley, varasto huomioiden) — sama kaava kuin backendissä.
function estimate1rm(weight, reps, rir) {
  const eff = reps + (rir != null ? rir : 0);
  if (weight <= 0 || reps <= 0) return 0;
  if (eff <= 1) return weight;
  return Math.round(weight * (1 + eff / 30) * 10) / 10;
}
function bestSetOf(we) {
  let best = null;
  we.sets.forEach((s) => {
    if (!s.completed || s.reps <= 0 || s.weight <= 0) return;
    const e = estimate1rm(s.weight, s.reps, s.rir);
    if (!best || e > best.e) best = { e, weight: s.weight, reps: s.reps };
  });
  return best;
}

// Lisää profile_id-parametri polkuun (skooppaa datan aktiiviseen profiiliin).
function pq(path) {
  if (currentProfileId == null) return path;
  return path + (path.includes("?") ? "&" : "?") + "profile_id=" + currentProfileId;
}

// Rakentaa <select>:n liikkeistä kategorioittain ryhmiteltynä (optgroup).
function exerciseSelect(onchange) {
  const sel = document.createElement("select");
  if (onchange) sel.addEventListener("change", onchange);
  const byCat = {};
  exercisesCache.forEach((ex) => (byCat[ex.category || "muu"] = byCat[ex.category || "muu"] || []).push(ex));
  Object.keys(byCat).sort().forEach((cat) => {
    const og = document.createElement("optgroup");
    og.label = cat;
    byCat[cat].forEach((ex) => {
      const o = document.createElement("option");
      o.value = ex.id;
      o.textContent = ex.name + (ex.equipment ? ` (${ex.equipment})` : "");
      og.append(o);
    });
    sel.append(og);
  });
  return sel;
}

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
  // Ryhmittele kategorioittain
  const byCat = {};
  exercisesCache.forEach((ex) => (byCat[ex.category || "muu"] = byCat[ex.category || "muu"] || []).push(ex));
  for (const cat of Object.keys(byCat).sort()) {
    list.append(el("h3", { style: "text-transform:capitalize;margin-bottom:4px" }, cat));
    for (const ex of byCat[cat]) {
      const tags = [];
      if (ex.is_main_lift) tags.push(el("span", { class: "tag main" }, "pääliike"));
      if (ex.equipment) tags.push(el("span", { class: "tag" }, ex.equipment));
      if (ex.per_hand) tags.push(el("span", { class: "tag", title: "Paino kirjataan per käsipaino, ei yhteispainona" }, "per käsi"));
      tags.push(el("span", { class: "tag" }, `${ex.default_sets}×${ex.default_reps}`));
      if (ex.sport) tags.push(el("span", { class: "tag" }, ex.sport));
      const item = el("div", { class: "item" },
        el("div", { class: "row-between" },
          el("div", {}, el("strong", {}, ex.name),
            ex.muscle_group ? el("span", { class: "muted" }, " · " + ex.muscle_group) : ""),
          el("div", { class: "btn-row" },
            ex.description ? el("button", { class: "small", onclick: (e) => {
              const d = e.target.closest(".item").querySelector(".ex-desc");
              d.style.display = d.style.display === "none" ? "" : "none";
            } }, "Ohje") : "",
            el("button", { class: "small danger", onclick: async () => {
              if (confirm(`Poista liike "${ex.name}"?`)) { await api.del(`/api/exercises/${ex.id}`); loadExercises(); }
            } }, "Poista"))),
        el("div", { class: "btn-row" }, ...tags));
      if (ex.description) item.append(el("div", { class: "ex-desc muted", style: "display:none;margin-top:6px" }, ex.description));
      list.append(item);
    }
  }
}

document.getElementById("new-exercise-btn").addEventListener("click", () => {
  const form = document.getElementById("exercise-form");
  form.classList.remove("hidden");
  form.innerHTML = "";
  const name = el("input", { placeholder: "Esim. Kyykky" });
  const category = el("input", { list: "cat-list", placeholder: "esim. jalat" });
  const catList = el("datalist", { id: "cat-list" });
  ["rinta", "selkä", "jalat", "olkapäät", "hauis", "ojentajat", "vatsa", "pohkeet", "olympia"]
    .forEach((c) => catList.append(el("option", {}, c)));
  const muscle = el("input", { placeholder: "Lihasryhmä" });
  const equip = el("select", {}, ...["", "tanko", "käsipainot", "talja", "kone", "keho", "kahvakuula", "muu"]
    .map((e) => el("option", { value: e }, e || "(väline)")));
  const dsets = el("input", { type: "number", value: 3 });
  const dreps = el("input", { type: "number", value: 10 });
  const sport = el("input", { placeholder: "Laji (esim. voimanosto)" });
  const main = el("input", { type: "checkbox" });
  form.append(
    el("div", { class: "grid" },
      el("label", {}, "Nimi", name, catList),
      el("label", {}, "Kategoria", category),
      el("label", {}, "Lihasryhmä", muscle),
      el("label", {}, "Väline", equip),
      el("label", {}, "Oletussarjat", dsets),
      el("label", {}, "Oletustoistot", dreps),
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
            equipment: equip.value || null,
            default_sets: +dsets.value || 3,
            default_reps: +dreps.value || 10,
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
  let programs = await api.get(pq("/api/programs"));
  // Aktiivinen ohjelma ensin
  programs = programs.slice().sort((a, b) => (b.is_active ? 1 : 0) - (a.is_active ? 1 : 0));
  const list = document.getElementById("program-list");
  list.innerHTML = "";
  if (!programs.length) {
    list.append(el("p", { class: "muted" }, "Ei ohjelmia vielä."));
  }
  for (const p of programs) {
    const item = el("div", { class: "item" + (p.is_active ? " ex-done" : "") });
    item.append(el("div", { class: "row-between" },
      el("div", { class: "btn-row", style: "align-items:center" },
        el("strong", {}, p.name),
        p.is_active ? el("span", { class: "tag status-done" }, "Aktiivinen") : ""),
      el("div", { class: "btn-row" },
        p.is_active
          ? el("button", { class: "small", onclick: async () => { await api.post(`/api/programs/${p.id}/finish`); loadPrograms(); loadWorkouts(); } }, "Päätä")
          : el("button", { class: "small primary", title: "Vie ohjelman treenipäivät Treenit-välilehdelle", onclick: async () => {
              await api.post(`/api/programs/${p.id}/activate`); loadPrograms(); loadWorkouts();
              alert("Ohjelma aktivoitu. Treenipäivät löytyvät nyt Treenit-välilehdeltä.");
            } }, "Aktivoi"),
        el("button", { class: "small", onclick: () => openProgramEditor(p.id) }, "Muokkaa"),
        el("button", { class: "small danger", onclick: async () => {
          if (confirm(`Poista ohjelma "${p.name}"?`)) { await api.del(`/api/programs/${p.id}`); loadPrograms(); }
        } }, "Poista"))
    ));
    const meta = [p.schedule_type === "cycle" ? "Sykli" : "Viikko"];
    if (p.goal) meta.push(p.goal);
    item.append(el("div", { class: "muted" }, meta.join(" · ")));
    // Yhteenveto: kesto + montako treeniä tehty/skipattu
    const sum = await api.get(`/api/programs/${p.id}/summary`);
    const sparts = [];
    if (sum.start_date) sparts.push(`alkoi ${sum.start_date}`);
    if (sum.end_date) sparts.push(`päättyi ${sum.end_date}`);
    if (sum.duration_days != null) sparts.push(`${sum.duration_days} pv`);
    sparts.push(`${sum.workouts_completed} treeniä tehty`);
    if (sum.workouts_skipped) sparts.push(`${sum.workouts_skipped} skipattu`);
    if (sum.workouts_planned_open) sparts.push(`${sum.workouts_planned_open} kesken`);
    item.append(el("div", { class: "muted" }, sparts.join(" · ")));
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

// Muokkaa olemassa olevaa ohjelmaa jälkikäteen: lisää/poista päiviä ja
// liikkeitä, muokkaa sarjoja/toistoja/painoja. Muutokset tallentuvat heti
// (granulaariset API-kutsut), joten päivien id:t säilyvät myös aktiivisessa
// ohjelmassa eivätkä jo siirretyt treenit katoa.
async function openProgramEditor(programId) {
  if (!exercisesCache.length) exercisesCache = await api.get("/api/exercises");
  const editor = document.getElementById("program-editor");

  async function render() {
    const p = await api.get(`/api/programs/${programId}`);
    editor.classList.remove("hidden");
    editor.innerHTML = "";
    editor.scrollIntoView({ behavior: "smooth", block: "nearest" });

    const name = el("input", { value: p.name, placeholder: "Ohjelman nimi" });
    const goal = el("input", { value: p.goal || "", placeholder: "Tavoite" });
    const autoProg = el("input", { type: "checkbox" });
    autoProg.checked = !!p.auto_progress;
    const saveHead = async () => { await api.patch(`/api/programs/${programId}`, { name: name.value.trim() || p.name, goal: goal.value.trim() || null, auto_progress: autoProg.checked }); };
    name.addEventListener("change", saveHead);
    goal.addEventListener("change", saveHead);
    autoProg.addEventListener("change", saveHead);

    editor.append(
      el("div", { class: "row-between" }, el("h3", { style: "margin:0" }, "Muokkaa ohjelmaa"),
        el("button", { class: "small success", onclick: () => { editor.classList.add("hidden"); loadPrograms(); } }, "Valmis")),
      el("div", { class: "grid" }, el("label", {}, "Nimi", name), el("label", {}, "Tavoite", goal)),
      el("label", { class: "btn-row", style: "align-items:center;gap:8px;margin-top:6px",
        title: "Kun päällä: uutta treeniä ohjelmasta luotaessa nostetaan tavoitepainoa yksi askel jos edellinen kerta meni täysillä (tuplaprogressio)." },
        autoProg, el("span", {}, "Automaattinen progressio (nosta painoa kun edellinen meni täysillä)")));

    for (const day of p.days) {
      const block = el("div", { class: "day-block " + (day.day_type === "rest" ? "rest" : "") });
      const labelInput = el("input", { value: day.label || "", placeholder: "Päivän nimi" });
      const typeSel = el("select", {}, el("option", { value: "train" }, "Treenipäivä"), el("option", { value: "rest" }, "Lepopäivä"));
      typeSel.value = day.day_type;
      const saveDay = async () => { await api.patch(`/api/programs/days/${day.id}`, { label: labelInput.value || null, day_type: typeSel.value }); render(); };
      labelInput.addEventListener("change", saveDay);
      typeSel.addEventListener("change", saveDay);
      block.append(el("div", { class: "btn-row" }, labelInput, typeSel,
        el("button", { class: "small danger", onclick: async () => {
          if (confirm("Poista tämä päivä?")) { await api.del(`/api/programs/days/${day.id}`); render(); }
        } }, "Poista päivä")));

      if (day.day_type === "train") {
        for (const pe of day.exercises) {
          const sel = exerciseSelect();
          sel.value = pe.exercise_id;
          const sets = el("input", { type: "number", value: pe.target_sets });
          const reps = el("input", { type: "number", value: pe.target_reps });
          const wt = el("input", { type: "number", step: "0.5", value: pe.target_weight ?? "" });
          const rest = el("input", { type: "number", value: pe.rest_seconds ?? "" });
          const scheme = el("input", { value: pe.rep_scheme ?? "", placeholder: "12,10,8" });
          const savePe = async () => {
            await api.patch(`/api/programs/exercises/${pe.id}`, {
              exercise_id: +sel.value, target_sets: +sets.value || 1, target_reps: +reps.value || 1,
              target_weight: wt.value ? +wt.value : null, rest_seconds: rest.value ? +rest.value : null,
              rep_scheme: scheme.value || null });
          };
          [sel, sets, reps, wt, rest, scheme].forEach((i) => i.addEventListener("change", savePe));
          block.append(el("div", { class: "btn-row" }, sel,
            el("label", {}, "sarjat", sets), el("label", {}, "toistot", reps),
            el("label", {}, "kg", wt), el("label", {}, "palautus s", rest),
            el("label", {}, "malli", scheme),
            el("button", { class: "small danger", onclick: async () => { await api.del(`/api/programs/exercises/${pe.id}`); render(); } }, "x")));
        }
        block.append(el("button", { class: "small", onclick: async () => {
          const ex0 = exercisesCache[0];
          await api.post(`/api/programs/days/${day.id}/exercises`, {
            exercise_id: ex0.id, order_index: day.exercises.length,
            target_sets: ex0.default_sets || 3, target_reps: ex0.default_reps || 10 });
          render();
        } }, "+ Liike"));
      }
      editor.append(block);
    }

    editor.append(el("div", { class: "btn-row" },
      el("button", { class: "small", onclick: async () => {
        await api.post(`/api/programs/${programId}/days`, { order_index: p.days.length, day_type: "train", label: "", exercises: [] }); render();
      } }, "+ Treenipäivä"),
      el("button", { class: "small", onclick: async () => {
        await api.post(`/api/programs/${programId}/days`, { order_index: p.days.length, day_type: "rest", label: "Lepo", exercises: [] }); render();
      } }, "+ Lepopäivä")));
  }
  await render();
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
          const sel = exerciseSelect((e) => (pe.exercise_id = +e.target.value));
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
          const ex0 = exercisesCache[0];
          day.exercises.push({ exercise_id: ex0.id, order_index: day.exercises.length,
            target_sets: ex0.default_sets || 3, target_reps: ex0.default_reps || 10, target_weight: null, rest_seconds: null });
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
          profile_id: currentProfileId,
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
function renderWorkoutItem(w, opts = {}) {
  const total = w.exercises.reduce((sum, we) => {
    let v = we.sets.reduce((s, set) => s + (set.completed ? set.reps * set.weight : 0), 0);
    if (we.missed_reps) {
      const topW = Math.max(0, ...we.sets.filter((st) => st.completed).map((st) => st.weight));
      v = Math.max(0, v - we.missed_reps * topW);
    }
    return sum + v;
  }, 0);
  const statusInfo = {
    planned: ["Suunniteltu", "status-planned"],
    completed: ["Suoritettu", "status-done"],
    skipped: ["Skipattu", "status-skip"],
  }[w.status] || ["", ""];
  const feelEmoji = { positive: "😀", neutral: "😐", negative: "😟" }[w.feeling] || "";
  return el("div", { class: "item" + (opts.active ? " ex-done" : "") },
    el("div", { class: "row-between" },
      el("div", { class: "btn-row", style: "align-items:center" },
        el("strong", {}, `${w.session_date} — ${w.name || "Treeni"}`),
        el("span", { class: "tag " + statusInfo[1] }, statusInfo[0]),
        feelEmoji ? el("span", { title: w.feeling_note || "" }, feelEmoji) : ""),
      el("div", { class: "btn-row" },
        el("button", { class: "small" + (opts.active ? " primary" : ""), onclick: () => openWorkoutEditor(w.id) }, opts.active ? "Jatka" : "Avaa"),
        el("button", { class: "small danger", onclick: async () => {
          if (confirm("Poista treeni?")) { await api.del(`/api/workouts/${w.id}`); loadWorkouts(); }
        } }, "Poista"))),
    el("div", { class: "muted" }, `${w.exercises.length} liikettä · kokonaiskuorma ${Math.round(total)} kg` +
      (w.duration_min ? ` · ${w.duration_min} min` : "") + (w.kcal_burned ? ` · ${Math.round(w.kcal_burned)} kcal` : ""))
  );
}

// Arvioi treenin kaloripoltto kun sitä ei ole merkitty. Käyttää ensisijaisesti
// omaa kcal/min-historiaa (aiemmat merkinnät), muuten MET-arviota painosta ja
// siirretystä raudasta.
let _kcalPerMinCache = null;
function estimateWorkoutBurn(w) {
  const dur = w.duration_min;
  if (!dur) return null;
  const prof = profilesCache.find((p) => p.id === currentProfileId);
  const bw = w.bodyweight || (prof && prof.latest_bodyweight) || 80;
  let tonnage = 0;
  (w.exercises || []).forEach((we) => (we.sets || []).forEach((s) => { if (s.completed) tonnage += s.weight * s.reps; }));
  // Oma historia (aiemmat kcal-merkinnät): kcal/min
  if (_kcalPerMinCache != null) return Math.round(_kcalPerMinCache * dur);
  return Math.round(bw * 0.0875 * dur + tonnage * 0.0008);
}

// Laske käyttäjän oma kcal/min aiemmista merkinnöistä (treenin muokkausta varten)
async function refreshKcalPerMin() {
  try {
    const ws = await api.get(pq("/api/workouts"));
    const withBoth = ws.filter((w) => w.kcal_burned && w.duration_min);
    if (withBoth.length >= 2) {
      const rates = withBoth.map((w) => w.kcal_burned / w.duration_min);
      _kcalPerMinCache = rates.reduce((a, b) => a + b, 0) / rates.length;
    } else _kcalPerMinCache = null;
  } catch (e) { _kcalPerMinCache = null; }
}

// Treenin tuntuma -kysymys kuittauksen jälkeen: mukauttaa järjestelmää
// koettuun kuormaan (helppo -> uskalla nostaa; väsynyt toistuvasti -> kevennä).
// Kysymys muotoillaan sen mukaan menikö kaikki sarjat.
function askWorkoutFeeling(workoutId, w) {
  const allDone = (w.exercises || []).length > 0 &&
    w.exercises.every((we) => (we.sets || []).every((s) => s.completed) || we.done);
  const title = allDone ? "Kaikki sarjat menivät — miltä treeni tuntui?" : "Miltä treeni tuntui?";
  const overlay = el("div", { class: "pr-celebrate" });
  const pick = async (feeling, note) => {
    await api.patch(`/api/workouts/${workoutId}`, { feeling, feeling_note: note });
    overlay.remove(); loadWorkouts();
  };
  overlay.append(el("div", { class: "pr-card" },
    el("h3", { style: "margin:4px 0 10px" }, title),
    el("div", { class: "muted", style: "margin-bottom:10px" },
      "Tuntuma auttaa järjestelmää mukautumaan: helppo → ehdotetaan lisää, raskas toistuvasti → kevennystä."),
    el("div", { class: "btn-row", style: "justify-content:center;flex-wrap:wrap" },
      el("button", { class: "small success", onclick: () => pick("positive", "helppo") }, "💪 Helppo"),
      el("button", { class: "small", onclick: () => pick("neutral", "sopiva") }, "👍 Sopiva"),
      el("button", { class: "small", onclick: () => pick("negative", "raskas") }, "🥵 Raskas"),
      el("button", { class: "small", onclick: () => pick("negative", "väsynyt") }, "😮‍💨 Olin väsynyt"),
      el("button", { class: "small", onclick: () => overlay.remove() }, "Ohita"))));
  document.body.append(overlay);
}

// Liikkeen ongelman ilmoitus: kipu/vaikea/muu -> turvallinen automaattivaihto
function reportExerciseProblem(workoutId, we) {
  const overlay = el("div", { class: "pr-celebrate" });
  const noteInput = el("input", { placeholder: "Tarkennus (vapaaehtoinen), esim. polvi kipeä", style: "width:100%;margin:8px 0" });
  const send = async (reason) => {
    const q = `reason=${reason}` + (noteInput.value.trim() ? `&note=${encodeURIComponent(noteInput.value.trim())}` : "");
    let res;
    try { res = await api.post(`/api/workouts/exercises/${we.id}/report-problem?${q}`); }
    catch (e) { alert("Virhe: " + e.message); return; }
    overlay.innerHTML = "";
    const card = el("div", { class: "pr-card", style: "max-width:460px;text-align:left" });
    if (res.swapped && res.alternative) {
      const a = res.alternative;
      card.append(
        el("h3", { style: "margin:4px 0 8px" }, "Liike vaihdettu turvallisempaan"),
        el("div", { class: "result-box", style: "border-color:var(--accent-2)" },
          el("strong", {}, `${res.original} → ${a.exercise_name}`),
          el("div", { class: "muted", style: "margin-top:4px" },
            `Ehdotus: ${a.sets} × ${a.reps}` + (a.start_weight ? ` · aloita ~${a.start_weight} kg` : " · aloita kevyellä")),
          el("div", { class: "muted", style: "margin-top:4px" }, a.start_note)));
    } else {
      card.append(el("h3", { style: "margin:4px 0 8px" }, "Ongelma merkitty"));
    }
    card.append(el("div", { style: "margin-top:8px;color:var(--warn)" }, "⚠ " + res.safety));
    card.append(el("div", { class: "result-box", style: "margin-top:8px;border-color:var(--accent)" },
      "🩺 " + res.pt_note));
    card.append(el("button", { class: "primary", style: "margin-top:12px",
      onclick: () => { overlay.remove(); openWorkoutEditor(workoutId); } }, "Selvä"));
    overlay.append(card);
  };
  overlay.append(el("div", { class: "pr-card", style: "max-width:440px;text-align:left" },
    el("h3", { style: "margin:4px 0 6px" }, `Ongelma liikkeessä: ${we.exercise.name}`),
    el("div", { class: "muted", style: "margin-bottom:6px" },
      "Kerro mikä on vialla, niin vaihdamme turvallisempaan tai helpompaan liikkeeseen ja ehdotamme sopivat sarjat. " +
      "Muista: tämä ei korvaa personal trainerin tai fysioterapeutin arviota."),
    noteInput,
    el("div", { class: "btn-row", style: "flex-wrap:wrap" },
      el("button", { class: "small danger", onclick: () => send("kipu") }, "🤕 Kipua"),
      el("button", { class: "small", onclick: () => send("vaikea") }, "😖 Tuntuu vaikealta"),
      el("button", { class: "small", onclick: () => send("muu") }, "Muu syy"),
      el("button", { class: "small", onclick: () => overlay.remove() }, "Peruuta"))));
  document.body.append(overlay);
}

// Ennätysjuhla: banneri + kevyt konfetti kun treeni rikkoo aiemman parhaan
function celebratePR(lines) {
  const overlay = el("div", { class: "pr-celebrate" },
    el("div", { class: "pr-card" },
      el("div", { style: "font-size:2.4em" }, "🏆"),
      el("h3", { style: "margin:6px 0" }, "Uusi ennätys!"),
      ...lines.map((l) => el("div", { style: "margin:4px 0" }, l)),
      el("button", { class: "primary", style: "margin-top:10px", onclick: () => overlay.remove() }, "Hienoa!")));
  document.body.append(overlay);
  // Konfetti
  for (let i = 0; i < 60; i++) {
    const c = el("div", { class: "confetti" });
    c.style.left = Math.random() * 100 + "vw";
    c.style.background = CHART_COLORS[i % CHART_COLORS.length];
    c.style.animationDelay = (Math.random() * 0.6) + "s";
    overlay.append(c);
  }
  setTimeout(() => { if (overlay.isConnected) overlay.remove(); }, 8000);
}

// Palautusajastin: yksi widget, esiasetetut ajat + laskuri
let restTimerId = null;
function renderRestTimer() {
  const wrap = el("div", { class: "rest-timer btn-row", style: "align-items:center;margin:8px 0" });
  const display = el("span", { style: "font-weight:700;min-width:52px;font-size:1.1em" }, "–");
  let remaining = 0;
  function tick() {
    remaining--;
    const m = Math.floor(remaining / 60), s = remaining % 60;
    display.textContent = `${m}:${String(s).padStart(2, "0")}`;
    if (remaining <= 0) {
      clearInterval(restTimerId); restTimerId = null;
      display.textContent = "Valmis!";
      try { navigator.vibrate && navigator.vibrate([200, 100, 200]); } catch (e) {}
      wrap.classList.add("rest-done");
      setTimeout(() => wrap.classList.remove("rest-done"), 2000);
    }
  }
  function start(sec) {
    if (restTimerId) clearInterval(restTimerId);
    remaining = sec + 1; tick();
    restTimerId = setInterval(tick, 1000);
  }
  wrap.append(el("span", { class: "muted" }, "Palautus:"));
  [60, 90, 120, 180].forEach((sec) => wrap.append(
    el("button", { class: "small", onclick: () => start(sec) }, `${sec}s`)));
  wrap.append(display,
    el("button", { class: "small", onclick: () => { if (restTimerId) { clearInterval(restTimerId); restTimerId = null; } display.textContent = "–"; } }, "Stop"));
  return wrap;
}

async function loadWorkouts() {
  const workouts = await api.get(pq("/api/workouts"));
  const list = document.getElementById("workout-list");
  list.innerHTML = "";
  if (!workouts.length) { list.append(el("p", { class: "muted" }, "Ei treenejä vielä.")); return; }

  // Aktiiviset = suunnitellut (vielä tekemättä) ylös. Tehdyt/skipatut
  // supistetaan historiaksi alle.
  const active = workouts.filter((w) => w.status === "planned");
  const past = workouts.filter((w) => w.status !== "planned");

  if (active.length) {
    list.append(el("div", { class: "section-label" }, "Aktiiviset treenit"));
    for (const w of active) list.append(renderWorkoutItem(w, { active: true }));
  } else {
    list.append(el("p", { class: "muted" }, "Ei aktiivista treeniä. Aloita uusi tai aktivoi ohjelma."));
  }

  if (past.length) {
    const histWrap = el("div", { class: "hidden" });
    for (const w of past) histWrap.append(renderWorkoutItem(w));
    const toggle = el("button", { class: "small", onclick: () => {
      const open = !histWrap.classList.toggle("hidden");
      toggle.textContent = open ? `▾ Aiemmat treenit (${past.length})` : `▸ Aiemmat treenit (${past.length})`;
    } }, `▸ Aiemmat treenit (${past.length})`);
    list.append(el("div", { class: "history-block" }, toggle, histWrap));
  }
}

document.getElementById("new-workout-btn").addEventListener("click", async () => {
  const w = await api.post("/api/workouts", { name: "Vapaa treeni", profile_id: currentProfileId, exercises: [] });
  await loadWorkouts();
  openWorkoutEditor(w.id);
});

// Treenin jälkeinen valmennus per liike: vertailu, korotus tai painon lasku
async function renderWorkoutReview(id) {
  const box = document.getElementById("workout-review");
  if (!box) return;
  box.innerHTML = "";
  let data;
  try { data = await api.get(`/api/workouts/${id}/review`); } catch { return; }
  const rows = (data.exercises || []).filter((e) => e.reason || e.compare);
  if (!rows.length) return;

  const card = el("div", { class: "card review-card", style: "border-color:var(--accent)" });
  const progress = el("span", { class: "muted", style: "font-size:0.85rem" });
  card.append(el("div", { class: "row-between", style: "align-items:baseline" },
    el("h3", { style: "margin:0" }, "🎯 Seuraava kerta — vahvista painot"),
    progress));
  const list = el("div", {});
  const footer = el("div", {});
  card.append(list, footer);
  box.append(card);

  // Vain ne rivit joissa on valinta (korotus/lasku) vaativat päätöksen.
  let pending = 0, totalActions = 0;

  function updateProgress() {
    if (!totalActions) { progress.textContent = ""; return; }
    progress.textContent = `${totalActions - pending}/${totalActions} valittu`;
    if (pending === 0) finish();
  }

  function finish() {
    footer.innerHTML = "";
    const banner = el("div", { class: "review-complete" },
      el("strong", {}, "✓ Kaikki painot vahvistettu — treeni valmis!"),
      el("button", { class: "small", onclick: () => {
        document.getElementById("workout-editor").classList.add("hidden");
      } }, "Sulje treeni"));
    footer.append(banner);
    // Sulje treeni pehmeästi hetken kuluttua (käyttäjä ehtii nähdä kuittauksen).
    setTimeout(() => {
      const ed = document.getElementById("workout-editor");
      if (ed && document.body.contains(banner)) ed.classList.add("hidden");
    }, 1800);
  }

  rows.forEach((e) => {
    const actionable = (e.ask_increase || e.ask_reduce) && e.suggested_weight != null;
    const tone = e.ask_reduce ? "var(--danger)" : e.ask_increase ? "var(--accent-2)" : "var(--muted)";
    const item = el("div", { class: "item review-item", style: `border-left:3px solid ${tone}` });
    const head = el("div", { class: "row-between" },
      el("strong", {}, e.exercise_name),
      el("span", { class: "muted" }, `${e.top_weight} kg · ${e.reps_at_top.join(", ")}`));
    item.append(head);
    if (e.compare) item.append(el("div", { class: "muted", style: "margin-top:3px" }, "↔ " + e.compare));
    if (e.reason) item.append(el("div", { style: `margin-top:3px;color:${tone}` }, e.reason));

    // Rivi käsitelty -> supistuu yhden rivin kuittaukseksi ("häviää" listasta).
    function resolve(msg) {
      item.classList.add("done");
      item.innerHTML = "";
      item.append(el("div", { class: "row-between" },
        el("span", { style: "color:var(--muted)" }, e.exercise_name),
        el("span", { style: "color:var(--accent-2)" }, "✓ " + msg)));
      if (actionable) { pending--; updateProgress(); }
    }

    if (actionable) {
      totalActions++; pending++;
      const verb = e.ask_increase ? "Korota" : "Laske";
      const applyBtn = el("button", { class: "small " + (e.ask_increase ? "success" : "primary"),
        onclick: async () => { await setNext(e.suggested_weight); } },
        `${verb} → ${e.suggested_weight} kg`);
      // Oma paino: valitse itse mihin korotat/lasket (esitäyttö = ehdotus)
      const custom = el("input", { type: "number", step: "0.5", value: e.suggested_weight,
        style: "width:78px", title: "Valitse oma paino ensi kerraksi" });
      const customBtn = el("button", { class: "small",
        onclick: async () => {
          const w = parseFloat(custom.value);
          if (!(w > 0)) return;
          await setNext(w);
        } }, "Aseta oma");
      const keepBtn = el("button", { class: "small",
        onclick: () => resolve(`pidetään ${e.top_weight} kg`) }, "Pidä ennallaan");

      async function setNext(w) {
        if (e.can_apply) {
          try { await api.post(`/api/workouts/exercises/${e.workout_exercise_id}/apply-weight?weight=${w}`); }
          catch (err) { alert(err.message); return; }
          resolve(`ensi kerraksi ${w} kg`);
        } else {
          // Vapaa treeni: ei ohjelmaa johon tallentaa, mutta paino muistetaan
          // viime kerrasta -> kuitataan visuaalisesti.
          resolve(`ensi kerraksi ${w} kg (muistetaan viime kerrasta)`);
        }
      }

      item.append(el("div", { class: "btn-row", style: "margin-top:6px;align-items:center" },
        applyBtn,
        el("span", { class: "muted", style: "font-size:0.8rem" }, "tai"),
        custom, el("span", { class: "muted", style: "font-size:0.8rem" }, "kg"), customBtn,
        keepBtn));
    }
    list.append(item);
  });
  updateProgress();
}

async function openWorkoutEditor(id) {
  const w = await api.get(`/api/workouts/${id}`);
  await refreshKcalPerMin();
  const editor = document.getElementById("workout-editor");
  editor.classList.remove("hidden");
  editor.innerHTML = "";
  editor.scrollIntoView({ behavior: "smooth" });

  const nameInput = el("input", { value: w.name || "", placeholder: "Treenin nimi" });
  const dateInput = el("input", { type: "date", value: w.session_date });
  const bw = el("input", { type: "number", step: "0.1", value: w.bodyweight ?? "", placeholder: "kg" });
  const dur = el("input", { type: "number", value: w.duration_min ?? "", placeholder: "min" });
  const kcal = el("input", { type: "number", value: w.kcal_burned ?? "", placeholder: "kcal" });
  const feeling = el("select", {}, el("option", { value: "" }, "—"),
    el("option", { value: "positive" }, "😀 Hyvä olo"),
    el("option", { value: "neutral" }, "😐 Neutraali"),
    el("option", { value: "negative" }, "😟 Ongelma"));
  feeling.value = w.feeling || "";
  const feelingNote = el("input", { value: w.feeling_note || "", placeholder: "esim. kipu olkapäässä, hyvä veto" });
  const notes = el("input", { value: w.notes || "", placeholder: "Huomiot" });

  async function saveMeta() {
    await api.patch(`/api/workouts/${id}`, {
      name: nameInput.value, session_date: dateInput.value,
      bodyweight: bw.value ? +bw.value : null,
      duration_min: dur.value ? +dur.value : null,
      kcal_burned: kcal.value ? +kcal.value : null,
      feeling: feeling.value || null,
      feeling_note: feelingNote.value || null,
      notes: notes.value,
    });
    loadWorkouts();
  }
  [nameInput, dateInput, bw, dur, kcal, feeling, feelingNote, notes].forEach((i) => i.addEventListener("change", saveMeta));

  const statusLabel = { planned: "Suunniteltu", completed: "Suoritettu", skipped: "Skipattu" }[w.status] || w.status;
  editor.append(el("div", { class: "row-between" },
    el("h3", {}, "Treenin muokkaus"),
    el("div", { class: "btn-row" },
      el("span", { class: "tag" }, statusLabel),
      el("button", { class: "small success", onclick: async () => {
        const res = await api.post(`/api/workouts/${id}/complete`);
        if (res && res.new_prs && res.new_prs.length) {
          const lines = res.new_prs.map((p) => `🏆 ${p.exercise_name}: uusi ennätys ~${p.new_1rm} kg (aiempi ${p.previous_best}, +${p.improvement} kg)`);
          celebratePR(lines);
        }
        if (!w.feeling) askWorkoutFeeling(id, w);
        loadWorkouts(); openWorkoutEditor(id);
      } }, "✓ Kuittaa valmiiksi"),
      el("button", { class: "small", onclick: async () => {
        if (confirm("Skipataanko tämä treeni? Sitä ei lasketa kehitykseen.")) {
          await api.post(`/api/workouts/${id}/skip`); loadWorkouts(); openWorkoutEditor(id);
        }
      } }, "Skip"),
      el("button", { class: "small", onclick: () => { editor.classList.add("hidden"); } }, "Sulje"))));
  editor.append(el("div", { id: "workout-review" }));
  editor.append(el("div", { class: "grid" },
    el("label", {}, "Nimi", nameInput), el("label", {}, "Päivä", dateInput),
    el("label", {}, "Kehon paino", bw), el("label", {}, "Kesto (min)", dur),
    el("label", {}, "Poltetut kcal", kcal), el("label", {}, "Fiilis", feeling),
    el("label", {}, "Fiilis-huomio", feelingNote), el("label", {}, "Huomiot", notes)));

  // Kaloriarvio jos ei merkitty (kesto + siirretty rauta + kehon paino).
  // Nojaa aiempiin merkintöihin: käyttää oman kcal/min-historian jos on.
  if (!w.kcal_burned && w.duration_min) {
    const est = estimateWorkoutBurn(w);
    if (est) {
      const hint = el("div", { class: "muted", style: "margin:4px 0" },
        `Kaloriarvio (ei merkitty): ~${est} kcal `,
        el("button", { class: "small", onclick: async () => {
          kcal.value = est; await saveMeta();
        } }, "Käytä arviota"));
      editor.append(hint);
    }
  }

  // Palautusajastin (esiasetetut ajat)
  editor.append(renderRestTimer());

  // Edistymislaskuri (montako liikettä tehty)
  const doneCount = w.exercises.filter((we) => we.done).length;
  if (w.exercises.length) {
    editor.append(el("div", { class: "muted", style: "margin:6px 0 2px" },
      `Edistyminen: ${doneCount}/${w.exercises.length} liikettä tehty`));
  }

  for (const we of w.exercises) editor.append(renderWorkoutExercise(id, we));

  // Liikkeen lisäys (kategorioittain ryhmitelty valinta)
  const addSel = exerciseSelect();
  editor.append(el("div", { class: "exercise-block btn-row" }, addSel,
    el("button", { class: "small primary", onclick: async () => {
      if (!exercisesCache.length) return alert("Lisää ensin liikkeitä.");
      const exId = +addSel.value;
      const ex = exercisesCache.find((e) => e.id === exId) || {};
      // Liikearkisto: esitäytä edellisellä painolla; sarjat liikkeen oletuksista.
      const last = await api.get(pq(`/api/stats/exercises/${exId}/last`));
      const w0 = last.last ? last.last.weight : 0;
      const nSets = ex.default_sets || 3;
      const reps = ex.default_reps || (last.last ? last.last.reps : 10);
      const sets = Array.from({ length: nSets }, (_, i) => ({ set_index: i, reps, weight: w0 }));
      await api.post(`/api/workouts/${id}/exercises`, {
        exercise_id: exId, order_index: w.exercises.length, sets,
      });
      openWorkoutEditor(id);
    } }, "+ Lisää liike treeniin")));

  // Jo kuitatun treenin analyysi näkyviin automaattisesti
  if (w.status === "completed") renderWorkoutReview(id);
}

function renderWorkoutExercise(workoutId, we) {
  const best = bestSetOf(we);
  const oneRm = best ? `${best.e} kg (paras ${best.weight}×${best.reps})` : "—";

  // Tehdyt liikkeet näytetään tiiviisti (mobiilifokus) ellei avattu muokkaukseen.
  if (we.done && !expandedExercises.has(we.id)) {
    return el("div", { class: "exercise-block ex-done" },
      el("div", { class: "row-between" },
        el("div", { class: "btn-row", style: "align-items:center" },
          el("strong", {}, we.exercise.name),
          el("span", { class: "tag status-done" }, "✓ tehty"),
          el("span", { class: "muted" }, `1RM ~${oneRm}`)),
        el("button", { class: "small", onclick: () => { expandedExercises.add(we.id); openWorkoutEditor(workoutId); } }, "Muokkaa")));
  }

  const block = el("div", { class: "exercise-block" + (we.done ? " ex-done" : "") });
  block.append(el("div", { class: "row-between" },
    el("div", { class: "btn-row", style: "align-items:center" },
      el("strong", {}, we.exercise.name),
      we.done ? el("span", { class: "tag status-done" }, "OK") : "",
      we.swap_reason ? el("span", { class: "tag", style: "color:var(--warn);border-color:var(--warn)",
        title: `Vaihdettu ongelman takia (${we.swap_reason}). Alkuperäinen: ${we.swapped_from || "?"}` },
        `⚠ vaihdettu (${we.swap_reason})`) : ""),
    el("div", { class: "btn-row" },
      el("button", { class: "small", title: "Ilmoita ongelma (kipu/vaikea) — vaihdetaan turvallisempaan liikkeeseen",
        onclick: () => reportExerciseProblem(workoutId, we) }, "⚠ Ongelma"),
      el("button", { class: "small success", onclick: async () => {
        const markDone = !we.done;
        await api.patch(`/api/workouts/exercises/${we.id}`, { exercise_id: we.exercise_id, done: markDone });
        if (markDone) expandedExercises.delete(we.id);  // valmis -> pienennä
        openWorkoutEditor(workoutId);
      } }, we.done ? "Peru OK" : "✓ OK"),
      el("button", { class: "small danger", onclick: async () => {
        await api.del(`/api/workouts/exercises/${we.id}`); openWorkoutEditor(workoutId);
      } }, "Poista liike"))));

  const table = el("table", {});
  table.append(el("tr", {},
    el("th", {}, "Sarja"), el("th", {}, "Toistot"), el("th", {}, "Paino"),
    el("th", { title: "RIR = varasto: montako toistoa olisi jäänyt vielä jäljelle. 0 = täysillä, 2 = kaksi jäi. Kirjaa se → 1RM-arvio ja ennuste tarkentuvat huomattavasti." }, "RIR ⓘ"),
    el("th", {}, "OK"), el("th", {}, "Huomio"), el("th", {}, "")));

  we.sets.forEach((set) => {
    const reps = el("input", { type: "number", value: set.reps });
    const weight = el("input", { type: "number", step: "0.5", value: set.weight });
    const rir = el("input", { type: "number", step: "0.5", value: set.rir ?? "", placeholder: "varasto",
      title: "Montako toistoa olisi jäänyt jäljelle (0 = täysillä). Vapaaehtoinen mutta tarkentaa arviot." });
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

  // Arvioitu 1RM tästä treenistä (paras suoritettu sarja)
  block.append(el("div", { class: "muted", style: "margin-top:6px" }, `Arvioitu 1RM: ${oneRm}`));

  // Huom: erillistä "vajaaksi jäi" -kenttää ei ole — jos sarja jäi vajaaksi,
  // muuta vain sen sarjan toistoluku siihen mitä oikeasti teit. Toistot per
  // sarja näkyvät yllä, joten kehitysvolyymi lasketaan suoraan niistä.

  const suggestBox = el("span", { class: "muted" });
  block.append(el("div", { class: "btn-row", style: "align-items:center;margin-top:8px" },
    el("button", { class: "small", onclick: async () => {
      const last = we.sets[we.sets.length - 1];
      await api.post(`/api/workouts/exercises/${we.id}/sets`, {
        set_index: we.sets.length, reps: last ? last.reps : 5, weight: last ? last.weight : 0,
      });
      openWorkoutEditor(workoutId);
    } }, "+ Sarja"),
    el("button", { class: "small", onclick: async () => {
      const reps = we.sets[0] ? we.sets[0].reps : 5;
      const s = await api.get(pq(`/api/stats/exercises/${we.exercise_id}/suggest?target_reps=${reps}&increase=true`));
      suggestBox.textContent = s.suggested_weight != null ? s.note : "Ei aiempaa dataa.";
      if (s.suggested_weight != null && confirm(`${s.note}\n\nAsetetaanko ${s.suggested_weight} kg kaikkiin sarjoihin?`)) {
        for (const set of we.sets) {
          await api.patch(`/api/workouts/sets/${set.id}`, { set_index: set.set_index, reps: set.reps, weight: s.suggested_weight, rir: set.rir, completed: set.completed });
        }
        openWorkoutEditor(workoutId);
      }
    } }, "Ehdota seuraava paino"),
    suggestBox));
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
// Validoitu kategorinen paletti tummalle pinnalle (#1a1d24): jokainen väri
// erottuu myös värisokealle ja täyttää 3:1-kontrastin. Järjestys on kiinteä.
const CHART_COLORS = ["#3987e5", "#199e70", "#c98500", "#9085e9", "#e66767", "#d55181", "#d95926"];
const CHART_INK = { grid: "#232733", axis: "#3a4150", label: "#9aa3b2", faint: "#7a8290" };

// Yhteinen segmentoitu tasopalkki (voimatasot, kisataso, fysiikkataso):
// jokainen taso oma lohko, saavutetut värillisinä, nykyinen korostettuna,
// nimet palkin alla. titles[i] = hover-teksti per lohko.
function segLevelBar(levels, currentIdx, { shorts = null, titles = null } = {}) {
  const wrap = el("div", {});
  const seg = el("div", { class: "seg-bar" });
  levels.forEach((name, i) => {
    seg.append(el("div", {
      class: "seg" + (i <= currentIdx ? " on" : "") + (i === currentIdx ? " current" : ""),
      title: (titles && titles[i]) || name,
    }));
  });
  const labels = el("div", { class: "seg-labels" });
  levels.forEach((name, i) => {
    labels.append(el("span", {
      class: "seg-label" + (i === currentIdx ? " current" : "") + (i <= currentIdx ? " on" : ""),
      title: name,
    }, (shorts && shorts[i]) || name.split(" ")[0]));
  });
  wrap.append(seg, labels);
  return wrap;
}

// Siistit y-akselin askeleet (1/2/5 × 10^n) -> pyöreät luvut ruudukkoon
function niceTicks(min, max, count = 5) {
  const span = max - min || 1;
  const raw = span / Math.max(1, count - 1);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  const lo = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = lo; v <= max + step * 0.5; v += step) if (v >= min - step * 0.5) ticks.push(v);
  return ticks;
}

// Automaattiset päivämäärämerkit x-akselille (~4-6 kpl, siistit rajat)
function timeTicks(minX, maxX, mode) {
  const marks = [];
  const spanDays = (maxX - minX) / 864e5;
  if (mode === "week" || (!mode && spanDays <= 45)) {
    const stride = 7 * 864e5 * (spanDays > 200 ? 4 : spanDays > 60 ? 2 : 1);
    const d0 = new Date(minX); d0.setHours(0, 0, 0, 0);
    for (let t = d0.getTime(); t <= maxX; t += stride) if (t >= minX) marks.push(t);
  } else {
    const stepM = spanDays > 900 ? 6 : spanDays > 480 ? 3 : spanDays > 240 ? 2 : 1;
    const d = new Date(minX); d.setDate(1); d.setHours(0, 0, 0, 0);
    if (d.getTime() < minX) d.setMonth(d.getMonth() + 1);
    while (d.getTime() <= maxX) { marks.push(d.getTime()); d.setMonth(d.getMonth() + stepM); }
  }
  return marks;
}

function drawLineChart(canvas, series, opts = {}) {
  // Looginen koko attribuuteista; taustapuskuri skaalataan näytön tarkkuuteen
  // (HiDPI) jotta viivat ja teksti ovat teräviä.
  if (!canvas._logW) { canvas._logW = canvas.width; canvas._logH = canvas.height; }
  const W = canvas._logW, H = canvas._logH;
  const dpr = Math.min(3, window.devicePixelRatio || 1);
  if (canvas.width !== Math.round(W * dpr)) {
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const pad = { l: 52, r: 16, t: 14, b: 30 };
  const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;

  const allPts = series.flatMap((s) => s.points || []);
  if (!allPts.length) {
    ctx.fillStyle = CHART_INK.label; ctx.font = "13px system-ui"; ctx.textAlign = "center";
    ctx.fillText(opts.empty || "Ei dataa vielä — kirjaa, niin käyrä ilmestyy tähän.", W / 2, H / 2);
    ctx.textAlign = "left";
    canvas._hoverPts = [];
    return;
  }
  // Sisällytä ennustehaarukan (band) pisteet akseleihin
  const bandPts = series.flatMap((s) => s.band || []);
  const xs = allPts.map((p) => p.x).concat(bandPts.map((p) => p.x));
  const ys = allPts.map((p) => p.y).concat(bandPts.flatMap((p) => [p.low, p.high]));
  let minX = Math.min(...xs), maxX = Math.max(...xs);
  let minY = Math.min(...ys), maxY = Math.max(...ys);
  if (minX === maxX) maxX = minX + 864e5;
  const yPad = (maxY - minY) * 0.08 || 5;
  minY = Math.max(0, minY - yPad); maxY = maxY + yPad;

  const xPix = (x) => pad.l + ((x - minX) / (maxX - minX)) * plotW;
  const yPix = (y) => pad.t + plotH - ((y - minY) / (maxY - minY)) * plotH;

  // Y-ruudukko siistein askelin (recessiivinen hiusviiva) + arvot
  ctx.font = "11px system-ui"; ctx.lineWidth = 1;
  const yTicks = niceTicks(minY, maxY);
  minY = Math.min(minY, yTicks[0]); maxY = Math.max(maxY, yTicks[yTicks.length - 1]);
  const dec = (maxY - minY) < 8 ? 1 : 0;
  yTicks.forEach((v) => {
    const y = yPix(v);
    if (y < pad.t - 1 || y > pad.t + plotH + 1) return;
    ctx.strokeStyle = CHART_INK.grid;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillStyle = CHART_INK.label; ctx.textAlign = "right";
    ctx.fillText(v.toFixed(dec) + (opts.unit ? " " + opts.unit : ""), pad.l - 6, y + 3.5);
  });
  ctx.textAlign = "left";

  // X-akselin päivämäärämerkit: aina automaattisesti (viikko/kk tiheyden mukaan)
  const spanDays = (maxX - minX) / 864e5;
  const marks = timeTicks(minX, maxX, opts.timeGrid === "none" ? null : opts.timeGrid);
  ctx.font = "10px system-ui"; ctx.textAlign = "center";
  let lastLblX = -1e9;
  marks.forEach((t) => {
    const X = xPix(t);
    if (X < pad.l - 1 || X > W - pad.r + 1) return;
    ctx.strokeStyle = CHART_INK.grid;
    ctx.beginPath(); ctx.moveTo(X, pad.t); ctx.lineTo(X, pad.t + plotH); ctx.stroke();
    if (X - lastLblX < 52) return;  // ei päällekkäisiä tekstejä
    lastLblX = X;
    const lbl = spanDays > 45
      ? new Date(t).toLocaleDateString("fi-FI", { month: "short", year: "2-digit" })
      : new Date(t).toLocaleDateString("fi-FI", { day: "numeric", month: "numeric" });
    ctx.fillStyle = CHART_INK.faint;
    ctx.fillText(lbl, X, H - 10);
  });
  ctx.textAlign = "left";
  // Pohjaviiva (akseli) hieman ruudukkoa vahvempana
  ctx.strokeStyle = CHART_INK.axis;
  ctx.beginPath(); ctx.moveTo(pad.l, pad.t + plotH); ctx.lineTo(W - pad.r, pad.t + plotH); ctx.stroke();

  // Gradienttitäyttö viivan alle kun yksi yhtenäinen sarja (näyttävämpi)
  const solid = series.filter((s) => !s.dashed && s.points && s.points.length);
  if (solid.length === 1) {
    const s = solid[0];
    const color = s.color || CHART_COLORS[0];
    const pts = [...s.points].sort((a, b) => a.x - b.x);
    const grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + plotH);
    grad.addColorStop(0, color + "3d");
    grad.addColorStop(1, color + "00");
    ctx.fillStyle = grad;
    ctx.beginPath();
    pts.forEach((p, i) => { const X = xPix(p.x), Y = yPix(p.y); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    ctx.lineTo(xPix(pts[pts.length - 1].x), pad.t + plotH);
    ctx.lineTo(xPix(pts[0].x), pad.t + plotH);
    ctx.closePath(); ctx.fill();
  }

  // Ennustehaarukat (band) taustalle
  series.forEach((s, idx) => {
    if (!s.band || !s.band.length) return;
    const color = s.color || CHART_COLORS[idx % CHART_COLORS.length];
    const b = [...s.band].sort((a, p) => a.x - p.x);
    ctx.fillStyle = color + "1f";
    ctx.beginPath();
    b.forEach((p, i) => { const X = xPix(p.x), Y = yPix(p.high); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    for (let i = b.length - 1; i >= 0; i--) ctx.lineTo(xPix(b[i].x), yPix(b[i].low));
    ctx.closePath(); ctx.fill();
  });

  // Viivat: 2 px, pisteet vain jos niitä on vähän (ei tukkoon piirrettyä käyrää)
  series.forEach((s, idx) => {
    const color = s.color || CHART_COLORS[idx % CHART_COLORS.length];
    const pts = [...s.points].sort((a, b) => a.x - b.x);
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2;
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.setLineDash(s.dashed ? [6, 5] : []);
    ctx.beginPath();
    pts.forEach((p, i) => { const X = xPix(p.x), Y = yPix(p.y); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    ctx.stroke();
    ctx.setLineDash([]);
    if (!s.dashed && pts.length <= 48) {
      pts.forEach((p) => {
        ctx.beginPath(); ctx.arc(xPix(p.x), yPix(p.y), 2.5, 0, Math.PI * 2); ctx.fill();
      });
    }
  });

  // Tallenna pisteet + geometria hoverille (ristikko + korostettu piste)
  const hoverPts = [];
  series.forEach((s, idx) => {
    const color = s.color || CHART_COLORS[idx % CHART_COLORS.length];
    (s.points || []).forEach((p) => hoverPts.push({
      px: xPix(p.x), py: yPix(p.y), x: p.x, y: p.y, color,
      name: s.name || null, forecast: !!s.dashed, unit: opts.unit || "",
    }));
  });
  canvas._hoverPts = hoverPts;
  canvas._plot = { t: pad.t, b: pad.t + plotH };
  canvas._redraw = () => drawLineChart(canvas, series, opts);
  bindChartHover(canvas);
}

let _chartTooltip = null;
function bindChartHover(canvas) {
  if (canvas._hoverBound) return;
  canvas._hoverBound = true;
  if (!_chartTooltip) {
    _chartTooltip = el("div", { class: "chart-tooltip" });
    document.body.append(_chartTooltip);
  }
  const hide = () => {
    if (_chartTooltip) _chartTooltip.style.display = "none";
    if (canvas._hoverDrawn && canvas._redraw) { canvas._hoverDrawn = false; canvas._redraw(); }
  };
  canvas.addEventListener("mouseleave", hide);
  canvas.addEventListener("mousemove", (e) => {
    const pts = canvas._hoverPts;
    if (!pts || !pts.length) return hide();
    const rect = canvas.getBoundingClientRect();
    const scale = (canvas._logW || canvas.width) / rect.width;
    const mx = (e.clientX - rect.left) * scale, my = (e.clientY - rect.top) * scale;
    let best = null, bestD = 1e9;
    for (const p of pts) {
      const d = (p.px - mx) ** 2 + (p.py - my) ** 2;
      if (d < bestD) { bestD = d; best = p; }
    }
    if (!best || bestD > 32 ** 2) return hide();

    // Ristikko + korostettu piste piirretään uudelleenpiirron päälle
    if (canvas._redraw) {
      canvas._redraw();
      canvas._hoverDrawn = true;
      const dpr = Math.min(3, window.devicePixelRatio || 1);
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const plot = canvas._plot || { t: 0, b: canvas._logH };
      ctx.strokeStyle = "rgba(154,163,178,0.35)"; ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(best.px, plot.t); ctx.lineTo(best.px, plot.b); ctx.stroke();
      ctx.setLineDash([]);
      // Korostettu piste: iso merkki + pinnanvärinen rengas
      ctx.beginPath(); ctx.arc(best.px, best.py, 5.5, 0, Math.PI * 2);
      ctx.fillStyle = best.color; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = "#1a1d24"; ctx.stroke();
    }

    const dstr = new Date(best.x).toLocaleDateString("fi-FI", { weekday: "short", day: "numeric", month: "numeric", year: "numeric" });
    const vstr = (Math.round(best.y * 10) / 10).toLocaleString("fi-FI") + (best.unit ? " " + best.unit : "");
    _chartTooltip.innerHTML = "";
    _chartTooltip.append(
      el("div", { style: "display:flex;align-items:center;gap:6px" },
        el("span", { style: `width:9px;height:9px;border-radius:50%;background:${best.color};flex:none` }),
        el("strong", {}, vstr), best.forecast ? el("span", { class: "muted" }, "ennuste") : ""),
      el("div", { class: "muted", style: "margin-top:2px" },
        (best.name ? best.name + " · " : "") + dstr));
    _chartTooltip.style.display = "block";
    const tw = 170;
    const lx = e.clientX + 14 + tw > window.innerWidth ? e.clientX - tw - 10 : e.clientX + 14;
    _chartTooltip.style.left = lx + "px";
    _chartTooltip.style.top = (e.clientY + 12) + "px";
  });
}

// =================== YLEISNÄKYMÄ ===================
async function loadCoachNotices() {
  const card = document.getElementById("coach-card");
  const div = document.getElementById("coach-notices");
  if (!card) return;
  const data = await api.get(pq("/api/coach/notices"));
  if (!data.notices || !data.notices.length) { card.style.display = "none"; return; }
  card.style.display = "";
  div.innerHTML = "";
  const tone = { alert: "#ef4444", warn: "#f59e0b", info: "var(--accent)" };
  const icon = { alert: "🛑", warn: "⚠", info: "ℹ️" };
  data.notices.forEach((n) => {
    div.append(el("div", { class: "item", style: `border-left:3px solid ${tone[n.level] || "var(--accent)"}` },
      el("strong", { style: `color:${tone[n.level] || "var(--accent)"}` }, `${icon[n.level] || ""} ${n.title}`),
      el("div", { class: "muted", style: "margin-top:4px" }, n.message)));
  });
}

async function loadDirection() {
  const card = document.getElementById("direction-card");
  const div = document.getElementById("direction-content");
  if (!card) return;
  const d = await api.get(pq("/api/coach/direction"));
  if (!d.enough_data) {
    if (d.data_needs && d.data_needs.length) {
      card.style.display = "";
      div.innerHTML = "";
      div.append(el("p", { class: "muted" },
        "Kokonaiskuvaan tarvitaan lisää dataa. Kirjaa: " + d.data_needs.join(", ") + "."));
    } else card.style.display = "none";
    return;
  }
  card.style.display = "";
  div.innerHTML = "";
  const tone = { excellent: "var(--accent-2)", good: "var(--accent-2)", neutral: "#f59e0b", bad: "#ef4444", no_data: "var(--muted)" };
  const icon = { excellent: "🚀", good: "📈", neutral: "➖", bad: "⚠️" };
  div.append(el("div", { class: "result-box" },
    el("div", { class: "big", style: `color:${tone[d.verdict]}` }, `${icon[d.verdict] || ""} ${d.label}`)));
  const fTone = { good: "var(--accent-2)", warn: "#f59e0b", bad: "#ef4444" };
  const fIcon = { good: "✅", warn: "⚠️", bad: "🔻" };
  d.factors.forEach((f) => {
    div.append(el("div", { class: "item", style: `border-left:3px solid ${fTone[f.status] || "var(--border)"}` },
      el("strong", {}, `${fIcon[f.status] || ""} ${f.title}`),
      el("div", { class: "muted", style: "margin-top:3px" }, f.text)));
  });
  if (d.data_needs && d.data_needs.length) {
    div.append(el("div", { class: "muted", style: "margin-top:6px" },
      "Tarkempaan kuvaan: kirjaa myös " + d.data_needs.join(", ") + "."));
  }
}

// Aloitusopas: taustakyselystä johdettu suunnitelma uusille/vähädataisille
// profiileille. Piilotetaan kun treenejä on kertynyt reilusti (rutiini löytyi).
async function loadOnboarding() {
  const card = document.getElementById("onboarding-card");
  const div = document.getElementById("onboarding-content");
  let data;
  try { data = await api.get(pq("/api/coach/onboarding")); }
  catch { card.style.display = "none"; return; }
  div.innerHTML = "";
  const prof = profilesCache.find((p) => p.id === currentProfileId);
  const workoutCount = data.workout_count ?? (prof ? prof.workouts : 0);
  if (!data.available) {
    // Kysely täyttämättä: kehota vain jos profiili on vielä tuore
    if ((prof ? prof.workouts : 0) >= 10) { card.style.display = "none"; return; }
    card.style.display = "";
    div.append(
      el("p", { class: "muted" },
        "Täytä lyhyt taustakysely (treenitausta ja tavoite), niin saat henkilökohtaisen " +
        "ohjelmasuosituksen, jaksojen pituudet ja realistiset kehitysodotukset. " +
        "Puuttuu: " + (data.missing || []).join(", ") + "."),
      el("button", { class: "primary small", onclick: () => {
        document.querySelector('nav#tabs button[data-tab="profiles"]').click();
        setTimeout(() => { if (prof) openProfileForm(prof); }, 200);
      } }, "Täytä taustakysely"));
    return;
  }
  // Kysely täytetty: näytä opas kunnes rutiini on syntynyt (~20 treeniä)
  if (workoutCount >= 20 && data.program.has_program) { card.style.display = "none"; return; }
  card.style.display = "";
  const a = data.answers;
  const planNames = { aloittelija: "Aloittelijan ohjelma", bodaus: "Lihasmassaohjelma",
    voimanosto: "Voimanosto-ohjelma", olympia: "Olympianosto-ohjelma" };
  div.append(el("div", { class: "muted", style: "margin-bottom:6px" },
    `${a.experience_label}` + (a.training_years ? ` · ${a.training_years} treenivuotta` : "") +
    ` · tavoite: ${a.goal}` + (a.days_per_week ? ` · ${a.days_per_week} pv/vk` : "")));
  // Ohjelmasuositus
  const progBox = el("div", { class: "result-box", style: "margin-bottom:8px" },
    el("div", { class: "row-between" },
      el("strong", {}, `📋 Suositus: ${planNames[data.program.plan] || data.program.plan} ${data.program.days_per_week}×/vk`),
      data.program.has_program ? el("span", { class: "tag status-done" }, "ohjelma luotu") : ""),
    el("div", { class: "muted", style: "margin-top:4px" }, data.program.why));
  if (!data.program.has_program) {
    progBox.append(el("button", { class: "success small", style: "margin-top:8px", onclick: async (ev) => {
      ev.target.disabled = true;
      try {
        await api.post("/api/templates/generate", {
          plan: data.program.plan, days_per_week: data.program.days_per_week,
          profile_id: currentProfileId });
        alert("Ohjelma luotu! Löydät sen Ohjelmat-välilehdeltä — sieltä voit käynnistää treenit.");
        loadOverview();
      } catch (e) { alert("Virhe: " + e.message); ev.target.disabled = false; }
    } }, "Luo suositeltu ohjelma"));
  }
  div.append(progBox);
  // Jaksotus ja odotukset
  div.append(el("div", { style: "margin-bottom:6px" },
    el("strong", {}, `🗓 Jaksot: ${data.cycle.weeks_min}–${data.cycle.weeks_max} viikkoa`),
    el("div", { class: "muted" }, data.cycle.note)));
  div.append(el("div", { style: "margin-bottom:6px" },
    el("strong", {}, "📈 Mitä odottaa"),
    el("div", { class: "muted" }, data.expectation)));
  if (data.tips && data.tips.length) {
    const tipsBox = el("div", {}, el("strong", {}, "✅ Näillä pääset alkuun"));
    data.tips.forEach((t) => tipsBox.append(el("div", { class: "muted", style: "margin-top:3px" }, "• " + t)));
    div.append(tipsBox);
  }
}

async function loadOverview() {
  loadOnboarding();
  loadCoachNotices();
  loadDirection();
  const o = await api.get(pq("/api/stats/overview"));
  const cards = document.getElementById("overview-cards");
  cards.innerHTML = "";
  const card = (label, val) => el("div", { class: "card" },
    el("div", { class: "muted" }, label), el("div", { class: "big" }, String(val)));
  cards.append(card("Treenejä", o.total_workouts), card("Liikkeitä", o.total_exercises),
    card("Ohjelmia", o.total_programs));

  const recs = await api.get(pq("/api/stats/records?main_only=true"));
  const rdiv = document.getElementById("overview-records");
  rdiv.innerHTML = "";
  if (!recs.length) rdiv.append(el("p", { class: "muted" }, "Ei vielä dataa pääliikkeistä."));
  else rdiv.append(recordsTable(recs));

  const recent = document.getElementById("overview-recent");
  recent.innerHTML = "";
  if (!o.recent_workouts.length) recent.append(el("p", { class: "muted" }, "Ei treenejä."));
  for (const w of o.recent_workouts) {
    const emoji = { positive: " 😀", neutral: " 😐", negative: " 😟" }[w.feeling] || "";
    recent.append(el("div", { class: "muted" }, `${w.date} — ${w.name || "Treeni"} (${w.exercises} liikettä)${emoji}`));
  }

  // Merkityt fiilikset
  const flagged = o.flagged_feelings || [];
  document.getElementById("flagged-card").style.display = flagged.length ? "" : "none";
  const fdiv = document.getElementById("overview-flagged");
  fdiv.innerHTML = "";
  for (const f of flagged) {
    const emoji = f.feeling === "positive" ? "😀" : "😟";
    fdiv.append(el("div", { class: "item" },
      el("div", {}, `${emoji} ${f.date} — ${f.name || "Treeni"}`),
      f.feeling_note ? el("div", { class: "muted" }, f.feeling_note) : ""));
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

async function loadTargetWeights() {
  const card = document.getElementById("target-weights-card");
  const div = document.getElementById("target-weights");
  const data = await api.get(pq("/api/stats/target-weights"));
  if (!data.lifts || !data.lifts.length) { card.style.display = "none"; return; }
  card.style.display = "";
  div.innerHTML = "";
  data.lifts.forEach((l) => {
    div.append(el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("strong", {}, l.exercise_name),
        el("span", { class: "tag main" }, `1RM ~${l.current_1rm} kg`)),
      el("div", { class: "btn-row", style: "gap:14px;flex-wrap:wrap;margin-top:4px" },
        el("span", {}, el("span", { class: "muted" }, "5×5: "), el("strong", {}, `${l.schemes["5x5"]} kg`)),
        el("span", {}, el("span", { class: "muted" }, "3×3: "), el("strong", {}, `${l.schemes["3x3"]} kg`)),
        el("span", {}, el("span", { class: "muted" }, "1RM: "), el("strong", {}, `${l.schemes["1RM"]} kg`))),
      l.forecast_1rm_1y ? el("div", { class: "muted", style: "margin-top:3px" },
        (l.forecast_1rm_4wk ? `Ennuste 4 vk: 1RM ~${l.forecast_1rm_4wk} kg · ` : "") +
        `~1 v: 1RM ~${l.forecast_1rm_1y} kg (5×5 ~${Math.round(l.forecast_1rm_1y / (1 + 7 / 30) / l.increment) * l.increment} kg) — sama laskuri kuin kehitysgraafissa`) : ""));
  });
}

async function loadProgress() {
  await restoreProgressSelection();
  renderProgressChips();
  await loadTargetWeights();
  renderBackfill();
  await loadForecastAccuracy();
  await loadMuscleLoad();
  await loadLevels();
  await loadComeback();
  await loadSports();
  await loadLoadTimeline();
  await loadRecordsTable();
}

async function loadMuscleLoad() {
  const div = document.getElementById("muscle-load-content");
  const data = await api.get(pq("/api/stats/muscle-load"));
  div.innerHTML = "";
  if (!data.areas || !data.areas.length) {
    div.append(el("p", { class: "muted" }, data.message || "Ei dataa.")); return;
  }
  const tone = { low: "#f59e0b", none: "#ef4444", high: "#e66767", ok: "var(--accent-2)", info: "var(--muted)" };
  const statusLabel = { low: "vajaa", none: "ei kuormaa", high: "paljon", ok: "hyvä", info: "kesken" };
  div.append(el("div", { class: "muted", style: "margin-bottom:8px" },
    `${data.workouts_week} treeniä viimeisen 14 pv aikana (edellinen 14 pv: ${data.workouts_prev}). ` +
    "Luvut ovat tehollisia sarjoja/viikko (14 pv keskiarvo), epäsuora kuorma mukana " +
    "(esim. penkki kerryttää ojentajia). Värillinen palkki = tehty, vihreä vyöhyke = suositushaarukka."));
  if (data.data_note) {
    div.append(el("div", { class: "muted", style: "margin-bottom:8px;font-style:italic" }, `ℹ ${data.data_note}`));
  }
  // Aluerivit: nimi + palkki (tavoitehaarukka varjostettuna) + sarjat + tila
  data.areas.forEach((a) => {
    const scaleMax = a.target_max * 1.3;
    const pct = Math.min(100, a.effective_sets / scaleMax * 100);
    const zoneLeft = a.target_min / scaleMax * 100;
    const zoneWidth = (a.target_max - a.target_min) / scaleMax * 100;
    const trend = a.prev_sets > 0 ? (a.effective_sets >= a.prev_sets * 1.15 ? " ↑" : (a.effective_sets <= a.prev_sets * 0.85 ? " ↓" : "")) : "";
    const last = a.days_since != null ? `pääkuormaa viimeksi ${a.days_since} pv sitten`
      : (a.tonnage > 0 ? "vain epäsuoraa kuormaa" : "ei kuormaa");
    div.append(el("div", { style: "margin-bottom:7px" },
      el("div", { class: "row-between", style: "font-size:0.9em" },
        el("span", {}, el("strong", { style: "text-transform:capitalize" }, a.area),
          el("span", { class: "muted" }, ` ${a.effective_sets}${trend} / ${a.target_min}–${a.target_max} sarjaa/vk`)),
        el("span", { class: "tag", style: `color:${tone[a.status]};border-color:${tone[a.status]}` }, statusLabel[a.status] || a.status)),
      el("div", { style: "position:relative;height:8px;background:var(--bg);border-radius:4px;overflow:hidden;margin-top:2px" },
        el("div", { style: `position:absolute;left:${zoneLeft}%;width:${zoneWidth}%;height:100%;background:color-mix(in srgb, var(--accent-2) 22%, transparent)` }),
        el("div", { style: `position:absolute;left:0;width:${pct}%;height:100%;background:${tone[a.status]};border-radius:4px;opacity:0.85` })),
      el("div", { class: "muted", style: "font-size:0.78em" }, `${last} · ~${a.tonnage} kg/vk alueelle`)));
  });
  // Hermostokuorma
  if (data.cns) {
    const c = data.cns;
    const cnsTone = { low: "var(--muted)", moderate: "var(--accent-2)", high: "#f59e0b",
      very_high: "#ef4444", overreach: "#ef4444" }[c.verdict] || "var(--muted)";
    div.append(el("div", { class: "result-box", style: "margin-top:10px" },
      el("div", { class: "row-between" },
        el("strong", {}, "⚡ Hermostollinen kuorma"),
        el("span", { class: "tag", style: `color:${cnsTone};border-color:${cnsTone}` },
          `${c.score} p · ${c.verdict === "overreach" ? "ylikuorma" : c.label}`)),
      el("div", { class: "muted", style: "margin-top:4px" }, c.note),
      el("div", { class: "muted", style: "font-size:0.8em;margin-top:3px" },
        `Edellinen viikko: ${c.prev_score} p` +
        (c.readiness_score != null ? ` · palautumispisteet ${c.readiness_score}/100` : ""))));
  }
  // Ehdotukset vajaimmille alueille
  if (data.suggestions && data.suggestions.length) {
    const box = el("div", { style: "margin-top:10px" }, el("strong", {}, "Ehdotukset vajaille alueille:"));
    data.suggestions.forEach((s) => {
      box.append(el("div", { class: "muted", style: "margin-top:4px" },
        el("span", { class: "tag", style: "margin-right:6px;text-transform:capitalize" }, s.area),
        s.note + (s.in_program ? "" : "")));
    });
    div.append(box);
  }
}

async function loadComeback() {
  const card = document.getElementById("comeback-card");
  const div = document.getElementById("comeback-content");
  const data = await api.get(pq("/api/stats/comeback"));
  if (!data.comebacks || !data.comebacks.length) { card.style.display = "none"; return; }
  card.style.display = "";
  div.innerHTML = "";
  data.comebacks.forEach((c) => {
    // Ilmaise aika luonnollisesti: vuodet jos pitkä tauko, muuten viikot
    const ago = c.years_since >= 1 ? `${c.years_since} v` : `${Math.round(c.weeks_since)} vk`;
    const prYear = c.best_ever_date ? ` (${c.best_ever_date.slice(0, 4)})` : "";
    const regain = c.regain_weeks >= 52 ? "~1 v" : (c.regain_weeks >= 8 ? `~${Math.round(c.regain_weeks / 4.3)} kk` : `~${c.regain_weeks} vk`);
    div.append(el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("strong", {}, c.exercise_name),
        el("span", { class: "tag" }, `ennätys ${c.best_ever_1rm} kg${prYear}`)),
      el("div", { class: "muted" },
        `Viimeksi tehty ${ago} sitten · arvioitu nyt ~${c.estimated_current_1rm} kg (−${c.lost_pct}%)`),
      el("div", { style: "margin-top:4px" },
        el("strong", { style: "color:var(--accent-2)" }, `Aloita ~${c.suggested_start_kg} kg`),
        el("span", { class: "muted" }, ` · takaisin huippuun arviolta ${regain} (lihasmuisti nopeuttaa)`))));
  });
}

async function loadForecastAccuracy() {
  const card = document.getElementById("accuracy-card");
  const div = document.getElementById("accuracy-content");
  const data = await api.get(pq("/api/stats/forecast-accuracy"));
  if (!data.overall) { card.style.display = "none"; return; }
  card.style.display = "";
  div.innerHTML = "";
  const o = data.overall;
  div.append(el("div", { class: "result-box" },
    el("div", { class: "big" }, `${o.within_band_pct}% haarukan sisällä`),
    el("div", { class: "muted" }, `${o.count} erääntynyttä ennustetta · keskivirhe ${o.mae} (${o.avg_error_pct} %)`)));
  const tbl = el("table", {});
  tbl.append(el("tr", {}, el("th", {}, "Kohde"), el("th", {}, "Tehty"), el("th", {}, "Horisontti"),
    el("th", {}, "Ennuste"), el("th", {}, "Toteuma"), el("th", {}, "Ero")));
  data.comparisons.slice(0, 12).forEach((c) => tbl.append(el("tr", {},
    el("td", {}, c.label), el("td", { class: "muted" }, c.made_on),
    el("td", {}, `${c.horizon_weeks} vk`), el("td", {}, String(c.predicted)),
    el("td", {}, String(c.actual)),
    el("td", { class: "tag " + (c.within_band ? "status-done" : "status-skip") },
      `${c.error >= 0 ? "+" : ""}${c.error}`))));
  div.append(tbl);
}

async function loadLevels() {
  const data = await api.get(pq("/api/stats/levels"));
  const div = document.getElementById("levels-content");
  div.innerHTML = "";
  if (!data.bodyweight) {
    div.append(el("p", { class: "muted" }, "Lisää kehon paino (Keho-välilehti) ja kirjaa pääliikkeitä nähdäksesi voimatason."));
    return;
  }
  if (!data.lifts.length) {
    div.append(el("p", { class: "muted" }, "Kirjaa pääliikkeitä (kyykky, penkki, maastaveto, pystypunnerrus) nähdäksesi tason."));
    return;
  }
  // Selite kaikista tasoista (avattava) — mitä mikäkin taso tarkoittaa
  const meanings = data.level_meanings || [];
  const legendWrap = el("div", { class: "hidden" });
  data.all_levels.forEach((name, i) => {
    legendWrap.append(el("div", { class: "muted", style: "margin:2px 0" },
      el("strong", { style: "color:var(--text)" }, `${i + 1}. ${name}: `), meanings[i] || ""));
  });
  const legBtn = el("button", { class: "small", onclick: () => {
    const open = !legendWrap.classList.toggle("hidden");
    legBtn.textContent = open ? "▾ Mitä tasot tarkoittavat" : "▸ Mitä tasot tarkoittavat";
  } }, "▸ Mitä tasot tarkoittavat");
  div.append(el("div", { style: "margin-bottom:10px" }, legBtn, legendWrap));

  data.lifts.forEach((l) => {
    const total = data.all_levels.length;
    const box = el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("strong", {}, l.exercise_name),
        el("span", { class: "tag main", title: l.level_meaning || "" }, `${l.level} (${l.ratio}× paino)`)));

    // Segmentoitu tasopalkki: hover näyttää rajan kiloina ja tason merkityksen
    box.append(segLevelBar(data.all_levels, l.level_index, {
      shorts: ["Aloitt.", "Harrast.", "Keski", "Edist.", "Kokenut", "Piiri", "SM", "MM"],
      titles: (l.thresholds_kg || []).map((thr, i) =>
        `${data.all_levels[i]} — raja ${thr} kg` + (meanings[i] ? `\n${meanings[i]}` : "")),
    }));

    // Nykytaso + sen merkitys + seuraavan tason raja kiloina
    box.append(el("div", { class: "muted", style: "margin-top:6px" }, l.level_meaning || ""));
    box.append(el("div", { class: "muted" },
      `Arvioitu 1RM ${l.current_1rm} kg` +
      (l.next_level ? ` · seuraavaan tasoon (${l.next_level}) tarvitaan ${l.next_threshold_kg} kg` : " · olet huipputasolla!")));
    if (l.population_avg) {
      box.append(el("div", { class: "muted" },
        `Väestön keskiarvo painollasi ~${l.population_avg} kg · sinä ${l.vs_population}× keskiarvo`));
    }
    div.append(box);
  });
}

let backfillExId = null;
function renderBackfill() {
  const span = document.getElementById("backfill-ex");
  span.innerHTML = "";
  const sel = exerciseSelect((e) => (backfillExId = +e.target.value));
  backfillExId = exercisesCache.length ? exercisesCache[0].id : null;
  if (exercisesCache.length) sel.value = backfillExId;
  span.append(sel);
}

document.getElementById("bf-save").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  if (!backfillExId || !v("bf-date") || !v("bf-weight") || !v("bf-reps")) return alert("Täytä liike, päivä, paino ja toistot.");
  // Vanha tulos = oma treenikerta menneellä päivällä (yksi sarja)
  await api.post("/api/workouts", {
    profile_id: currentProfileId, session_date: v("bf-date"), name: "Vanha tulos", status: "completed",
    exercises: [{ exercise_id: backfillExId, done: true,
      sets: [{ set_index: 0, reps: +v("bf-reps"), weight: +v("bf-weight"), completed: true }] }],
  });
  ["bf-weight", "bf-reps"].forEach((id) => (document.getElementById(id).value = ""));
  await loadLevels(); await drawProgressChart(); await loadLoadTimeline(); await loadRecordsTable();
  await loadComeback();
  alert("Tulos tallennettu. Jos päivä on riittävän kaukana, näet paluusuunnitelman \"Paluu vanhoihin tuloksiin\" -kortissa.");
});

let loadMode = "program";

async function loadLoadTimeline() {
  const sum = document.getElementById("load-summary");
  sum.innerHTML = "";
  if (loadMode === "program") {
    const data = await api.get(pq("/api/stats/program-load"));
    const series = [];
    let idx = 0;
    (data.programs || []).forEach((prog) => {
      const color = CHART_COLORS[idx % CHART_COLORS.length];
      series.push({ name: prog.program_name, points: prog.cycles.map((c) => ({ x: new Date(c.date).getTime(), y: c.total_kg })), color });
      idx++;
      const last = prog.cycles[prog.cycles.length - 1];
      sum.append(el("div", { class: "muted" },
        `${prog.program_name}${prog.is_active ? " (aktiivinen)" : ""}: ${prog.cycles.length} kierrosta · ` +
        `viimeisin kierto ${Math.round(last.total_kg).toLocaleString("fi-FI")} kg (${last.workouts} treeniä` +
        (last.skipped ? `, ${last.skipped} skipattu → total pienempi` : "") + ")" +
        (prog.open_partial ? ` · kesken oleva kierto ${prog.open_partial.workouts} treeniä tehty` : "")));
    });
    if (!series.length) {
      sum.append(el("p", { class: "muted" }, "Kun ohjelman kaikki treenit on tehty kerran, näet kierron kokonaiskuorman tässä. (Aktivoi ohjelma ja tee sen treenit.)"));
    }
    drawLineChart(document.getElementById("load-chart"), series, { unit: "kg" });
  } else {
    const data = await api.get(pq("/api/stats/load-timeline"));
    if (data.length) {
      const latest = data[data.length - 1];
      const totalAll = data.reduce((a, d) => a + d.total_kg, 0);
      sum.append(el("div", { class: "muted" },
        `Viimeisin treeni: ${Math.round(latest.total_kg)} kg · ${latest.reps} toistoa · ${latest.sets} sarjaa` +
        (latest.duration_min ? ` · ${latest.duration_min} min` : "") +
        (latest.kcal_burned ? ` · ${latest.kcal_burned} kcal poltettu` : "") +
        ` · kaikkiaan siirretty ${Math.round(totalAll).toLocaleString("fi-FI")} kg`));
    }
    drawLineChart(document.getElementById("load-chart"),
      [{ name: "Treenin kuorma", points: data.map((d) => ({ x: new Date(d.date).getTime(), y: d.total_kg })) }], { unit: "kg" });
  }
}

document.querySelectorAll(".load-mode-btn").forEach((b) => b.addEventListener("click", () => {
  loadMode = b.dataset.mode;
  document.querySelectorAll(".load-mode-btn").forEach((x) => x.classList.toggle("active", x === b));
  loadLoadTimeline();
}));

// Pääliikkeet (kyykky/penkki/mave/pystypunnerrus tai pääliikkeeksi merkitty)
// ovat kehitysgraafin prioriteetti: ne listataan ensin ja ne saavat ennusteen.
const MAIN_LIFT_WORDS = ["kyykky", "penkki", "maasta", "mave", "pystypunnerrus"];
function isMainLiftLike(ex) {
  const n = (ex.name || "").toLowerCase();
  return !!ex.is_main_lift || MAIN_LIFT_WORDS.some((w) => n.includes(w));
}
// Liikkeet joilla on kirjattua dataa (ennätystaulukosta) -> etusijalle listassa
let progressDataIds = new Set();

function progressStorageKey() { return `progressSelection:${currentProfileId ?? "none"}`; }
function saveProgressSelection() {
  try { localStorage.setItem(progressStorageKey(), JSON.stringify([...selectedProgress])); } catch (e) { /* ei kriittinen */ }
}
// Palauta valinta (profiilikohtainen); jos ei tallennettua, valitse oletuksena
// pääliikkeet joissa on dataa (max 3) -> ennuste näkyy heti.
async function restoreProgressSelection() {
  selectedProgress = new Set();
  const validIds = new Set(exercisesCache.map((e) => e.id));
  try {
    const saved = JSON.parse(localStorage.getItem(progressStorageKey()) || "null");
    if (Array.isArray(saved)) saved.forEach((id) => { if (validIds.has(+id)) selectedProgress.add(+id); });
  } catch (e) { /* ei kriittinen */ }
  try {
    const recs = await api.get(pq("/api/stats/records"));
    progressDataIds = new Set(recs.map((r) => r.exercise_id));
    if (!selectedProgress.size) {
      recs.filter((r) => r.is_main_lift || isMainLiftLike({ name: r.exercise_name }))
        .filter((r) => r.sessions >= 2)
        .slice(0, 3)
        .forEach((r) => selectedProgress.add(r.exercise_id));
    }
  } catch (e) { /* ei kriittinen */ }
}

function renderProgressChips() {
  const search = document.getElementById("progress-search").value.toLowerCase();
  const chips = document.getElementById("progress-chips");
  chips.innerHTML = "";
  // Järjestys: valitut aina ensin (ja aina näkyvissä, vaikka haku ei osuisi),
  // sitten pääliikkeet joissa on dataa, muut liikkeet joissa on dataa, loput.
  const rank = (ex) => (selectedProgress.has(ex.id) ? 0 : 1) * 100
    + (isMainLiftLike(ex) ? 0 : 10) + (progressDataIds.has(ex.id) ? 0 : 1);
  const list = exercisesCache
    .filter((ex) => selectedProgress.has(ex.id) || ex.name.toLowerCase().includes(search))
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name, "fi"));
  const shown = list.filter((ex) => selectedProgress.has(ex.id))
    .concat(list.filter((ex) => !selectedProgress.has(ex.id)).slice(0, 30));
  shown.forEach((ex) => {
    const active = selectedProgress.has(ex.id);
    const main = isMainLiftLike(ex);
    chips.append(el("button", {
      class: "small" + (active ? " primary" : ""),
      title: main ? "Pääliike — saa ennusteen" : "",
      onclick: () => {
        active ? selectedProgress.delete(ex.id) : selectedProgress.add(ex.id);
        saveProgressSelection();
        renderProgressChips(); drawProgressChart();
      } }, (active ? "✓ " : "") + ex.name + (main && !active ? " ★" : "")));
  });
}

let progressRangeDays = 0;   // 0 = kaikki

async function drawProgressChart() {
  const series = [];
  const legend = document.getElementById("progress-legend");
  legend.innerHTML = "";
  let idx = 0;
  const single = selectedProgress.size === 1;
  // Historiaraja: näytä vain viimeiset N päivää (ennuste säilyy kokonaan)
  const cutoff = progressRangeDays ? Date.now() - progressRangeDays * 864e5 : null;
  const notes = [];
  let anyForecast = false;
  for (const id of selectedProgress) {
    const h = await api.get(pq(`/api/stats/exercises/${id}/history`));
    const color = CHART_COLORS[idx % CHART_COLORS.length];
    // Vain päivät joina liike oikeasti tehtiin (0 = ei suoritettua sarjaa ->
    // ei piirretä "tiputusta" nollaan).
    let pts = h.points.filter((p) => p.estimated_1rm > 0)
      .map((p) => ({ x: new Date(p.date).getTime(), y: p.estimated_1rm }));
    if (cutoff) pts = pts.filter((p) => p.x >= cutoff);
    series.push({ name: h.exercise_name, points: pts, color });
    legend.append(el("span", { class: "tag", style: `color:${color};border-color:${color}` }, h.exercise_name));
    // Ennuste (katkoviiva + haarukka) jokaiselle valitulle pääliikkeelle —
    // säilyy näkyvissä vaikka vertailuun lisätään muita liikkeitä.
    const meta = h.forecast_meta;
    if (h.forecast && h.forecast.length && meta) {
      // Ankkuri = nykytaso (paras tuoreen ikkunan sisällä), ei viimeisin
      // yksittäinen treeni -> kevyt päivä ei näy ennusteen pudotuksena.
      const anchor = { x: new Date(meta.anchor_date).getTime(), y: meta.anchor };
      const fc = h.forecast.map((p) => ({ x: new Date(p.date).getTime(), y: p.mid }));
      const band = h.forecast.map((p) => ({ x: new Date(p.date).getTime(), low: p.low, high: p.high }));
      series.push({ name: h.exercise_name + " (ennuste)", points: [anchor, ...fc], band, color, dashed: true });
      anyForecast = true;
      const w4 = h.forecast[3] || h.forecast[h.forecast.length - 1];
      const w52 = h.forecast[h.forecast.length - 1];
      notes.push(el("div", { class: "muted", style: "margin-top:4px;width:100%" },
        el("span", { style: `color:${color}` }, `${h.exercise_name}: `),
        `nykytaso ${meta.anchor} kg → 4 vk ~${w4.mid} kg → 1 v ~${w52.mid} kg (${w52.low}–${w52.high})`
        + (single ? ". " + meta.note : "")));
    }
    idx++;
  }
  if (anyForecast) legend.append(el("span", { class: "muted" }, " — katkoviiva = ennuste, alue = haarukka"));
  notes.forEach((n) => legend.append(n));
  drawLineChart(document.getElementById("progress-chart"), series, { unit: "kg" });
}

document.getElementById("progress-search").addEventListener("input", renderProgressChips);
document.querySelectorAll(".range-btn").forEach((b) => b.addEventListener("click", () => {
  progressRangeDays = +b.dataset.range;
  document.querySelectorAll(".range-btn").forEach((x) => x.classList.toggle("active", x === b));
  drawProgressChart();
}));

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
  // Oletukseksi laji jossa on dataa (ei tyhjää totalia ensin)
  let preferred = prev;
  if (!sports.includes(preferred)) {
    const recs = await api.get(pq("/api/stats/records?main_only=true"));
    const sportsWithData = new Set(recs.map((r) => r.sport).filter(Boolean));
    preferred = sports.find((s) => sportsWithData.has(s)) || sports[0];
  }
  sel.value = preferred;
  await drawTotal();
}

document.getElementById("sport-select").addEventListener("change", drawTotal);

async function drawTotal() {
  const sport = document.getElementById("sport-select").value;
  if (!sport) return;
  const t = await api.get(pq(`/api/stats/total?sport=${encodeURIComponent(sport)}`));
  const sum = document.getElementById("total-summary");
  sum.innerHTML = "";
  const fcEnd = t.forecast && t.forecast.length ? t.forecast[t.forecast.length - 1] : null;
  sum.append(el("div", { class: "result-box" },
    el("div", {}, `${sport} — tämänhetkinen yhteistulos`),
    el("div", { class: "big" }, `${t.total_mid} kg`),
    el("div", { class: "muted" }, `Haarukka ${t.total_low}–${t.total_high} kg`),
    el("div", { class: "muted" }, t.per_lift.map((l) => `${l.exercise_name}: ${l.current_1rm}kg`).join(" · ")),
    fcEnd ? el("div", { class: "muted", style: "margin-top:6px" },
      `Ennuste ~1 v: ${fcEnd.low}–${fcEnd.high} kg (mihin tällä tahdilla ollaan menossa; haarukka kapenee kun dataa kertyy)`) : ""));

  // Kilpailutaso: painoluokka + paikallinen → MM (yhteistuloksen mukaan)
  const c = t.competition;
  if (c) {
    const box = el("div", { class: "item", style: "margin-top:10px" },
      el("div", { class: "row-between" },
        el("strong", {}, `Kisataso · painoluokka ${c.weight_class}`),
        el("span", { class: "tag main" }, c.level)));
    // Segmentoitu tasopalkki: Paikallinen · SM · EM · MM (raja kiloina hoverissa)
    box.append(segLevelBar(c.levels, c.level_index, {
      titles: c.thresholds_kg.map((thr, i) => `${c.levels[i]} — raja ${thr} kg`),
    }));
    box.append(el("div", { class: "muted" }, c.next_threshold_kg
      ? `Seuraava taso (${c.next_level}) painoluokassasi: ${c.next_threshold_kg} kg — eroa ${c.to_next_kg} kg`
      : "Olet ylimmällä tasolla!"));
    box.append(el("div", { class: "muted" },
      "Rajat: " + c.levels.map((n, i) => `${n.split(" ")[0]} ${c.thresholds_kg[i]}kg`).join(" · ")));
    box.append(el("div", { class: "muted", style: "margin-top:4px;font-size:0.8em" },
      sport === "voimanosto"
        ? "Voimanostossa ratkaisee yhteistulos (kyykky+penkki+mave) painoluokassasi — ei yksittäinen nosto."
        : (sport === "olympia"
          ? "Olympianostoissa ratkaisee yhteistulos (tempaus + rinnalleveto & työntö) painoluokassasi."
          : "Yhteistulos painoluokassasi.")));
    sum.append(box);
  }

  // Historiaraja (ennuste säilyy kokonaan)
  const cutoff = totalRangeDays ? Date.now() - totalRangeDays * 864e5 : null;
  let tl = t.timeline.map((p) => ({ x: new Date(p.date).getTime(), y: p.total }));
  if (cutoff) tl = tl.filter((p) => p.x >= cutoff);
  const series = [{ name: "Yhteistulos", points: tl }];
  if (t.forecast && t.forecast.length && t.timeline.length) {
    const last = t.timeline[t.timeline.length - 1];
    const anchor = { x: new Date(last.date).getTime(), y: last.total };
    const fc = t.forecast.map((p) => ({ x: new Date(p.date).getTime(), y: p.mid }));
    const band = t.forecast.map((p) => ({ x: new Date(p.date).getTime(), low: p.low, high: p.high }));
    series.push({ name: "Yhteistulos", points: [anchor, ...fc], band, dashed: true, color: CHART_COLORS[1] });
  }
  drawLineChart(document.getElementById("total-chart"), series, { unit: "kg" });
}

let totalRangeDays = 0;
document.querySelectorAll(".trange-btn").forEach((b) => b.addEventListener("click", () => {
  totalRangeDays = +b.dataset.range;
  document.querySelectorAll(".trange-btn").forEach((x) => x.classList.toggle("active", x === b));
  drawTotal();
}));

// ---- Ennätystaulukko ----
async function loadRecordsTable() {
  const recs = await api.get(pq("/api/stats/records"));
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
document.getElementById("generate-btn").addEventListener("click", async () => {
  const panel = document.getElementById("generate-panel");
  panel.classList.toggle("hidden");
  if (panel.classList.contains("hidden")) return;
  panel.innerHTML = "";
  const plans = await api.get("/api/templates/plans");
  const planSel = el("select", {});
  plans.forEach((p) => planSel.append(el("option", { value: p.id }, p.name || p.id)));
  const daysSel = el("select", {});
  const info = el("div", { class: "muted", style: "margin:8px 0" });
  function refreshDays() {
    const p = plans.find((x) => x.id === planSel.value);
    daysSel.innerHTML = "";
    p.days_options.forEach((d) => daysSel.append(el("option", { value: d }, `${d}× viikossa`)));
    info.innerHTML = "";
    if (p.emphasis) info.append(el("div", {}, el("strong", {}, "Painotus: "), el("span", {}, p.emphasis)));
    if (p.suits) info.append(el("div", { style: "margin-top:4px" }, el("strong", {}, "Kenelle: "), el("span", {}, p.suits)));
    info.append(el("div", { style: "margin-top:6px" }, p.guidance));
    if (p.next_phase) info.append(el("div", { style: "margin-top:6px;color:var(--accent-2)" }, "➜ " + p.next_phase));
  }
  planSel.addEventListener("change", refreshDays);
  panel.append(
    el("div", { class: "grid" }, el("label", {}, "Laji", planSel), el("label", {}, "Treenikerrat", daysSel)),
    info,
    el("div", { class: "btn-row" },
      el("button", { class: "success", onclick: async () => {
        const r = await api.post("/api/templates/generate", {
          plan: planSel.value, days_per_week: +daysSel.value, profile_id: currentProfileId });
        panel.classList.add("hidden");
        await loadPrograms();
        let msg = `Ohjelma "${r.name}" luotu (${r.days} treenipäivää).`;
        if (r.missing_exercises && r.missing_exercises.length) msg += ` Huom: ${r.missing_exercises.length} liikettä puuttui kirjastosta.`;
        alert(msg);
      } }, "Luo ohjelma"),
      el("button", { onclick: () => panel.classList.add("hidden") }, "Peruuta")));
  refreshDays();
});

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
        await api.post("/api/templates/build", { template_id: tSel.value, exercise_ids: ids, profile_id: currentProfileId });
        panel.classList.add("hidden"); loadPrograms();
      } }, "Luo ohjelma pohjasta"),
      el("button", { onclick: () => panel.classList.add("hidden") }, "Peruuta")));
  updateGuidance();
});

// =================== PROFIILIT ===================
function initials(name) {
  return name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}

async function loadProfiles() {
  profilesCache = await api.get("/api/profiles");
  if (!profilesCache.length) return;
  // Muista viimeksi käytetty profiili: avaa se ensin (jos yhä olemassa eikä
  // roolilukko ole jo valinnut profiilia).
  if (currentProfileId == null) {
    const saved = +localStorage.getItem("lastProfileId");
    if (saved && profilesCache.some((p) => p.id === saved)) currentProfileId = saved;
  }
  if (currentProfileId == null || !profilesCache.some((p) => p.id === currentProfileId)) {
    currentProfileId = profilesCache[0].id;
  }
  renderProfileSwitch();
}

// Aseta aktiivinen profiili ja muista se seuraavaa avausta varten.
function setActiveProfile(id) {
  currentProfileId = id;
  if (id != null) localStorage.setItem("lastProfileId", String(id));
}

function renderProfileSwitch() {
  const sel = document.getElementById("profile-select");
  sel.innerHTML = "";
  profilesCache.forEach((p) => {
    const o = el("option", { value: p.id }, p.name);
    sel.append(o);
  });
  sel.value = currentProfileId;
  // Profiililukossa tavallinen käyttäjä näkee vain oman profiilinsa -> ei
  // vaihtomahdollisuutta (estää vahingossa väärälle profiilille kirjaamisen).
  sel.disabled = authRole() === "profile";
  const cur = profilesCache.find((p) => p.id === currentProfileId);
  const av = document.getElementById("profile-avatar");
  av.textContent = cur ? initials(cur.name) : "";
  av.style.background = cur && cur.color ? cur.color : "var(--accent)";
}

document.getElementById("profile-select").addEventListener("change", async (e) => {
  setActiveProfile(+e.target.value);
  renderProfileSwitch();
  await refreshActiveTab();
});

// --- Profiililukko (valinnainen pääsynhallinta) ----------------------------

// Lukee tokenin payloadin (allekirjoitettu mutta ei salattu) roolin ja
// profiilin selvittämiseksi ilman palvelinkyselyä.
function tokenPayload() {
  const t = authToken();
  if (!t || !t.includes(".")) return null;
  try {
    let b = t.split(".")[0].replace(/-/g, "+").replace(/_/g, "/");
    b += "=".repeat((4 - (b.length % 4)) % 4);
    return JSON.parse(atob(b));
  } catch (e) { return null; }
}
function authRole() { const p = tokenPayload(); return p ? p.role : null; }

function hideLockScreen() {
  const o = document.getElementById("lock-overlay");
  if (o) o.remove();
}

// Näyttää lukitusnäytön: käyttäjä valitsee profiilinsa ja syöttää PINin, tai
// kirjautuu PT:nä (admin) joka näkee kaikki profiilit.
async function showLockScreen() {
  hideLockScreen();
  let status;
  try { status = await api.get("/api/auth/status"); }
  catch (e) { return; }
  if (!status.enabled) { hideLockScreen(); return; }

  const overlay = el("div", { id: "lock-overlay", class: "lock-overlay" });
  const card = el("div", { class: "lock-card" });
  const msg = el("div", { class: "lock-msg muted" });

  async function doLogin(payload) {
    msg.textContent = "";
    try {
      const r = await api.post("/api/auth/login", payload);
      setAuthToken(r.token);
      hideLockScreen();
      currentProfileId = r.profile_id || null;
      await bootAfterLogin();
    } catch (e) { msg.textContent = e.message || "Kirjautuminen epäonnistui."; }
  }

  function renderPicker() {
    card.innerHTML = "";
    card.append(
      el("h2", {}, "Kuka kirjaa?"),
      el("div", { class: "muted", style: "margin-bottom:12px" },
        "Valitse oma profiilisi. Näin kirjaukset menevät oikealle henkilölle."),
    );
    status.profiles.forEach((p) => {
      card.append(el("button", { class: "lock-profile", onclick: () => {
        if (p.has_pin) renderPin(p); else doLogin({ mode: "profile", profile_id: p.id });
      } }, el("span", { class: "lock-ava" }, initials(p.name)),
         el("span", {}, p.name),
         p.has_pin ? el("span", { class: "lock-lock" }, "🔒") : ""));
    });
    card.append(
      el("div", { class: "lock-sep" }),
      el("button", { class: "lock-admin", onclick: renderAdmin }, "Olen valmentaja (PT)"),
      msg);
  }

  function renderPin(p) {
    card.innerHTML = "";
    const inp = el("input", { type: "password", inputmode: "numeric",
      placeholder: "PIN", class: "lock-input" });
    const submit = () => doLogin({ mode: "profile", profile_id: p.id, pin: inp.value });
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    card.append(
      el("h2", {}, p.name),
      el("div", { class: "muted", style: "margin-bottom:10px" }, "Syötä profiilisi PIN."),
      inp,
      el("div", { class: "btn-row", style: "margin-top:12px" },
        el("button", { class: "primary", onclick: submit }, "Kirjaudu"),
        el("button", { onclick: renderPicker }, "Takaisin")),
      msg);
    setTimeout(() => inp.focus(), 50);
  }

  function renderAdmin() {
    card.innerHTML = "";
    const inp = el("input", { type: "password", inputmode: "numeric",
      placeholder: "Admin-PIN", class: "lock-input" });
    const submit = () => doLogin({ mode: "admin", pin: inp.value });
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    card.append(
      el("h2", {}, "Valmentaja (PT)"),
      el("div", { class: "muted", style: "margin-bottom:10px" },
        "Admin-PINillä näet ja hallinnoit kaikkia profiileja."),
      inp,
      el("div", { class: "btn-row", style: "margin-top:12px" },
        el("button", { class: "primary", onclick: submit }, "Kirjaudu"),
        el("button", { onclick: renderPicker }, "Takaisin")),
      msg);
    setTimeout(() => inp.focus(), 50);
  }

  renderPicker();
  overlay.append(card);
  document.body.append(overlay);
}

// Kirjautumisen jälkeen: lataa profiilit uudelleen (oikeilla oikeuksilla) ja
// piilota profiilinvaihto tavallisilta käyttäjiltä.
async function bootAfterLogin() {
  await loadProfiles();
  await loadExercises();
  await refreshActiveTab();
}

// Portti sovelluksen alussa: jos lukko on päällä eikä voimassa olevaa tokenia
// ole, näytä lukitusnäyttö. Palauttaa true jos voi jatkaa normaalisti.
async function authGate() {
  let status;
  try { status = await api.get("/api/auth/status"); }
  catch (e) { return true; }
  if (!status.enabled) { setAuthToken(null); return true; }
  // Onko token voimassa? Testataan kevyellä kutsulla.
  if (authToken()) {
    try { await api.get("/api/profiles"); return true; }
    catch (e) { setAuthToken(null); }
  }
  await showLockScreen();
  return false;
}

async function refreshActiveTab() {
  // Lataa nykyiset perusnäkymät + aktiivisen välilehden data.
  await loadPrograms();
  await loadWorkouts();
  const activeTab = document.querySelector("nav#tabs button.active");
  const loader = activeTab && TAB_LOADERS[activeTab.dataset.tab];
  if (loader) await loader(); else await loadOverview();
}

// QR-koodi paikallisesti (vendoroitu kirjasto, toimii offline).
function makeQR(textData, sizePx) {
  try {
    const qr = qrcode(0, "M");
    qr.addData(textData);
    qr.make();
    const wrap = el("div", { style: `width:${sizePx}px;height:${sizePx}px;background:#fff;border-radius:8px;padding:6px;box-sizing:border-box` });
    wrap.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
    const svg = wrap.querySelector("svg");
    if (svg) { svg.setAttribute("width", "100%"); svg.setAttribute("height", "100%"); }
    return wrap;
  } catch (e) { return null; }
}

async function loadNetworkInfo() {
  const box = document.getElementById("network-info");
  if (!box) return;
  try {
    const info = await api.get("/api/network-info");
    box.innerHTML = "";
    const isLocal = info.lan_ip === "127.0.0.1";
    box.append(
      el("div", { class: "btn-row", style: "align-items:center;gap:8px;flex-wrap:wrap" },
        el("a", { href: info.phone_url, target: "_blank",
          style: "font-size:1.2em;font-weight:700;color:var(--accent)" }, info.phone_url),
        el("button", { class: "small", onclick: async () => {
          try { await navigator.clipboard.writeText(info.phone_url); }
          catch (e) { /* leikepöytä ei käytettävissä */ }
        } }, "Kopioi")),
      isLocal
        ? el("div", { class: "muted", style: "margin-top:6px" },
            "Lähiverkon IP:tä ei tunnistettu. Tarkista että kone on wifissä — " +
            "puhelimen pitää olla samassa verkossa.")
        : el("div", { class: "muted", style: "margin-top:6px" },
            "Kirjoita osoite puhelimen selaimeen tai skannaa QR alta."),
    );
    if (!isLocal) {
      const qrEl = makeQR(info.phone_url, 160);
      if (qrEl) { qrEl.style.marginTop = "10px"; box.append(qrEl); }
    }
    // Tallenna oma osoite laitesynkronointia varten
    window._phoneUrl = info.phone_url;
    // Versio näkyviin (auttaa varmistamaan että laitteet ovat samassa versiossa)
    try {
      const v = await api.get("/api/version");
      box.append(el("div", { class: "muted", style: "margin-top:8px;font-size:0.8rem" },
        `Versio ${v.version} (${v.build}) · isännöitynä sovellus päivittyy automaattisesti kun avaat sen uudelleen`));
    } catch (e) { /* ei kriittinen */ }
  } catch (e) {
    box.textContent = "Osoitteen haku epäonnistui.";
  }
}

function renderCompletenessHint() {
  const list = document.getElementById("profile-list");
  const p = profilesCache.find((x) => x.id === currentProfileId);
  if (!p) return;
  const missing = [];
  if (!p.sex) missing.push("sukupuoli");
  if (p.age == null) missing.push("syntymäaika (ikä)");
  if (!p.height_cm) missing.push("pituus");
  if (!p.latest_bodyweight) missing.push("kehon paino (Keho-välilehti)");
  if (missing.length) {
    list.append(el("div", { class: "item", style: "border-left:3px solid #f59e0b" },
      el("strong", { style: "color:#f59e0b" }, "Täydennä profiili tarkempia lukuja varten"),
      el("div", { class: "muted", style: "margin-top:4px" },
        `Puuttuu: ${missing.join(", ")}. Näitä käytetään TDEE:hen, FFMI:hin ja voimatasoihin — ilman niitä arviot ovat karkeampia.`)));
  }
}

function logout() {
  setAuthToken(null);
  currentProfileId = null;
  showLockScreen();
}

// Profiililukon hallintakortti Profiilit-välilehdellä.
async function loadSecurityCard() {
  const box = document.getElementById("security-info");
  if (!box) return;
  box.innerHTML = "";
  let status;
  try { status = await api.get("/api/auth/status"); }
  catch (e) { box.textContent = "Tilan haku epäonnistui."; return; }

  const note = el("div", { class: "muted", style: "margin-top:8px;font-size:0.85rem" });

  // 1) Lukko pois päältä: kuka tahansa voi ottaa sen käyttöön asettamalla admin-PINin.
  if (!status.enabled) {
    const pinInp = el("input", { type: "password", inputmode: "numeric",
      placeholder: "Admin-PIN (väh. 4)", style: "max-width:180px" });
    box.append(
      el("p", { class: "muted", style: "margin-top:0" },
        "Lukko on pois päältä — kaikki tällä instanssilla näkevät ja voivat kirjata mille " +
        "tahansa profiilille. Jos jaat sovelluksen kavereille, ota lukko käyttöön: " +
        "sinä (PT) näet kaikki, muut vain oman profiilinsa."),
      el("div", { class: "btn-row" },
        pinInp,
        el("button", { class: "primary", onclick: async () => {
          try {
            const r = await api.post("/api/auth/setup", { admin_pin: pinInp.value });
            setAuthToken(r.token);
            note.textContent = "Lukko käyttöön. Aseta seuraavaksi profiileille omat PINit.";
            note.style.color = "var(--accent)";
            await loadProfilesTab();
          } catch (e) { note.textContent = e.message; note.style.color = "#ef4444"; }
        } }, "Ota lukko käyttöön")),
      note);
    return;
  }

  // 2) Lukko päällä, tavallinen käyttäjä: vain uloskirjautuminen.
  if (authRole() !== "admin") {
    box.append(
      el("p", { class: "muted", style: "margin-top:0" },
        "Lukko on päällä. Näet vain oman profiilisi. Vain valmentaja (PT) hallinnoi lukkoa."),
      el("button", { onclick: logout }, "Kirjaudu ulos"));
    return;
  }

  // 3) Lukko päällä, admin: hallinnoi profiilien PINejä, admin-PIN, poisto.
  box.append(el("p", { class: "muted", style: "margin-top:0" },
    "Lukko on päällä. Sinä (PT) näet kaikki profiilit; muut pääsevät vain omaansa. " +
    "Aseta kullekin profiilille oma PIN — profiili ilman PINiä on avoin kenelle vain."));

  status.profiles.forEach((p) => {
    const pinInp = el("input", { type: "password", inputmode: "numeric",
      placeholder: p.has_pin ? "uusi PIN" : "aseta PIN", style: "max-width:120px" });
    const st = el("span", { class: "muted", style: "font-size:0.8rem" },
      p.has_pin ? "🔒 PIN asetettu" : "avoin");
    const row = el("div", { class: "row-between", style: "gap:8px;margin:6px 0;flex-wrap:wrap" },
      el("div", {}, el("strong", {}, p.name), " ", st),
      el("div", { class: "btn-row" },
        pinInp,
        el("button", { class: "small", onclick: async () => {
          try {
            const r = await api.post("/api/auth/profile-pin", { profile_id: p.id, pin: pinInp.value });
            st.textContent = r.has_pin ? "🔒 PIN asetettu" : "avoin";
            pinInp.value = "";
          } catch (e) { st.textContent = e.message; }
        } }, "Tallenna"),
        p.has_pin ? el("button", { class: "small", onclick: async () => {
          try {
            await api.post("/api/auth/profile-pin", { profile_id: p.id, pin: "" });
            st.textContent = "avoin";
          } catch (e) { st.textContent = e.message; }
        } }, "Poista PIN") : ""));
    box.append(row);
  });

  const admInp = el("input", { type: "password", inputmode: "numeric",
    placeholder: "uusi admin-PIN", style: "max-width:160px" });
  box.append(
    el("div", { class: "lock-sep", style: "margin:12px 0" }),
    el("div", { class: "btn-row" },
      admInp,
      el("button", { class: "small", onclick: async () => {
        try { await api.post("/api/auth/change-admin-pin", { admin_pin: admInp.value });
          note.textContent = "Admin-PIN vaihdettu."; note.style.color = "var(--accent)"; admInp.value = "";
        } catch (e) { note.textContent = e.message; note.style.color = "#ef4444"; }
      } }, "Vaihda admin-PIN")),
    el("div", { class: "btn-row", style: "margin-top:10px" },
      el("button", { onclick: logout }, "Kirjaudu ulos"),
      el("button", { style: "color:#ef4444", onclick: async () => {
        if (!confirm("Poistetaanko lukko? Kaikki PINit nollataan ja instanssi palaa avoimeksi.")) return;
        try { await api.post("/api/auth/disable"); setAuthToken(null); await loadProfilesTab(); }
        catch (e) { note.textContent = e.message; }
      } }, "Poista lukko käytöstä")),
    note);
}

// =================== YHTEISÖ ===================
async function loadCommunity() {
  const box = document.getElementById("community-view");
  if (!box) return;
  box.innerHTML = "";
  let data;
  try { data = await api.get("/api/community/overview"); }
  catch (e) { box.textContent = "Yhteisön haku epäonnistui."; return; }

  // --- PT-viesti ---
  const ptCard = el("div", { class: "card" }, el("h3", { style: "margin-top:0" }, "📣 PT-viesti"));
  if (data.pt_message) {
    ptCard.append(el("div", { class: "pt-message" }, data.pt_message),
      data.pt_message_at ? el("div", { class: "muted", style: "font-size:0.78rem;margin-top:6px" },
        "Päivitetty " + data.pt_message_at.slice(0, 10)) : "");
  } else if (!data.is_admin) {
    ptCard.append(el("div", { class: "muted" }, "Ei viestiä juuri nyt."));
  }
  if (data.is_admin) {
    const ta = el("textarea", { rows: 2, style: "width:100%;margin-top:8px",
      placeholder: "Kirjoita viesti kaikille (esim. tiedote, kannustus, aikataulu)…" }, data.pt_message || "");
    const st = el("span", { class: "muted", style: "font-size:0.8rem" });
    ptCard.append(ta, el("div", { class: "btn-row", style: "margin-top:6px" },
      el("button", { class: "primary small", onclick: async () => {
        try { await api.post("/api/community/pt-message", { message: ta.value }); st.textContent = "Tallennettu."; loadCommunity(); }
        catch (e) { st.textContent = e.message; }
      } }, "Tallenna viesti"),
      data.pt_message ? el("button", { class: "small", onclick: async () => {
        try { await api.post("/api/community/pt-message", { message: "" }); loadCommunity(); }
        catch (e) { st.textContent = e.message; }
      } }, "Poista") : "", st));
  }
  box.append(ptCard);

  // --- Oma jaettava statusrivi ---
  const me = data.members.find((m) => m.id === currentProfileId);
  const myCard = el("div", { class: "card" }, el("h3", { style: "margin-top:0" }, "🙋 Oma jaettava rivi"));
  const noteInp = el("input", { type: "text", maxlength: 200, style: "width:100%",
    placeholder: "Esim. tavoite, kuulumiset, motto (näkyy muille)", value: me && me.public_note ? me.public_note : "" });
  const noteSt = el("span", { class: "muted", style: "font-size:0.8rem" });
  myCard.append(noteInp, el("div", { class: "btn-row", style: "margin-top:6px" },
    el("button", { class: "small", onclick: async () => {
      try { await api.post("/api/community/public-note", { profile_id: currentProfileId, note: noteInp.value }); noteSt.textContent = "Tallennettu."; loadCommunity(); }
      catch (e) { noteSt.textContent = e.message; }
    } }, "Tallenna"),
    el("button", { class: "small", onclick: async () => {
      try { await api.post("/api/community/public-note", { profile_id: currentProfileId, hide_from_community: true }); loadCommunity(); }
      catch (e) { noteSt.textContent = e.message; }
    } }, "Piilota minut yhteisöstä"), noteSt));
  box.append(myCard);

  // --- Jäsenet ---
  const memCard = el("div", { class: "card" },
    el("h3", { style: "margin-top:0" }, `👥 Jäsenet (${data.members.length})`));
  const grid = el("div", { class: "member-grid" });
  data.members.forEach((m) => {
    grid.append(el("div", { class: "member" },
      el("div", { class: "member-top" },
        el("span", { class: "lock-ava", style: m.color ? `background:${m.color}` : "" }, initials(m.name)),
        el("div", {}, el("strong", {}, m.name),
          el("div", { class: "muted", style: "font-size:0.8rem" },
            [m.age != null ? m.age + " v" : null, m.sex || null].filter(Boolean).join(" · ")))),
      el("div", { class: "member-stats" },
        el("span", {}, `🏋️ ${m.workouts} treeniä`),
        m.last_workout ? el("span", {}, `Viimeksi ${m.last_workout}`) : el("span", { class: "muted" }, "Ei treenejä vielä"),
        m.joined ? el("span", { class: "muted" }, `Liittyi ${m.joined}`) : ""),
      m.public_note ? el("div", { class: "member-note" }, m.public_note) : ""));
  });
  memCard.append(grid);
  box.append(memCard);

  // --- Hall of Fame ---
  const hofCard = el("div", { class: "card" },
    el("h3", { style: "margin-top:0" }, "🏆 Hall of Fame"));
  hofCard.append(el("p", { class: "muted", style: "margin-top:0" },
    "Jaa saavutus kaikkien nähtäville: ennätys, virstanpylväs tai kuulumiset."));
  const hTitle = el("input", { type: "text", maxlength: 120, placeholder: "Otsikko (esim. Uusi penkki-ennätys 100 kg!)", style: "width:100%" });
  const hBody = el("textarea", { rows: 2, placeholder: "Vapaa kuvaus (valinnainen)", style: "width:100%;margin-top:6px" });
  const hSt = el("span", { class: "muted", style: "font-size:0.8rem" });
  hofCard.append(hTitle, hBody, el("div", { class: "btn-row", style: "margin-top:6px" },
    el("button", { class: "primary small", onclick: async () => {
      if (!hTitle.value.trim()) { hSt.textContent = "Otsikko puuttuu."; return; }
      try { await api.post("/api/community/hall", { profile_id: currentProfileId, title: hTitle.value, body: hBody.value }); loadCommunity(); }
      catch (e) { hSt.textContent = e.message; }
    } }, "Jaa saavutus"), hSt));

  const list = el("div", { class: "list", style: "margin-top:10px" });
  if (!data.hall_of_fame.length) {
    list.append(el("div", { class: "muted" }, "Ei vielä merkintöjä — ole ensimmäinen!"));
  }
  data.hall_of_fame.forEach((e) => {
    const actions = el("div", { class: "btn-row" });
    if (data.is_admin) {
      actions.append(el("button", { class: "small", onclick: async () => {
        await api.patch(`/api/community/hall/${e.id}`, { pinned: !e.pinned }); loadCommunity();
      } }, e.pinned ? "Irrota" : "📌 Kiinnitä"),
      el("button", { class: "small", onclick: async () => {
        await api.patch(`/api/community/hall/${e.id}`, { hidden: !e.hidden }); loadCommunity();
      } }, e.hidden ? "Näytä" : "Piilota"));
    }
    if (e.can_edit) {
      actions.append(el("button", { class: "small danger", onclick: async () => {
        if (confirm("Poistetaanko merkintä?")) { await api.del(`/api/community/hall/${e.id}`); loadCommunity(); }
      } }, "Poista"));
    }
    list.append(el("div", { class: "item" + (e.hidden ? " hof-hidden" : "") },
      el("div", { class: "row-between" },
        el("div", {},
          el("strong", {}, e.pinned ? "📌 " : "", e.title),
          el("div", { class: "muted", style: "font-size:0.8rem" },
            `${e.author}${e.created_at ? " · " + e.created_at : ""}${e.hidden ? " · piilotettu" : ""}`)),
        actions),
      e.body ? el("div", { style: "margin-top:6px" }, e.body) : ""));
  });
  hofCard.append(list);
  box.append(hofCard);
}

async function loadProfilesTab() {
  await loadProfiles();
  loadNetworkInfo();
  loadSecurityCard();
  const list = document.getElementById("profile-list");
  list.innerHTML = "";
  renderCompletenessHint();
  for (const p of profilesCache) {
    const isCurrent = p.id === currentProfileId;
    const item = el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("div", { class: "btn-row", style: "align-items:center" },
          el("span", { class: "avatar", style: `background:${p.color || "var(--accent)"}` }, initials(p.name)),
          el("strong", {}, p.name + (isCurrent ? " (aktiivinen)" : ""))),
        el("div", { class: "btn-row" },
          isCurrent ? "" : el("button", { class: "small primary", onclick: async () => {
            setActiveProfile(p.id); renderProfileSwitch(); await refreshActiveTab(); loadProfilesTab();
          } }, "Valitse"),
          el("button", { class: "small", onclick: () => openProfileForm(p) }, "Muokkaa"),
          el("button", { class: "small danger", onclick: async () => {
            if (confirm(`Poista profiili "${p.name}" ja kaikki sen data?`)) {
              try { await api.del(`/api/profiles/${p.id}`); await loadProfiles(); loadProfilesTab(); }
              catch (e) { alert("Virhe: " + e.message); }
            }
          } }, "Poista"))));
    const info = [];
    if (p.age != null) info.push(`${p.age} v`);
    if (p.sex) info.push(p.sex);
    if (p.height_cm) info.push(`${p.height_cm} cm`);
    if (p.latest_bodyweight) info.push(`${p.latest_bodyweight} kg`);
    info.push(`${p.workouts} treeniä`, `${p.programs} ohjelmaa`);
    item.append(el("div", { class: "muted" }, info.join(" · ")));
    list.append(item);
  }
}

// Yhteinen lomake profiilin luontiin (existing = null) ja muokkaukseen.
function openProfileForm(existing) {
  const form = document.getElementById("profile-form");
  form.classList.remove("hidden");
  form.innerHTML = "";
  form.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const name = el("input", { placeholder: "Nimi", value: existing ? existing.name : "" });
  const sex = el("select", {}, el("option", { value: "" }, "—"),
    el("option", { value: "mies" }, "mies"), el("option", { value: "nainen" }, "nainen"),
    el("option", { value: "muu" }, "muu"));
  if (existing && existing.sex) sex.value = existing.sex;
  const bd = el("input", { type: "date", value: existing && existing.birthdate ? existing.birthdate : "" });
  const height = el("input", { type: "number", step: "0.5", placeholder: "cm", value: existing && existing.height_cm ? existing.height_cm : "" });
  const color = el("input", { type: "color", value: existing && existing.color ? existing.color : "#4f8cff" });
  // Taustakysely: kokemus ja tavoite ohjaavat ohjelmasuosituksia ja ennusteita
  const expSel = el("select", {}, el("option", { value: "" }, "— valitse —"),
    el("option", { value: "aloittelija" }, "Aloittelija (ei aiempaa salitreeniä)"),
    el("option", { value: "jonkin_verran" }, "Jonkin verran (alle ~2 v tai epäsäännöllisesti)"),
    el("option", { value: "kokenut" }, "Kokenut (useita vuosia säännöllisesti)"),
    el("option", { value: "palaava" }, "Palaava (treenannut ennen, nyt tauolta)"));
  if (existing && existing.experience) expSel.value = existing.experience;
  const yearsIn = el("input", { type: "number", step: "0.5", min: "0", placeholder: "esim. 5",
    value: existing && existing.training_years != null ? existing.training_years : "" });
  const goalSel = el("select", {}, el("option", { value: "" }, "— valitse —"),
    el("option", { value: "voima" }, "Voima (isommat raudat)"),
    el("option", { value: "lihasmassa" }, "Lihasmassa (koko ja muoto)"),
    el("option", { value: "kunto" }, "Yleiskunto ja terveys"),
    el("option", { value: "painonpudotus" }, "Painonpudotus (lihakset säilyttäen)"));
  if (existing && existing.goal) goalSel.value = existing.goal;
  const daysSel = el("select", {}, ...[2, 3, 4, 5, 6].map((d) =>
    el("option", { value: String(d) }, `${d} päivää/vk`)));
  daysSel.value = existing && existing.days_per_week ? String(existing.days_per_week) : "3";
  form.append(
    el("h3", { style: "margin-top:0" }, existing ? `Muokkaa profiilia: ${existing.name}` : "Uusi profiili"),
    el("div", { class: "grid" },
      el("label", {}, "Nimi", name), el("label", {}, "Sukupuoli", sex),
      el("label", {}, "Syntymäaika (ikä lasketaan)", bd), el("label", {}, "Pituus", height),
      el("label", {}, "Väri", color)),
    el("h4", { style: "margin-bottom:4px" }, "Taustakysely (suositukset & ennusteet)"),
    el("p", { class: "muted", style: "margin-top:0" },
      "Vastausten perusteella järjestelmä ehdottaa sopivan ohjelman, jakson pituudet ja " +
      "realistiset kehitysodotukset — ja kalibroi ennusteet kunnes omaa dataa kertyy."),
    el("div", { class: "grid" },
      el("label", {}, "Treenitausta", expSel),
      el("label", {}, "Treenivuosia yhteensä", yearsIn),
      el("label", {}, "Päätavoite", goalSel),
      el("label", {}, "Ehdin treenata", daysSel)),
    el("div", { class: "btn-row" },
      el("button", { class: "success", onclick: async () => {
        if (!name.value.trim()) return alert("Anna nimi.");
        const payload = {
          name: name.value.trim(), sex: sex.value || null, birthdate: bd.value || null,
          height_cm: height.value ? +height.value : null, color: color.value,
          experience: expSel.value || null,
          training_years: yearsIn.value !== "" ? +yearsIn.value : null,
          goal: goalSel.value || null,
          days_per_week: +daysSel.value,
        };
        if (existing) {
          await api.patch(`/api/profiles/${existing.id}`, payload);
        } else {
          const p = await api.post("/api/profiles", payload);
          setActiveProfile(p.id);
        }
        form.classList.add("hidden");
        await loadProfiles(); renderProfileSwitch(); loadProfilesTab(); await refreshActiveTab();
      } }, "Tallenna"),
      el("button", { onclick: () => form.classList.add("hidden") }, "Peruuta")));
}

document.getElementById("new-profile-btn").addEventListener("click", () => openProfileForm(null));

// ---- Varmuuskopio: lataus ja palautus ----
// ---- Laitesynkronointi ----
document.getElementById("sync-scan-btn").addEventListener("click", () => {
  const box = document.getElementById("sync-qr");
  box.innerHTML = "";
  const url = window._phoneUrl;
  if (!url) { box.append(el("div", { class: "muted" }, "Osoitetta ei vielä haettu.")); return; }
  const qr = makeQR(url, 180);
  box.append(el("div", { class: "muted", style: "margin-bottom:6px" },
    "Tämän laitteen osoite: " + url + ". Kirjoita se toisen laitteen kenttään, tai skannaa:"),
    qr || el("div", { class: "muted" }, "QR:ää ei voitu luoda."));
});

document.getElementById("sync-now-btn").addEventListener("click", async () => {
  const status = document.getElementById("sync-status");
  const url = (document.getElementById("sync-url").value || "").trim();
  if (!url) { status.textContent = "Anna toisen laitteen osoite (tai skannaa sen QR)."; return; }
  const onlyThis = document.getElementById("sync-thisprofile").checked;
  status.textContent = "Synkronoidaan…";
  try {
    const body = { url, push_back: true };
    if (onlyThis && currentProfileId != null) body.profile_id = currentProfileId;
    const r = await api.post("/api/sync/pull", body);
    const got = r.pulled ? r.pulled.added_total : 0;
    const sent = r.pushed ? r.pushed.added_total : 0;
    status.textContent = `✓ ${r.message} Tälle laitteelle tuli ${got} uutta riviä, toiselle lähti ${sent}.`;
    await loadProfiles(); await refreshActiveTab();
  } catch (e) {
    status.textContent = "Synkronointi epäonnistui: " + e.message +
      " — varmista että molemmat laitteet ovat samassa wifissä ja osoite on oikein.";
  }
});

document.getElementById("backup-download").addEventListener("click", async () => {
  const status = document.getElementById("backup-status");
  status.textContent = "Kootaan varmuuskopiota…";
  try {
    const data = await api.get("/api/backup/export");
    const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 10);
    a.href = url; a.download = `treeni-varmuuskopio-${stamp}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    status.textContent = "Varmuuskopio ladattu. Säilytä tiedosto turvassa.";
  } catch (e) { status.textContent = "Lataus epäonnistui: " + e.message; }
});

document.getElementById("backup-restore-btn").addEventListener("click", () => {
  document.getElementById("backup-file").click();
});

document.getElementById("backup-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  const status = document.getElementById("backup-status");
  if (!confirm("Palautus KORVAA kaikki nykyisen datan varmuuskopiolla. Jatketaanko?")) {
    ev.target.value = ""; return;
  }
  status.textContent = "Palautetaan…";
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    const res = await api.post("/api/backup/import", payload);
    const total = Object.values(res.restored || {}).reduce((a, b) => a + b, 0);
    status.textContent = `Palautettu (${total} riviä). Ladataan sovellus uudelleen…`;
    setTimeout(() => window.location.reload(), 1200);
  } catch (e) { status.textContent = "Palautus epäonnistui: " + e.message; }
  ev.target.value = "";
});

// =================== KEHO ===================
async function renderBodyScore() {
  const div = document.getElementById("body-score");
  div.innerHTML = "";
  const bs = await api.get(pq("/api/stats/body-score"));
  if (bs.overall_score == null) {
    div.append(el("p", { class: "muted" }, "Kirjaa kehon mittoja, paino + rasva-% ja pääliikkeitä nähdäksesi pisteet.")); return;
  }
  const scoreBox = (label, val, sub) => el("div", { class: "result-box" },
    el("div", { class: "muted" }, label), el("div", { class: "big" }, val == null ? "—" : `${val}`),
    sub ? el("div", { class: "muted" }, sub) : "");
  div.append(el("div", { class: "grid" },
    scoreBox("Yhteispisteet", bs.overall_score, "ulkonäkö + voima"),
    scoreBox("Suhdepisteet", bs.proportion ? bs.proportion.score : null, "mittojen suhteet"),
    scoreBox("Fysiikkataso", bs.physique ? bs.physique.level : null, bs.physique ? `FFMI ${bs.physique.ffmi}` : ""),
    scoreBox("Voimataso", bs.strength_score, bs.strength_level_avg != null ? `taso ka. ${bs.strength_level_avg}/7` : "")));
  if (bs.proportion && bs.proportion.breakdown) {
    const tbl = el("table", {});
    tbl.append(el("tr", {}, el("th", {}, "Suhde"), el("th", {}, "Arvo"), el("th", {}, "Pisteet")));
    Object.entries(bs.proportion.breakdown).forEach(([k, v]) =>
      tbl.append(el("tr", {}, el("td", {}, k), el("td", {}, String(v.ratio)), el("td", {}, `${v.score}/100`))));
    div.append(tbl);
  }
  div.append(el("div", { class: "muted", style: "margin-top:6px" }, bs.note));
}

async function renderBodypartLevels() {
  const div = document.getElementById("bodypart-levels");
  div.innerHTML = "";
  const data = await api.get(pq("/api/stats/bodypart-levels"));
  if (!data.height_cm) {
    div.append(el("p", { class: "muted" }, "Aseta pituus profiiliin nähdäksesi kehon osien tasot.")); return;
  }
  if (!data.parts.length) {
    div.append(el("p", { class: "muted" }, "Lisää ympärysmittoja nähdäksesi osien tasot.")); return;
  }
  const total = data.all_levels.length;
  data.parts.forEach((p) => {
    const pct = p.level_index < 0 ? 4 : Math.round(((p.level_index + 1) / total) * 100);
    const ref = p.reversed
      ? `keskiarvo ~${p.population_avg_cm} cm · huippu(ohut) ~${p.elite_cm} cm`
      : `keskiarvo ~${p.population_avg_cm} cm · huippu ~${p.elite_cm} cm`;
    const item = el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("strong", { style: "text-transform:capitalize" }, p.site),
        el("span", { class: "tag main" }, `${p.level} (${p.value_cm} cm)`)),
      el("div", { class: "level-bar" }, el("div", { class: "level-fill", style: `width:${pct}%` })),
      el("div", { class: "muted" }, `${ref} · sinä ${p.vs_population}× keskiarvo`));
    // Rasvakorjaus: kertoo jos osa mitasta on rasvaa (rehellisempi lihaskuva)
    if (p.fat_note) {
      item.append(el("div", { class: "muted", style: "margin-top:3px;color:#f59e0b" }, "⚑ " + p.fat_note));
    }
    div.append(item);
  });
}

// ---- Kehon 3D-hahmo (Three.js): oikea valaistu 3D-malli ----
// Keho rakennetaan poikkileikkausrenkaista oikeaksi 3D-verkoksi (ellipsi-
// renkaat + etusiirtymä), joten maha ja povi työntyvät VAIN eteenpäin ja
// pakarat taakse. Pää kasvonpiirteineen (nenä, korvat, hiukset) kääntyy
// mukana. Sukupuoli ja rasva-% muokkaavat muotoa, mitat kokoa.
let _figState = null;

function renderBodyFigure(sites, height, sex, bodyFat) {
  const area = document.getElementById("figure-area");
  const dateWrap = document.getElementById("figure-date-wrap");
  area.innerHTML = ""; dateWrap.innerHTML = "";
  if (_figState) { _figState.dead = true; try { _figState.renderer.dispose(); } catch (e) {} _figState = null; }
  const siteNames = Object.keys(sites || {});
  if (!siteNames.length) {
    area.append(el("p", { class: "muted" }, "Lisää ympärysmittoja (vyötärö, hartia, reisi…) niin piirrän hahmon."));
    return;
  }
  if (typeof THREE === "undefined") {
    area.append(el("p", { class: "muted" }, "3D-hahmo vaatii three.js-kirjaston (frontend/vendor)."));
    return;
  }
  const dateSet = new Set();
  siteNames.forEach((s) => sites[s].forEach((p) => dateSet.add(p.date)));
  const dates = [...dateSet].sort();
  const SITE_ALIAS = { hartia: "hartiat", rintakehä: "rinta", pohje: "pohkeet", reisi: "reidet" };
  function valueAsOf(site, dateStr) {
    const arr = sites[site] || sites[SITE_ALIAS[site]];
    if (!arr) return null;
    let v = null;
    for (const p of arr) { if (p.date <= dateStr) v = p.value; }
    return v;
  }

  const female = (sex || "").toLowerCase().startsWith("nain");
  const h = height || (female ? 167 : 178);
  const refBf = female ? 20 : 12;
  const fat = bodyFat == null ? 0.25 : Math.max(0, Math.min(1, (bodyFat - refBf) / 22));

  // --- Three.js-perusta ---
  const CW = 340, CH = 560;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2.5, window.devicePixelRatio || 1));
  renderer.setSize(CW, CH);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.style.cssText = "max-width:100%;cursor:grab;touch-action:pan-y;border-radius:12px";
  const chipRow = el("div", { class: "btn-row", style: "justify-content:center;margin-top:6px" });
  const hint = el("div", { class: "muted", style: "font-size:0.8em;margin-top:2px" }, "↔ pyöritä vetämällä · tuplaklikkaus = automaattipyöritys");
  area.append(renderer.domElement, chipRow, hint);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, CW / CH, 1, 2000);
  camera.position.set(0, h * 0.56, h * 2.05);
  camera.lookAt(0, h * 0.5, 0);
  scene.add(new THREE.HemisphereLight(0xbfd0e8, 0x2a2d38, 1.15));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(60, 160, 120);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.bias = -0.0002;
  sun.shadow.normalBias = 2.5;
  const sc = sun.shadow.camera;
  sc.left = -80; sc.right = 80; sc.top = 200; sc.bottom = -10; sc.far = 500;
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0x8899cc, 0.5);
  fill.position.set(-80, 60, -80);
  scene.add(fill);
  // Lattia (vain varjo)
  const ground = new THREE.Mesh(new THREE.CircleGeometry(70, 48), new THREE.ShadowMaterial({ opacity: 0.35 }));
  ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true;
  scene.add(ground);

  const group = new THREE.Group();
  scene.add(group);

  // Materiaalit
  const skin = new THREE.MeshStandardMaterial({ color: 0xc9a58f, roughness: 0.72, metalness: 0.03 });
  const hairM = new THREE.MeshStandardMaterial({ color: 0x33261d, roughness: 0.85 });
  const eyeM = new THREE.MeshStandardMaterial({ color: 0x1c1c22, roughness: 0.35 });

  // Yleistetty sylinteri renkaista: {y, w (x-puolileveys), d (z-puolisyvyys), zc (etusiirtymä)}
  function tube(rawRings, mat) {
    const seg = 30;
    // Tihennä renkaat (cosine-interpolointi) -> sileät normaalit ja muodot
    const rings = [];
    for (let i = 0; i < rawRings.length - 1; i++) {
      const a = rawRings[i], b = rawRings[i + 1];
      const steps = Math.max(1, Math.round(Math.abs(b.y - a.y) / (h * 0.012)));
      for (let s = 0; s < steps; s++) {
        const t = s / steps, u = (1 - Math.cos(t * Math.PI)) / 2;
        rings.push({
          y: a.y + (b.y - a.y) * t,
          w: a.w + (b.w - a.w) * u,
          d: a.d + (b.d - a.d) * u,
          zc: (a.zc || 0) + ((b.zc || 0) - (a.zc || 0)) * u,
        });
      }
    }
    rings.push(rawRings[rawRings.length - 1]);
    const pos = [];
    rings.forEach((r) => {
      for (let i = 0; i <= seg; i++) {
        const a = (i / seg) * Math.PI * 2;
        pos.push(r.w * Math.sin(a), r.y, (r.zc || 0) + r.d * Math.cos(a));
      }
    });
    const idx = [];
    for (let j = 0; j < rings.length - 1; j++) {
      for (let i = 0; i < seg; i++) {
        const a = j * (seg + 1) + i, b = a + 1, c = a + seg + 1, d = c + 1;
        idx.push(a, b, c, b, d, c);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(idx);
    g.computeVertexNormals();
    const m = new THREE.Mesh(g, mat);
    m.castShadow = true;
    return m;
  }
  const ell = (rx, ry, rz, mat) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 18), mat);
    m.scale.set(rx, ry, rz); m.castShadow = true;
    return m;
  };

  let usedChips = {};
  function buildModel(dateStr) {
    // Tyhjennä vanha
    for (let i = group.children.length - 1; i >= 0; i--) {
      const c = group.children[i];
      c.traverse && c.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
      group.remove(c);
    }
    const defC = female
      ? { hartia: h * 0.585, rintakehä: h * 0.53, vyötärö: h * 0.42, lantio: h * 0.56,
          hauis: h * 0.165, reisi: h * 0.325, pohje: h * 0.21, kaula: h * 0.19 }
      : { hartia: h * 0.63, rintakehä: h * 0.55, vyötärö: h * 0.465, lantio: h * 0.52,
          hauis: h * 0.19, reisi: h * 0.31, pohje: h * 0.22, kaula: h * 0.215 };
    usedChips = {};
    const C = (site) => {
      const v = valueAsOf(site, dateStr);
      usedChips[site] = { v, real: v != null };
      return v != null ? v : defC[site];
    };
    const R = (c) => c / (2 * Math.PI); // ympärys -> säde (cm)
    const rNeck = R(C("kaula")), rChest = R(C("rintakehä")), rWaist = R(C("vyötärö"));
    const rHip = R(C("lantio")), rArm = R(C("hauis")), rThigh = R(C("reisi")), rCalf = R(C("pohje"));
    // Hartiaympärys -> visuaalinen puolileveys: ympärysmitta kiertää rinnan
    // ja hartiat, joten olkapäiden ulkoleveys on ~ympärys/2.4 (puolikas /4.8).
    // Aiempi /3.3 venytti hartiat kauas sivuille isoilla mitoilla. Lisäksi
    // rajataan suhteessa rintakehään ettei mittavirhe riko hahmoa.
    const shoulderRaw = C("hartia") / 4.8 * (female ? 0.95 : 1.0);
    const shoulderHalf = Math.max(rChest * 1.25, Math.min(shoulderRaw, rChest * 1.8));

    const chestK = female ? 1.15 : 1.26, chestD = female ? 0.9 : 0.8;
    const waistK = 1.1 - 0.12 * fat, waistD = 0.8 + 0.28 * fat;
    const hipK = female ? 1.28 : 1.18, hipD = 0.82 + 0.12 * fat;
    const belly = fat * rWaist * 0.5;              // maha VAIN eteenpäin
    const bust = female ? rChest * 0.3 : rChest * 0.06 * (1 - fat * 0.5);
    const butt = rHip * (female ? 0.3 : 0.22);      // pakarat taakse

    const Y = (f) => h * f;
    // --- Vartalo ---
    const torso = tube([
      { y: Y(0.845), w: rNeck * 1.02, d: rNeck * 1.02 },
      { y: Y(0.825), w: rNeck * 1.35, d: rNeck * 1.2 },
      { y: Y(0.80), w: shoulderHalf * 0.88, d: rChest * 0.72 },
      { y: Y(0.72), w: rChest * chestK, d: rChest * chestD, zc: bust * 0.5 },
      { y: Y(0.665), w: rChest * chestK * 0.97, d: rChest * chestD, zc: bust },
      { y: Y(0.60), w: rWaist * waistK, d: rWaist * waistD, zc: belly * 0.7 },
      { y: Y(0.555), w: (rWaist * waistK + rHip * hipK) / 2, d: (rWaist * waistD + rHip * hipD) / 2, zc: belly },
      { y: Y(0.52), w: rHip * hipK, d: rHip * hipD, zc: belly * 0.4 - butt * 0.25 },
      { y: Y(0.48), w: rHip * hipK * 0.93, d: rHip * hipD * 0.95, zc: -butt * 0.3 },
      { y: Y(0.44), w: rHip * hipK * 0.62, d: rHip * hipD * 0.7, zc: -butt * 0.12 },
    ], skin);
    group.add(torso);

    // --- Hartiat (deltoid-pallot) + kädet ---
    const armX = shoulderHalf * 0.98;
    [-1, 1].forEach((s) => {
      const delt = ell(rArm * 1.06, rArm * 1.15, rArm * 1.06, skin);
      delt.position.set(s * armX, Y(0.782), 0);
      group.add(delt);
      const ax = s * (armX + rArm * 0.15);
      const arm = tube([
        { y: Y(0.79), w: rArm * 0.98, d: rArm * 0.98 },
        { y: Y(0.70), w: rArm * 0.95, d: rArm * 0.95 },
        { y: Y(0.63), w: rArm * 0.78, d: rArm * 0.8 },
        { y: Y(0.54), w: rArm * 0.6, d: rArm * 0.62 },
        { y: Y(0.485), w: rArm * 0.5, d: rArm * 0.52 },
      ], skin);
      arm.position.x = ax;
      group.add(arm);
      const hand = ell(rArm * 0.42, rArm * 0.75, rArm * 0.5, skin);
      hand.position.set(ax, Y(0.45), 1);
      group.add(hand);
    });

    // --- Jalat + jalkaterät ---
    const legX = rHip * hipK * 0.5;
    [-1, 1].forEach((s) => {
      const leg = tube([
        { y: Y(0.50), w: rThigh * 1.02, d: rThigh * 1.06, zc: -butt * 0.15 },
        { y: Y(0.42), w: rThigh * 0.95, d: rThigh, zc: 0 },
        { y: Y(0.29), w: rThigh * 0.58, d: rThigh * 0.62 },
        { y: Y(0.22), w: rCalf * 0.95, d: rCalf * 1.05, zc: -rCalf * 0.15 },
        { y: Y(0.10), w: rCalf * 0.55, d: rCalf * 0.6 },
        { y: Y(0.03), w: rCalf * 0.5, d: rCalf * 0.55 },
      ], skin);
      leg.position.x = s * legX;
      group.add(leg);
      const foot = ell(4.4, 3.2, 12, skin);
      foot.position.set(s * legX, 3.2, 6.5);
      group.add(foot);
    });

    // --- Pää: kallo, nenä, korvat, silmät, hiukset ---
    const headR = h * 0.058;
    const hy = Y(0.845) + headR * 1.06;
    const headG = new THREE.Group();
    const skull = ell(headR * 0.78 * (1 + fat * 0.08), headR, headR * 0.84, skin);
    headG.add(skull);
    const nose = new THREE.Mesh(new THREE.ConeGeometry(headR * 0.13, headR * 0.32, 12), skin);
    nose.rotation.x = Math.PI / 2;
    nose.position.set(0, -headR * 0.12, headR * 0.82);
    nose.castShadow = true;
    headG.add(nose);
    [-1, 1].forEach((s) => {
      const ear = ell(headR * 0.1, headR * 0.22, headR * 0.16, skin);
      ear.position.set(s * headR * 0.78, -headR * 0.05, 0);
      headG.add(ear);
      const eye = ell(headR * 0.08, headR * 0.05, headR * 0.04, eyeM);
      eye.position.set(s * headR * 0.3, headR * 0.08, headR * 0.72);
      headG.add(eye);
    });
    // Hiukset: lakki + naisilla pitkät taakse
    const cap = ell(headR * 0.82, headR * 0.78, headR * 0.82, hairM);
    cap.position.set(0, headR * 0.34, -headR * 0.18);
    headG.add(cap);
    if (female) {
      const back = ell(headR * 0.72, headR * 1.5, headR * 0.5, hairM);
      back.position.set(0, -headR * 0.7, -headR * 0.55);
      headG.add(back);
    }
    headG.position.y = hy;
    // Pään varjo rintaan olisi liian raju -> pää ei heitä varjoa
    headG.traverse((o) => { o.castShadow = false; });
    group.add(headG);

    // Mittachipit
    chipRow.innerHTML = "";
    ["hartia", "rintakehä", "vyötärö", "lantio", "hauis", "reisi", "pohje"].forEach((s) => {
      const u = usedChips[s] || {};
      chipRow.append(el("span", { class: "tag", style: u.real ? "" : "opacity:0.45",
        title: u.real ? "Mitattu" : "Arvio — lisää mitta tarkentaaksesi" },
        `${s} ${u.v != null ? u.v + " cm" : "~"}`));
    });
  }

  // --- Pyöritys + animaatio ---
  const st = { dead: false, renderer, auto: true, dragging: false, lastX: 0 };
  _figState = st;
  group.rotation.y = 0.4;
  const cv = renderer.domElement;
  cv.addEventListener("pointerdown", (e) => {
    st.dragging = true; st.auto = false; st.lastX = e.clientX;
    try { cv.setPointerCapture(e.pointerId); } catch (err) {}
    cv.style.cursor = "grabbing";
  });
  cv.addEventListener("pointermove", (e) => {
    if (st.dragging) { group.rotation.y += (e.clientX - st.lastX) * 0.012; st.lastX = e.clientX; }
  });
  cv.addEventListener("pointerup", () => { st.dragging = false; cv.style.cursor = "grab"; });
  cv.addEventListener("dblclick", () => { st.auto = true; });

  function loop() {
    if (st.dead || !cv.isConnected) return;
    if (st.auto && !st.dragging) group.rotation.y += 0.006;
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  }

  // Näytä/piilota + aikajana
  const applyHidden = (hidden) => {
    area.style.display = hidden ? "none" : "";
    slideHost.style.display = hidden ? "none" : "";
    toggle.textContent = hidden ? "Näytä hahmo" : "Piilota hahmo";
  };
  const toggle = el("button", { class: "small", style: "margin-bottom:8px" });
  const slideHost = el("div");
  toggle.addEventListener("click", () => {
    const nowHidden = area.style.display !== "none";
    localStorage.setItem("figureHidden", nowHidden ? "1" : "0");
    applyHidden(nowHidden);
  });
  dateWrap.append(toggle, slideHost);
  if (dates.length > 1) {
    const slider = el("input", { type: "range", min: "0", max: String(dates.length - 1),
      value: String(dates.length - 1), style: "width:100%" });
    const lbl = el("div", { class: "muted", style: "text-align:center" }, dates[dates.length - 1]);
    slider.addEventListener("input", () => { lbl.textContent = dates[+slider.value]; buildModel(dates[+slider.value]); });
    slideHost.append(slider, lbl);
  }
  buildModel(dates[dates.length - 1]);
  applyHidden(localStorage.getItem("figureHidden") === "1");
  loop();
}

async function loadPhotos() {
  const gal = document.getElementById("photo-gallery");
  if (!gal) return;
  gal.innerHTML = "";
  const photos = await api.get(pq("/api/photos"));
  if (!photos.length) { gal.append(el("p", { class: "muted" }, "Ei kuvia vielä.")); return; }
  photos.forEach((p) => {
    const img = el("img", { src: p.url, alt: p.entry_date, loading: "lazy" });
    img.addEventListener("click", () => {
      const ov = el("div", { class: "pr-celebrate", onclick: () => ov.remove() },
        el("img", { src: p.url, style: "max-width:92vw;max-height:88vh;border-radius:10px" }));
      document.body.append(ov);
    });
    gal.append(el("div", { class: "photo-item" }, img,
      el("div", { class: "photo-meta" }, p.entry_date,
        el("button", { class: "small danger", onclick: async () => {
          if (confirm("Poista kuva?")) { await api.del(`/api/photos/${p.id}`); loadPhotos(); }
        } }, "×"))));
  });
}

document.getElementById("photo-add-btn").addEventListener("click", () => document.getElementById("photo-file").click());
document.getElementById("photo-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  const status = document.getElementById("photo-status");
  if (file.size > 12 * 1024 * 1024) { status.textContent = "Kuva liian suuri (max 12 MB)."; ev.target.value = ""; return; }
  status.textContent = "Ladataan…";
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      await api.post(pq("/api/photos"), {
        image_base64: reader.result, mime: file.type,
        entry_date: document.getElementById("photo-date").value || null,
      });
      status.textContent = "Kuva lisätty.";
      loadPhotos();
    } catch (e) { status.textContent = "Lisäys epäonnistui: " + e.message; }
  };
  reader.readAsDataURL(file);
  ev.target.value = "";
});

async function loadBody() {
  document.getElementById("b-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("m-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("photo-date").value = new Date().toISOString().slice(0, 10);
  const s = await api.get(pq("/api/body/summary"));
  renderBodyScore();
  renderBodypartLevels();
  renderBodyFigure(s.measurement_sites, s.height_cm, s.sex, s.composition ? s.composition.body_fat_pct : null);
  loadPhotos();
  loadBia();

  // Koostumus
  const comp = document.getElementById("composition");
  comp.innerHTML = "";

  // Kreatiini päällä/pois -kytkin: vaikuttaa koostumusarvioon (lihasvesi ≠ rasva)
  const creToggle = el("input", { type: "checkbox" });
  creToggle.checked = !!s.creatine;
  creToggle.addEventListener("change", async () => {
    await api.patch(`/api/profiles/${currentProfileId}`, { creatine: creToggle.checked });
    loadBody();
  });
  comp.append(el("label", { class: "btn-row", style: "align-items:center;gap:8px;margin:0 0 10px",
    title: "Kreatiini sitoo lihaksiin vettä (~1 kg). Se ei ole rasvaa, joten päällä ollessa rasvamassa lasketaan tarkemmin." },
    creToggle, el("span", {}, "Kreatiini käytössä")));

  if (s.composition) {
    const c = s.composition;
    comp.append(el("div", { class: "result-box" },
      el("div", {}, `Paino ${c.bodyweight} kg · rasva ${c.body_fat_pct}%` +
        (c.body_fat_source === "bia" ? (c.body_fat_estimated ? " (johdettu laitemittauksesta)" : " (laitemittaus)")
          : c.body_fat_source === "navy" ? " (arvioitu mitoista)" : "")),
      el("div", { class: "big" }, `Lihasmassa ~${c.lean_mass_kg} kg`),
      el("div", { class: "muted" },
        `Rasvamassa ~${c.fat_mass_kg} kg` +
        (c.bmi ? ` · BMI ${c.bmi}` : "") + (c.ffmi ? ` · FFMI ${c.ffmi}` : "") +
        (c.creatine_water_kg ? ` · josta kreatiinivettä ~${c.creatine_water_kg} kg (ei rasvaa)` : ""))));
    // Fysiikkataso (aloittelija → Mr. Olympia) segmentoituna palkkina
    if (s.physique) {
      const p = s.physique;
      const box = el("div", { style: "margin-top:12px" },
        el("div", { class: "row-between" },
          el("strong", {}, "Fysiikkataso"),
          el("span", { class: "tag main" }, `${p.level} (FFMI ${p.ffmi})`)));
      box.append(segLevelBar(p.levels, p.level_index, {
        shorts: ["Aloitt.", "Harrast.", "Keski", "Edist.", "Kokenut", "Eliitti", "Kilpa", "IFBB", "Olympia"],
      }));
      box.append(el("div", { class: "muted" }, p.next_level ? `Seuraava: ${p.next_level} @ FFMI ${p.next_ffmi}` : "Ylin taso saavutettu!"));
      comp.append(box);
    }
  } else {
    comp.append(el("p", { class: "muted" }, "Anna paino ja rasva-% nähdäksesi koostumusarvion."));
  }

  // Painokäyrä
  drawLineChart(document.getElementById("weight-chart"),
    [{ name: "Paino", points: s.weight_series.map((p) => ({ x: new Date(p.date).getTime(), y: p.value })) }], { unit: "kg" });

  // Mitat
  const legend = document.getElementById("measure-legend");
  legend.innerHTML = "";
  const series = [];
  let idx = 0;
  const fcs = s.measurement_forecasts || {};
  let hasFc = false;
  for (const [site, pts] of Object.entries(s.measurement_sites)) {
    const color = CHART_COLORS[idx % CHART_COLORS.length];
    series.push({ name: site, color, points: pts.map((p) => ({ x: new Date(p.date).getTime(), y: p.value })) });
    legend.append(el("span", { class: "tag", style: `color:${color};border-color:${color}` }, site));
    // Ennuste (katkoviiva + haarukka) jos dataa riittää
    if (fcs[site] && fcs[site].length && pts.length) {
      const last = pts[pts.length - 1];
      const anchor = { x: new Date(last.date).getTime(), y: last.value };
      const fc = fcs[site].map((p) => ({ x: new Date(p.date).getTime(), y: p.mid }));
      const band = fcs[site].map((p) => ({ x: new Date(p.date).getTime(), low: p.low, high: p.high }));
      series.push({ name: site, color, dashed: true, points: [anchor, ...fc], band });
      hasFc = true;
    }
    idx++;
  }
  if (hasFc) legend.append(el("span", { class: "muted" }, " — katkoviiva = ennuste (oman datan trendistä)"));
  drawLineChart(document.getElementById("measure-chart"), series, { unit: "cm" });

  // Painon opastus (7 pv keskiarvo + luonnollinen heilahtelu, ei säikäytä)
  renderWeightGuidance(s.weight_guidance);
  // Mittausohjeet (haetaan kerran)
  loadMeasureGuide();

  // Tulkinnat per mitta: suunta (kohina-/kadenssitietoinen), rauhoitus ja
  // voima–koko-yhteys (esim. reisi kasvaa + jalkavoima nousee = lihaskasvua).
  const ins = document.getElementById("measure-insights");
  ins.innerHTML = "";
  const insights = s.measurement_insights || {};
  const rows = Object.entries(insights);
  rows.forEach(([site, v]) => {
    const r = v.reading;
    const tone = r && r.status === "up" ? "var(--accent-2)"
      : r && r.status === "down" ? "#f59e0b" : "var(--muted)";
    const card = el("div", { class: "item", style: `margin-top:6px;border-left:3px solid ${tone}` },
      el("div", { class: "row-between" },
        el("strong", {}, site),
        el("span", { class: "muted" }, r ? `${r.current} cm` : "")));
    if (r) card.append(el("div", { style: `margin-top:3px;color:${tone}` }, r.message));
    if (r && r.reassure) card.append(el("div", { class: "muted", style: "margin-top:3px;font-size:0.85em" }, "🌊 " + r.reassure));
    if (v.strength_link) card.append(el("div", { style: "margin-top:3px;color:var(--accent);font-size:0.9em" }, "💪 " + v.strength_link));
    if (v.note) card.append(el("div", { class: "muted", style: "margin-top:3px;font-size:0.85em" }, v.note));
    if (v.ceiling) card.append(el("div", { class: "muted", style: "margin-top:2px;font-size:0.8em" }, `Arvioitu luonnollinen katto ~${v.ceiling} cm`));
    ins.append(card);
  });
}

function renderWeightGuidance(g) {
  const div = document.getElementById("weight-guidance");
  if (!div) return;
  div.innerHTML = "";
  if (!g) return;
  const box = el("div", { class: "result-box", style: "text-align:left" });
  if (g.avg7 != null) {
    box.append(el("div", {}, el("strong", {}, `7 pv keskiarvo: ${g.avg7} kg`),
      g.direction ? el("span", { class: "muted" }, ` · ${g.direction}`) : ""));
  }
  box.append(el("div", { class: "muted", style: "margin-top:4px;font-size:0.85em" }, g.message));
  div.append(box);
}

let _measureGuideLoaded = false;
async function loadMeasureGuide() {
  const body = document.getElementById("measure-guide-body");
  if (!body || _measureGuideLoaded) return;
  try {
    const g = await api.get("/api/body/measurement-guide");
    body.innerHTML = "";
    body.append(el("p", { class: "muted", style: "margin:8px 0" }, g.general));
    const ul = el("ul", { style: "margin:6px 0;padding-left:18px" });
    Object.entries(g.sites).forEach(([site, txt]) =>
      ul.append(el("li", { style: "margin:4px 0;color:var(--muted)" },
        el("strong", { style: "color:var(--text)" }, site + ": "), txt)));
    body.append(ul);
    body.append(el("p", { class: "muted", style: "margin:6px 0;font-size:0.88em" }, "⚖ " + g.weight));
    _measureGuideLoaded = true;
  } catch (e) { /* ohje ei kriittinen */ }
}

document.getElementById("b-save").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  // Uni tunteina + minuutteina -> desimaalitunnit (7 h 23 min = 7.38)
  let sleep = null;
  if (v("b-sleep") || v("b-sleep-min")) {
    sleep = (+v("b-sleep") || 0) + (+v("b-sleep-min") || 0) / 60;
    sleep = Math.round(sleep * 100) / 100;
  }
  const body = {
    entry_date: v("b-date") || null,
    bodyweight: v("b-weight") ? +v("b-weight") : null,
    body_fat_pct: v("b-bf") ? +v("b-bf") : null,
    sleep_hours: sleep,
    sleep_score: v("b-sscore") ? +v("b-sscore") : null,
    hrv: v("b-hrv") ? +v("b-hrv") : null,
    resting_hr: v("b-rhr") ? +v("b-rhr") : null,
    kcal: v("b-kcal") ? +v("b-kcal") : null,
    steps: v("b-steps") ? +v("b-steps") : null,
    water_l: v("b-water") ? +v("b-water") : null,
  };
  const saved = await api.post(pq("/api/body/entries"), body);
  ["b-weight", "b-bf", "b-sleep", "b-sleep-min", "b-sscore", "b-hrv", "b-rhr", "b-kcal", "b-steps", "b-water"].forEach((id) => (document.getElementById(id).value = ""));
  await loadBody();
  // Kerro jos rasva-% täyttyi automaattisesti laitemittauksesta
  if (body.bodyweight && !body.body_fat_pct && saved.body_fat_pct != null) {
    const est = document.getElementById("bia-estimate");
    if (est) est.prepend(el("div", { style: "color:var(--accent-2);margin-bottom:6px" },
      `✓ Rasva-% ${saved.body_fat_pct} % arvioitiin automaattisesti laitemittauksesta painollesi.`));
  }
});

document.getElementById("m-save").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  if (!v("m-site") || !v("m-value")) return alert("Anna kohta ja mitta.");
  await api.post(pq("/api/body/measurements"), {
    entry_date: v("m-date") || null, site: v("m-site").trim(), value_cm: +v("m-value"),
  });
  document.getElementById("m-value").value = "";
  loadBody();
});

// ---- BIA-kehonkoostumusmittaus (InBody tms.) ----
async function loadBia() {
  document.getElementById("bia-date").value = new Date().toISOString().slice(0, 10);
  const estDiv = document.getElementById("bia-estimate");
  const listDiv = document.getElementById("bia-list");
  estDiv.innerHTML = ""; listDiv.innerHTML = "";
  const [est, list] = await Promise.all([
    api.get(pq("/api/body/bia/estimate")), api.get(pq("/api/body/bia"))]);
  if (est.available) {
    const dm = est.muscle_change_kg;
    const df = est.fat_change_kg;
    const chg = (est.basis !== "anchor")
      ? ` · muutos ankkurista: rasva ${df > 0 ? "+" : ""}${df} kg, lihas ${dm > 0 ? "+" : ""}${dm} kg`
      : "";
    estDiv.append(el("div", { class: "result-box", style: "margin-bottom:10px" },
      el("div", { class: "big" }, `Rasva-% nyt ~${est.bf_pct} %`),
      el("div", { class: "muted" },
        `Ankkuri ${est.anchor_date}: ${est.anchor_bf_pct} % @ ${est.anchor_weight ?? "?"} kg` +
        (est.waist_delta_cm != null ? ` · vyötärö ${est.waist_delta_cm > 0 ? "+" : ""}${est.waist_delta_cm} cm` : "") + chg),
      el("div", { class: "muted", style: "font-size:0.85em;margin-top:3px" }, est.note)));
  } else {
    estDiv.append(el("p", { class: "muted" }, est.note));
  }
  list.forEach((b) => {
    const bits = [`rasva ${b.body_fat_pct} %`];
    if (b.weight_kg) bits.push(`${b.weight_kg} kg`);
    if (b.muscle_mass_kg) bits.push(`lihas ${b.muscle_mass_kg} kg`);
    if (b.fat_mass_kg) bits.push(`rasvaa ${b.fat_mass_kg} kg`);
    if (b.visceral_level != null) bits.push(`sis.rasva ${b.visceral_level}`);
    if (b.score != null) bits.push(`pisteet ${b.score}`);
    const seg = [];
    if (b.muscle_arms_kg) seg.push(`kädet ${b.muscle_arms_kg}`);
    if (b.muscle_legs_kg) seg.push(`jalat ${b.muscle_legs_kg}`);
    if (b.muscle_trunk_kg) seg.push(`keskiv. ${b.muscle_trunk_kg}`);
    listDiv.append(el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("strong", {}, `${b.entry_date}${b.device ? " · " + b.device : ""}`),
        el("button", { class: "small danger", onclick: async () => {
          if (confirm("Poista laitemittaus?")) { await api.del(`/api/body/bia/${b.id}`); loadBody(); }
        } }, "Poista")),
      el("div", { class: "muted" }, bits.join(" · ")),
      seg.length ? el("div", { class: "muted", style: "font-size:0.85em" }, `Lihasjakauma (kg): ${seg.join(" · ")}`) : ""));
  });
}

document.getElementById("bia-save").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  if (!v("bia-bf")) return alert("Rasva-% on pakollinen (laitteen tärkein lukema).");
  await api.post(pq("/api/body/bia"), {
    entry_date: v("bia-date") || null,
    weight_kg: v("bia-weight") ? +v("bia-weight") : null,
    body_fat_pct: +v("bia-bf"),
    muscle_mass_kg: v("bia-muscle") ? +v("bia-muscle") : null,
    fat_mass_kg: v("bia-fatkg") ? +v("bia-fatkg") : null,
    visceral_level: v("bia-visceral") ? +v("bia-visceral") : null,
    score: v("bia-score") ? +v("bia-score") : null,
    bmr_kcal: v("bia-bmr") ? +v("bia-bmr") : null,
    muscle_arms_kg: v("bia-arms") ? +v("bia-arms") : null,
    muscle_legs_kg: v("bia-legs") ? +v("bia-legs") : null,
    muscle_trunk_kg: v("bia-trunk") ? +v("bia-trunk") : null,
    device: v("bia-device").trim() || null,
  });
  ["bia-weight", "bia-bf", "bia-muscle", "bia-fatkg", "bia-visceral", "bia-score",
   "bia-bmr", "bia-arms", "bia-legs", "bia-trunk"].forEach((id) => (document.getElementById(id).value = ""));
  loadBody();
});

// =================== RUOKA ===================
let foodCats = [];
function nDate() {
  const inp = document.getElementById("n-date");
  if (!inp.value) inp.value = new Date().toISOString().slice(0, 10);
  return inp.value;
}

async function loadNutrition() {
  nDate();
  // Kategoriat valitsimeen
  if (!foodCats.length) {
    foodCats = await api.get("/api/nutrition/categories");
    const sel = document.getElementById("food-cat");
    foodCats.forEach((c) => sel.append(el("option", { value: c }, c)));
    const dl = document.getElementById("nf-cats");
    foodCats.forEach((c) => dl.append(el("option", {}, c)));
  }
  await renderFoodResults();
  await renderDayLog();
  await renderMeals();
}

async function renderFoodResults() {
  const q = document.getElementById("food-search").value.trim();
  const cat = document.getElementById("food-cat").value;
  const fav = document.getElementById("food-fav-only").checked;
  let path = "/api/nutrition/foods?";
  if (q) path += "q=" + encodeURIComponent(q) + "&";
  if (cat) path += "category=" + encodeURIComponent(cat) + "&";
  if (fav) path += "favorites=true";
  const foods = await api.get(path);
  const box = document.getElementById("food-results");
  box.innerHTML = "";
  if (!foods.length) { box.append(el("p", { class: "muted" }, "Ei osumia.")); return; }
  foods.slice(0, 60).forEach((f) => {
    const grams = el("input", { type: "number", value: f.default_grams ?? 100, style: "width:75px" });
    const star = el("button", { class: "small", title: "Suosikki", onclick: async () => {
      await api.patch(`/api/nutrition/foods/${f.id}`, { is_favorite: !f.is_favorite }); renderFoodResults();
    } }, f.is_favorite ? "★" : "☆");
    box.append(el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("div", {}, el("strong", {}, f.name),
          el("span", { class: "muted" }, ` · ${f.kcal} kcal · P${f.protein_g} H${f.carbs_g} R${f.fat_g} /100g`)),
        el("div", { class: "btn-row", style: "align-items:center" }, star, grams, el("span", { class: "muted" }, "g"),
          el("button", { class: "small primary", onclick: async () => {
            await api.post(pq("/api/nutrition/logs") + "&on_date=" + nDate(),
              { food_id: f.id, grams: +grams.value || f.default_grams || 100 });
            renderDayLog();
          } }, "Kirjaa")))));
  });
}

async function renderRecentFoods() {
  const box = document.getElementById("recent-foods");
  if (!box) return;
  box.innerHTML = "";
  const foods = await api.get(pq("/api/nutrition/recent"));
  if (!foods.length) return;
  box.append(el("span", { class: "muted", style: "align-self:center" }, "Pikakirjaa:"));
  foods.forEach((f) => {
    box.append(el("button", { class: "small", title: `${f.kcal} kcal /100g`, onclick: async () => {
      await api.post(pq("/api/nutrition/logs") + "&on_date=" + nDate(),
        { food_id: f.id, grams: f.default_grams || 100 });
      renderDayLog();
    } }, `+ ${f.name}`));
  });
}

async function renderDayLog() {
  renderRecentFoods();
  const s = await api.get(pq("/api/nutrition/summary") + "&on_date=" + nDate());
  const t = s.today;
  // Yhteenveto + liikaa/liian vähän -arvio dieettitavoitteeseen nähden
  const today = document.getElementById("nutrition-today");
  today.innerHTML = "";
  const box = el("div", { class: "result-box" },
    el("div", { class: "big" }, `${Math.round(t.kcal)} kcal`),
    el("div", { class: "muted" }, `Proteiini ${Math.round(t.protein_g)} g · hiilarit ${Math.round(t.carbs_g)} g · rasva ${Math.round(t.fat_g)} g`));
  // 7 pv keskiarvo: vakaa vertailuluku (yksittäinen päivä heiluu paljon)
  const a = s.avg7;
  if (a && a.days_logged >= 2) {
    box.append(el("div", { style: "margin-top:8px;padding-top:8px;border-top:1px solid var(--border-soft)" },
      el("div", {}, el("strong", {}, `7 pv keskiarvo: ${Math.round(a.kcal)} kcal/pv`),
        el("span", { class: "muted" }, ` (${a.days_logged} kirjattua pv)`)),
      el("div", { class: "muted" }, `Proteiini ${Math.round(a.protein_g)} g · hiilarit ${Math.round(a.carbs_g)} g · rasva ${Math.round(a.fat_g)} g — tämä on vakain kuva`)));
  }
  let dietTargets = null;
  try {
    const diet = await api.get(pq("/api/diet/status"));
    if (diet.targets) {
      dietTargets = diet.targets;
      const tgt = diet.targets.kcal;
      // Vertaa ENSISIJAISESTI 7 pv keskiarvoon jos dataa on — yksittäinen
      // päivä ei kerro liikaa/liian vähän, useamman päivän tahti kertoo.
      const useAvg = a && a.days_logged >= 3;
      const cmp = useAvg ? a.kcal : t.kcal;
      const label = useAvg ? "7 pv keskiarvo" : "Tänään";
      if (cmp > 0) {
        const diff = Math.round(cmp - tgt);
        let msg;
        if (diff < -300) msg = `${label} ${Math.abs(diff)} kcal alle tavoitteen (${tgt}) — syönti jää liian vähäiseksi.`;
        else if (diff > 300) msg = `${label} ${diff} kcal yli tavoitteen (${tgt}) — syöt tavoitetta enemmän.`;
        else msg = `${label} tavoitteessa (${tgt} kcal ±300).`;
        box.append(el("div", { class: "muted", style: "margin-top:6px" }, msg));
        const cmpP = useAvg ? a.protein_g : t.protein_g;
        if (cmpP < diet.targets.protein_g * 0.8)
          box.append(el("div", { class: "muted" }, `Proteiinia jää tavoitteesta (${diet.targets.protein_g} g) — lisää proteiinia.`));
      }
    }
  } catch (e) {}
  today.append(box);

  // Saman päivän korjaavat neuvot (herkkuvoittoinen / yli tavoitteen päivä)
  if (s.today_advice && s.today_advice.tips && s.today_advice.tips.length) {
    const adv = el("div", { class: "result-box", style: "margin-top:10px;border-color:var(--warn)" },
      el("strong", {}, "💡 Näin korjaat loppupäivän ja huomisen"));
    s.today_advice.tips.forEach((t) => adv.append(el("div", { class: "muted", style: "margin-top:4px" }, "• " + t)));
    today.append(adv);
  }

  const logs = await api.get(pq("/api/nutrition/logs") + "&on_date=" + nDate());
  const log = document.getElementById("today-log");
  log.innerHTML = "";
  if (!logs.length) log.append(el("p", { class: "muted" }, "Ei kirjauksia tälle päivälle."));
  logs.forEach((l) => {
    const g = el("input", { type: "number", value: l.grams, style: "width:75px" });
    g.addEventListener("change", async () => { await api.patch(`/api/nutrition/logs/${l.id}`, { grams: +g.value }); renderDayLog(); });
    log.append(el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("span", {}, l.food.name),
        el("div", { class: "btn-row", style: "align-items:center" }, g, el("span", { class: "muted" }, "g"),
          el("span", { class: "muted" }, `${Math.round(l.food.kcal * l.grams / 100)} kcal`),
          el("button", { class: "small danger", onclick: async () => { await api.del(`/api/nutrition/logs/${l.id}`); renderDayLog(); } }, "x")))));
  });

  // Kalorit & makrot omissa paneeleissaan (oikeat yksiköt, ei normalisointia)
  renderIntakePanels(s.timeline, dietTargets);
}

// Kalorit ja makrot erillisiin paneeleihin: kalorit omalla asteikolla (+ tavoite
// katkoviivana), makrot grammoina samassa paneelissa (sama yksikkö -> vertailtava).
function renderIntakePanels(timeline, targets) {
  const wrap = document.getElementById("intake-panels");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!timeline || timeline.length < 2) {
    wrap.append(el("p", { class: "muted" }, "Kirjaa ruokaa muutamana päivänä, niin kehitys näkyy tässä."));
    return;
  }
  const xs = timeline.map((p) => new Date(p.date).getTime());
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const targetLine = (val) => (val ? { name: "tavoite", dashed: true, color: "#9aa3b2",
    points: [{ x: x0, y: val }, { x: x1, y: val }] } : null);

  // Paneeli 1: kalorit (+ tavoite jos dieetti käytössä)
  const kcalPanel = el("div", { class: "recovery-panel" });
  kcalPanel.append(el("div", { class: "row-between", style: "align-items:baseline" },
    el("strong", {}, "Kalorit"),
    el("span", { class: "muted", style: "font-size:0.8rem" },
      targets && targets.kcal ? `tavoite ${Math.round(targets.kcal)} kcal/pv` : "kcal/pv")));
  const kcalCanvas = el("canvas", { width: 820, height: 150 });
  kcalPanel.append(kcalCanvas);
  wrap.append(kcalPanel);
  const kcalSeries = [{ name: "Kalorit", color: CHART_COLORS[0],
    points: timeline.map((p) => ({ x: new Date(p.date).getTime(), y: p.kcal })) }];
  const kt = targetLine(targets && targets.kcal);
  if (kt) kcalSeries.push(kt);
  // Ei yksikköä akselille: "2400 kcal" ei mahdu kapeaan marginaaliin ja
  // otsikko kertoo jo yksikön. Pelkkä luku (2400) pysyy luettavana.
  drawLineChart(kcalCanvas, kcalSeries, {});

  // Paneeli 2: makrot grammoina (proteiini/hiilarit/rasva, sama yksikkö)
  const macroPanel = el("div", { class: "recovery-panel" });
  const legend = el("div", { class: "btn-row" });
  const macros = [["protein_g", "Proteiini", CHART_COLORS[1]],
                  ["carbs_g", "Hiilarit", CHART_COLORS[2]], ["fat_g", "Rasva", CHART_COLORS[3]]];
  macros.forEach(([k, label, color]) =>
    legend.append(el("span", { class: "tag", style: `color:${color};border-color:${color}` }, label)));
  macroPanel.append(el("div", { class: "row-between", style: "align-items:baseline;flex-wrap:wrap;gap:6px" },
    el("strong", {}, "Makrot (g)"), legend));
  const macroCanvas = el("canvas", { width: 820, height: 150 });
  macroPanel.append(macroCanvas);
  wrap.append(macroPanel);
  const macroSeries = macros.map(([k, label, color]) => ({ name: label, color,
    points: timeline.map((p) => ({ x: new Date(p.date).getTime(), y: p[k] })) }));
  const pt = targetLine(targets && targets.protein_g);
  if (pt) { pt.name = "proteiinitavoite"; macroSeries.push(pt); }
  drawLineChart(macroCanvas, macroSeries, { unit: "g" });
}

document.getElementById("n-date").addEventListener("change", renderDayLog);
document.getElementById("meal-search").addEventListener("input", renderMeals);
document.getElementById("food-search").addEventListener("input", renderFoodResults);
document.getElementById("food-cat").addEventListener("change", renderFoodResults);
document.getElementById("food-fav-only").addEventListener("change", renderFoodResults);

// ---- Omat ateriat ----
async function renderMeals() {
  let meals = await api.get(pq("/api/nutrition/meals"));
  const q = (document.getElementById("meal-search")?.value || "").trim().toLowerCase();
  if (q) {
    meals = meals.filter((m) =>
      m.name.toLowerCase().includes(q) ||
      m.items.some((it) => it.food.name.toLowerCase().includes(q)));
  }
  const list = document.getElementById("meals-list");
  list.innerHTML = "";
  if (!meals.length) {
    list.append(el("p", { class: "muted" }, q ? "Ei osumia haulle." : "Ei tallennettuja aterioita vielä."));
  }
  meals.forEach((m) => {
    const kcal = m.items.reduce((a, it) => a + it.food.kcal * it.grams / 100, 0);
    list.append(el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("div", {}, el("strong", {}, m.name),
          el("div", { class: "muted" }, m.items.map((it) => `${it.food.name} ${it.grams}g`).join(" + ") + ` · ${Math.round(kcal)} kcal`)),
        el("div", { class: "btn-row" },
          el("button", { class: "small primary", onclick: async () => {
            await api.post(`/api/nutrition/meals/${m.id}/log?profile_id=${currentProfileId}&on_date=${nDate()}`);
            renderDayLog();
          } }, "Kirjaa"),
          el("button", { class: "small danger", onclick: async () => { await api.del(`/api/nutrition/meals/${m.id}`); renderMeals(); } }, "Poista")))));
  });
}

document.getElementById("new-meal-btn").addEventListener("click", async () => {
  const editor = document.getElementById("meal-editor");
  editor.classList.remove("hidden");
  editor.innerHTML = "";
  const name = el("input", { placeholder: "Aterian nimi (esim. Smoothie)" });
  const items = []; // {food_id, grams}
  const itemsBox = el("div", { class: "list", style: "margin-top:8px" });
  const totals = el("div", { class: "muted", style: "margin-top:4px" });
  const allFoods = await api.get("/api/nutrition/foods");
  const byId = {};
  allFoods.forEach((f) => (byId[f.id] = f));

  function renderTotals() {
    let kcal = 0, prot = 0;
    items.forEach((it) => { const f = byId[it.food_id]; kcal += f.kcal * it.grams / 100; prot += f.protein_g * it.grams / 100; });
    totals.textContent = items.length ? `Yhteensä ~${Math.round(kcal)} kcal · ${Math.round(prot)} g proteiinia` : "";
  }
  function renderItems() {
    itemsBox.innerHTML = "";
    items.forEach((it, i) => {
      const f = byId[it.food_id];
      const g = el("input", { type: "number", value: it.grams, style: "width:75px",
        oninput: (e) => { it.grams = +e.target.value || 0; renderTotals(); } });
      itemsBox.append(el("div", { class: "btn-row", style: "align-items:center" },
        el("strong", { style: "flex:1;min-width:120px" }, f.name), g, el("span", { class: "muted" }, "g"),
        el("button", { class: "small danger", onclick: () => { items.splice(i, 1); renderItems(); } }, "x")));
    });
    renderTotals();
  }

  // Haku: kirjoita -> osumat listana -> klikkaa lisätäksesi (ei scrollattavaa valikkoa)
  const search = el("input", { placeholder: "Hae ja lisää ruoka (esim. kaura, kana)…", style: "flex:1;min-width:160px" });
  const results = el("div", { class: "list", style: "max-height:220px;overflow:auto;margin-top:6px" });
  function renderResults() {
    const q = search.value.trim().toLowerCase();
    results.innerHTML = "";
    if (!q) return;
    const hits = allFoods.filter((f) => f.name.toLowerCase().includes(q)).slice(0, 12);
    if (!hits.length) { results.append(el("p", { class: "muted" }, "Ei osumia — voit lisätä oman ruoan alempaa.")); return; }
    hits.forEach((f) => {
      results.append(el("div", { class: "item", style: "cursor:pointer", onclick: () => {
        items.push({ food_id: f.id, grams: f.default_grams || 100 });
        search.value = ""; renderResults(); renderItems(); search.focus();
      } },
        el("div", { class: "row-between" },
          el("span", {}, f.name),
          el("span", { class: "muted" }, `${f.kcal} kcal/100g · lisää +`))));
    });
  }
  search.addEventListener("input", renderResults);

  editor.append(el("div", { class: "card" },
    el("label", {}, "Nimi", name),
    el("div", { class: "btn-row", style: "margin-top:8px" }, search),
    results, itemsBox, totals,
    el("div", { class: "btn-row", style: "margin-top:8px" },
      el("button", { class: "success", onclick: async () => {
        if (!name.value.trim() || !items.length) return alert("Anna nimi ja vähintään yksi ruoka.");
        await api.post(`/api/nutrition/meals?profile_id=${currentProfileId}`, { name: name.value.trim(), items });
        editor.classList.add("hidden"); renderMeals();
      } }, "Tallenna ateria"),
      el("button", { class: "small", onclick: () => editor.classList.add("hidden") }, "Peruuta"))));
  search.focus();
});

document.getElementById("nf-save").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  if (!v("nf-name").trim()) return alert("Anna ruoalle nimi.");
  try {
    await api.post("/api/nutrition/foods", {
      name: v("nf-name").trim(), category: v("nf-cat").trim() || null,
      kcal: +v("nf-kcal") || 0, protein_g: +v("nf-prot") || 0,
      carbs_g: +v("nf-carb") || 0, fat_g: +v("nf-fat") || 0,
      fiber_g: +v("nf-fiber") || 0, sugar_g: +v("nf-sugar") || 0, sodium_mg: +v("nf-sodium") || 0,
      default_grams: v("nf-grams") ? +v("nf-grams") : null,
    });
    ["nf-name", "nf-cat", "nf-kcal", "nf-prot", "nf-carb", "nf-fat", "nf-fiber", "nf-sugar", "nf-sodium", "nf-grams"].forEach((id) => (document.getElementById(id).value = ""));
    foodCats = []; loadNutrition();
  } catch (e) { alert("Virhe: " + e.message); }
});

// =================== DIEETTI ===================
let dietModelsCache = [];

async function loadDiet() {
  dietModelsCache = await api.get("/api/diet/models");
  const sel = document.getElementById("diet-model");
  sel.innerHTML = "";
  dietModelsCache.forEach((m) => sel.append(el("option", { value: m.id }, `${m.name} (${m.target_rate >= 0 ? "+" : ""}${m.target_rate} kg/vk)`)));
  const showInfo = () => {
    const m = dietModelsCache.find((x) => x.id === sel.value);
    document.getElementById("diet-model-info").textContent = m ? m.info : "";
  };
  sel.onchange = showInfo;

  const phase = await api.get(pq("/api/diet/phase"));
  if (phase) { sel.value = dietModelsCache.find((m) => m.name === phase.model)?.id || sel.value; }
  showInfo();
  await renderDietStatus();
}

document.getElementById("diet-start").addEventListener("click", async () => {
  const model = document.getElementById("diet-model").value;
  await api.post("/api/diet/phase", { profile_id: currentProfileId, model });
  renderDietStatus();
});

document.getElementById("mp-go").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  const path = `/api/diet/meal-plan?meals=${+v("mp-meals") || 4}` +
    `&wake=${v("mp-wake")}&sleep=${v("mp-sleep")}` + (v("mp-train") ? `&training=${v("mp-train")}` : "");
  const r = await api.get(pq(path));
  const div = document.getElementById("mp-result");
  div.innerHTML = "";
  if (!r.meals || !r.meals.length) {
    div.append(el("p", { class: "muted" }, r.message || "Ei aikataulua.")); return;
  }
  if (r.fasting) div.append(el("div", { class: "muted", style: "margin:8px 0" }, "16:8-paasto: syönti-ikkuna rajattu."));
  const tbl = el("table", {});
  tbl.append(el("tr", {}, el("th", {}, "Aika"), el("th", {}, "Ateria"),
    el("th", {}, "kcal"), el("th", {}, "P"), el("th", {}, "H"), el("th", {}, "R"), el("th", {}, "")));
  r.meals.forEach((m) => tbl.append(el("tr", {},
    el("td", {}, m.time), el("td", {}, m.label), el("td", {}, String(m.kcal)),
    el("td", {}, `${m.protein_g}g`), el("td", {}, `${m.carbs_g}g`), el("td", {}, `${m.fat_g}g`),
    el("td", { class: "muted" }, m.note || ""))));
  div.append(tbl);
});

async function renderDietStatus() {
  const s = await api.get(pq("/api/diet/status"));
  const div = document.getElementById("diet-status");
  div.innerHTML = "";
  if (s.message && !s.targets) {
    div.append(el("div", { class: "card muted" }, s.message));
    return;
  }
  const t = s.targets;
  // Tavoitekortti
  div.append(el("div", { class: "card" },
    el("h3", {}, `Tavoite: ${s.model || s.goal} (${s.target_rate >= 0 ? "+" : ""}${s.target_rate} kg/vk)`),
    el("div", { class: "grid" },
      el("div", { class: "result-box" }, el("div", { class: "muted" }, "Päivätavoite"),
        el("div", { class: "big" }, `${t.kcal} kcal`),
        el("div", { class: "muted" }, `P ${t.protein_g}g · H ${t.carbs_g}g · R ${t.fat_g}g`)),
      el("div", { class: "result-box" }, el("div", { class: "muted" }, "Ylläpito (TDEE)"),
        el("div", { class: "big" }, `${t.tdee} kcal`),
        el("div", { class: "muted" }, `Vaje/ylijäämä ${t.daily_delta} kcal/pv`)))));
  // TDEE:n lähde ja luottamus + mitä dataa vielä tarvitaan (ei hätiköintiä)
  const confTone = { korkea: "var(--accent-2)", kohtalainen: "var(--warn)", matala: "var(--muted)", "ei dataa": "var(--muted)" }[s.tdee_confidence] || "var(--muted)";
  const tdeeCard = div.lastChild;
  tdeeCard.append(el("div", { class: "muted", style: "margin-top:8px" },
    el("span", { class: "tag", style: `color:${confTone};border-color:${confTone}` },
      `Tarve: ${s.tdee_source} · luottamus ${s.tdee_confidence}`)));
  if (s.tdee_note) tdeeCard.append(el("div", { class: "muted", style: "margin-top:4px;font-size:0.85em" }, s.tdee_note));
  if (s.tdee_data_needs && s.tdee_data_needs.length)
    tdeeCard.append(el("div", { class: "muted", style: "margin-top:4px;color:var(--warn)" },
      "Tarkempaan arvioon: " + s.tdee_data_needs.join(", ") + "."));
  if (s.phase_note)
    tdeeCard.append(el("div", { class: "result-box", style: "margin-top:8px" }, "🎯 " + s.phase_note));

  // Per-päivä-tavoitteet (treeni- vs lepopäivä)
  const dt = s.day_targets;
  if (dt && dt.cycled) {
    const dayCard = (title, m, hint) => el("div", { class: "result-box" },
      el("div", { class: "muted" }, title),
      el("div", { class: "big" }, `${m.kcal} kcal`),
      el("div", { class: "muted" }, `P ${m.protein_g}g · H ${m.carbs_g}g · R ${m.fat_g}g`),
      el("div", { class: "muted" }, hint));
    div.append(el("div", { class: "card" },
      el("h3", {}, `Per-päivä-tavoitteet (${dt.training_days_per_week} treenipäivää/vk)`),
      el("p", { class: "muted" }, "Viikkokeskiarvo pysyy tavoitteessa — treenipäivinä enemmän hiilareita suorituskykyyn, lepopäivinä vähemmän."),
      el("div", { class: "grid" },
        dayCard("Treenipäivä", dt.train_day, "enemmän hiilaria"),
        dayCard("Lepopäivä", dt.rest_day, "vähemmän hiilaria, hieman enemmän rasvaa"))));
  }

  // Viikkoyhteenveto
  const wr = s.weekly_review;
  if (wr) {
    const parts = [`Viikkotavoite ${wr.target_weekly_kcal} kcal`];
    if (wr.actual_weekly_kcal != null) parts.push(`toteutunut ${wr.actual_weekly_kcal} kcal`);
    if (wr.adherence_pct != null) parts.push(`osuvuus ${wr.adherence_pct} %`);
    div.append(el("div", { class: "card" }, el("h3", {}, "Viikkoyhteenveto"),
      el("div", { class: "muted" }, parts.join(" · ")),
      wr.verdict ? el("div", { class: "result-box", style: "margin-top:10px" }, wr.verdict) : ""));
  }

  // Trendi & suositus
  div.append(el("div", { class: "card" },
    el("h3", {}, "Kehitys (viikkokeskiarvo)"),
    el("div", { class: "muted" },
      `Paino ${s.week_avg_weight ?? "—"} kg · trendi ${s.trend_kg_per_week != null ? (s.trend_kg_per_week >= 0 ? "+" : "") + s.trend_kg_per_week + " kg/vk" : "—"}` +
      (s.intake_avg_kcal ? ` · keskisyönti ${s.intake_avg_kcal} kcal${s.intake_estimated ? " (arvioitu painokehityksestä)" : ""}` : "")),
    el("div", { class: "result-box", style: "margin-top:10px" }, s.recommendation)));

  // Makrojako mukautettu omaan syömistyyliin
  if (s.targets && s.targets.style_note) {
    div.append(el("div", { class: "muted", style: "margin-top:6px" }, "🍽 " + s.targets.style_note));
  }

  // Ruokavalion laadun arvio (monipäiväinen, pisteet + järkevämpi lähestymistapa)
  const nq = s.nutrition_quality;
  if (nq && nq.available) {
    const tone = { hyva: "var(--accent-2)", kohtalainen: "var(--warn)", heikko: "var(--danger)" }[nq.level];
    const card = el("div", { class: "card" },
      el("h3", {}, "Ruokavalion laatu"),
      el("div", { class: "result-box", style: `border-color:${tone}` },
        el("div", { class: "row-between" },
          el("div", { class: "big", style: `color:${tone}` }, `${nq.score}/100`),
          el("span", { class: "tag", style: `color:${tone};border-color:${tone}` }, nq.label)),
        el("div", { class: "muted", style: "margin-top:6px" }, `Arvio ${nq.n_days} kirjatusta päivästä (toistuvat valinnat).`),
        el("div", { style: "margin-top:8px" }, el("strong", {}, "Järkevämpi lähestymistapa: "),
          el("span", {}, nq.better_approach))));
    if (nq.energy_note)
      card.querySelector(".result-box").append(
        el("div", { class: "muted", style: "margin-top:8px;color:var(--warn)" }, "⚡ " + nq.energy_note));
    if (nq.issues && nq.issues.length) {
      nq.issues.forEach((i) => card.append(el("div", { class: "item", style: "border-left:3px solid " + tone },
        el("div", { class: "muted" }, i.text))));
    }
    div.append(card);
  } else if (s.food_notes && s.food_notes.length) {
    // Vähemmän dataa: näytä yksittäiset huomiot
    const card = el("div", { class: "card" }, el("h3", {}, "Ruokavalion huomiot"));
    s.food_notes.forEach((n) => card.append(el("div", { class: "item", style: "border-left:3px solid #f59e0b" },
      el("div", { class: "muted" }, n))));
    div.append(card);
  }

  // Alkoholin vaikutusten seuranta (30 pv kuorma + oma mitattu vaste)
  try {
    const al = await api.get(pq("/api/diet/alcohol"));
    if (al && al.available) {
      const card = el("div", { class: "card" }, el("h3", {}, "🍺 Alkoholi & vaikutukset"));
      if (!al.any_use) {
        card.append(el("div", { class: "muted" }, al.note));
      } else {
        const tone = { matala: "var(--accent-2)", kohtalainen: "var(--warn)", korkea: "var(--danger)" }[al.level];
        card.append(el("div", { class: "result-box", style: `border-color:${tone}` },
          el("div", { class: "row-between" },
            el("div", { class: "big", style: `color:${tone}` }, `${al.drinks_30d} annosta / 30 pv`),
            el("span", { class: "tag", style: `color:${tone};border-color:${tone}` }, al.label)),
          el("div", { class: "muted", style: "margin-top:4px" },
            `${al.weekly_drinks} annosta/vk · ${al.total_g_30d} g puhdasta alkoholia · juomapäiviä ${al.drinking_days} · ` +
            `kertaryöppyjä ${al.binge_days} (raja ${al.binge_threshold_g} g)`),
          el("div", { class: "muted", style: "margin-top:4px" },
            `Suurin kerta ~${al.max_session_drinks} annosta (elimistö selviää ~${al.hours_to_sober_max} h).`)));
        card.append(el("div", { class: "item", style: `border-left:3px solid ${tone};margin-top:8px` },
          el("strong", {}, "Rytmi: "), el("span", { class: "muted" }, al.pattern_note)));
        // Oma mitattu vaste (jos dataa)
        if (al.measured_notes && al.measured_notes.length) {
          const mb = el("div", { style: "margin-top:8px" }, el("strong", {}, "Oma mitattu vaste:"));
          al.measured_notes.forEach((n) => mb.append(el("div", { class: "muted", style: "margin-top:3px" }, "📉 " + n)));
          card.append(mb);
        }
        card.append(el("div", { class: "muted", style: "margin-top:8px" }, "💡 " + al.guidance));
      }
      div.append(card);
    }
  } catch (e) {}

  // Kardio-/lämmittelyvinkki tavoitteen mukaan
  if (s.cardio_tip) {
    div.append(el("div", { class: "card" }, el("h3", {}, "Kardio & kulutus"),
      el("div", { class: "muted" }, s.cardio_tip)));
  }

  // Voiman seuranta dieetillä
  if (s.strength_note) {
    div.append(el("div", { class: "card" }, el("h3", {}, "Voiman seuranta"),
      el("div", { class: "muted" }, s.strength_note)));
  }

  // Vyötärö / bulk-raja
  if (s.waist && s.waist.message) {
    div.append(el("div", { class: "card" }, el("h3", {}, "Vyötärö"),
      el("div", { class: "muted" }, s.waist.message)));
  }

  // Kehon alueet
  if (s.body_areas && s.body_areas.areas.length) {
    const card = el("div", { class: "card" }, el("h3", {}, "Kehon alueiden kehitys"));
    const tbl = el("table", {});
    tbl.append(el("tr", {}, el("th", {}, "Kohta"), el("th", {}, "Nyt (cm)"), el("th", {}, "Muutos"), el("th", {}, "Huomio")));
    s.body_areas.areas.forEach((a) => tbl.append(el("tr", {},
      el("td", {}, a.site), el("td", {}, String(a.latest_cm)),
      el("td", {}, `${a.change_cm >= 0 ? "+" : ""}${a.change_cm} cm`), el("td", { class: "muted" }, a.note || ""))));
    card.append(tbl);
    div.append(card);
  }
}

// =================== PALAUTUMINEN & KORRELAATIO ===================
function normalize01to100(points) {
  const ys = points.map((p) => p.y);
  const lo = Math.min(...ys), hi = Math.max(...ys);
  return points.map((p) => ({ x: p.x, y: hi === lo ? 50 : ((p.y - lo) / (hi - lo)) * 100 }));
}

async function loadReadiness() {
  const card = document.getElementById("readiness-card");
  const div = document.getElementById("readiness-content");
  const r = await api.get(pq("/api/recovery/readiness"));
  if (!r.has_data) { card.style.display = "none"; return; }
  card.style.display = "";
  div.innerHTML = "";
  const color = r.score >= 80 ? "var(--accent-2)" : r.score >= 60 ? "#f59e0b" : "#ef4444";
  div.append(el("div", { class: "result-box" },
    el("div", { class: "muted" }, "Valmiuspisteet"),
    el("div", { class: "big", style: `color:${color}` }, `${r.score}/100`),
    el("div", { style: `color:${color};font-weight:600` }, r.status)));
  div.append(el("div", { class: "level-bar", style: "margin:8px 0" },
    el("div", { class: "level-fill", style: `width:${r.score}%;background:${color}` })));
  if (r.warnings.length) {
    const w = el("div", { style: "margin-top:8px" });
    r.warnings.forEach((msg) => w.append(el("div", { style: "color:#f59e0b;margin:3px 0" }, "⚠ " + msg)));
    div.append(w);
  } else {
    div.append(el("div", { class: "muted", style: "margin-top:6px" }, "Ei varoituksia — keho vaikuttaa palautuneelta."));
  }
  if (r.thin_data) {
    div.append(el("div", { class: "muted", style: "margin-top:6px" },
      "Osasta mittareista on vielä vähän dataa — hälytykset annetaan vasta kun pitkän ajan vertailu on luotettava. Kirjaa unta/HRV:tä/sykettä säännöllisesti."));
  }
  if (r.deload_recommended) {
    div.append(el("div", { style: "margin-top:10px;padding:10px;border-radius:10px;background:rgba(239,68,68,0.12);border:1px solid #ef4444" },
      el("strong", { style: "color:#ef4444" }, "🛑 Kevennysviikko suositeltu"),
      el("div", { class: "muted", style: "margin-top:4px" }, r.deload_message)));
  } else if (r.load_caution) {
    // Kuorma nousi mutta palautuminen kunnossa -> huomautus, ei pakotettu kevennys
    div.append(el("div", { style: "margin-top:10px;padding:10px;border-radius:10px;background:rgba(245,158,11,0.12);border:1px solid #f59e0b" },
      el("strong", { style: "color:#f59e0b" }, "⚠ Kuorma nousi — seuraa tuntumaa"),
      el("div", { class: "muted", style: "margin-top:4px" }, r.load_caution)));
  }
  // Tekijät
  const tbl = el("table", { style: "margin-top:8px" });
  tbl.append(el("tr", {}, el("th", {}, "Tekijä"), el("th", {}, "Nyt (7pv)"), el("th", {}, "Vertailu"), el("th", {}, "Muutos")));
  r.factors.forEach((f) => tbl.append(el("tr", {},
    el("td", {}, f.name), el("td", {}, String(f.recent)),
    el("td", {}, String(f.baseline)),
    el("td", {}, f.change_pct != null ? `${f.change_pct > 0 ? "+" : ""}${f.change_pct}%` : "—"))));
  div.append(tbl);
  if (r.acwr) {
    const a = r.acwr;
    div.append(el("div", { class: "muted", style: "margin-top:6px",
      title: a.note || "Akuutti (viim. 7 pv) vs. krooninen (edeltävien 4 vk ka.) treenikuorma. 0.8–1.3 = optimaalinen, yli 1.5 = piikki." },
      a.acwr != null
        ? `Kuormasuhde ACWR ${a.acwr} (${a.zone})` +
          (a.acute_load != null ? ` · akuutti ${a.acute_load} vs. krooninen ~${a.chronic_weekly_avg}/vk` : "")
        : `Kuormasuhde ACWR: ${a.note}`));
  }
}

async function loadCardio() {
  const data = await api.get(pq("/api/recovery/cardio/trend"));
  const list = await api.get(pq("/api/recovery/cardio"));
  document.getElementById("cardio-summary").innerHTML = "";
  document.getElementById("cardio-summary").append(el("div", { class: "muted" },
    `Tällä viikolla: ${data.week_sessions} kertaa · ${data.week_minutes} min · ${data.week_kcal} kcal`));

  // Aerobinen kehitys: keskinopeus (km/h) ajan yli, jos matka+aika kirjattu
  const speedPts = data.points.filter((p) => p.speed_kmh != null)
    .map((p) => ({ x: new Date(p.date).getTime(), y: p.speed_kmh }));
  const hrPts = data.points.filter((p) => p.avg_hr != null)
    .map((p) => ({ x: new Date(p.date).getTime(), y: p.avg_hr }));
  const series = [];
  if (speedPts.length >= 2) series.push({ name: "Nopeus", points: speedPts, color: CHART_COLORS[1] });
  if (hrPts.length >= 2) series.push({ name: "Keskisyke (norm.)", points: normalize01to100(hrPts), color: CHART_COLORS[3] });
  drawLineChart(document.getElementById("cardio-chart"), series, { unit: speedPts.length ? "km/h" : "" });

  const ul = document.getElementById("cardio-list");
  ul.innerHTML = "";
  if (!list.length) ul.append(el("p", { class: "muted" }, "Ei kardiotapahtumia vielä."));
  list.forEach((s) => {
    const bits = [s.activity];
    if (s.duration_min) bits.push(`${s.duration_min} min`);
    if (s.distance_km) bits.push(`${s.distance_km} km`);
    if (s.distance_km && s.duration_min) bits.push(`${(s.distance_km / (s.duration_min / 60)).toFixed(1)} km/h`);
    if (s.avg_hr) bits.push(`syke ${s.avg_hr}`);
    if (s.kcal) bits.push(`${Math.round(s.kcal)} kcal`);
    ul.append(el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("div", {}, el("strong", {}, s.session_date), el("span", { class: "muted" }, " · " + bits.join(" · "))),
        el("button", { class: "small danger", onclick: async () => {
          await api.del(`/api/recovery/cardio/${s.id}`); loadCardio(); loadReadiness();
        } }, "Poista"))));
  });
}

async function askTrainToday(sore) {
  const box = document.getElementById("tt-result");
  box.innerHTML = "";
  const r = await api.get(pq("/api/recovery/train-today") + "&sore=" + (sore ? "true" : "false"));
  const tone = { go: "var(--accent-2)", light: "#f59e0b", rest: "#ef4444" }[r.level] || "var(--muted)";
  box.append(el("div", { class: "item", style: `border-left:3px solid ${tone}` },
    el("strong", { style: `color:${tone}` }, r.verdict +
      (r.readiness_score != null ? ` (valmius ${r.readiness_score}/100)` : "")),
    el("div", { class: "muted", style: "margin-top:4px" }, r.detail),
    r.data_note ? el("div", { class: "muted", style: "margin-top:4px;font-style:italic" }, r.data_note) : ""));
}
document.getElementById("tt-ok").addEventListener("click", () => askTrainToday(false));
document.getElementById("tt-sore").addEventListener("click", () => askTrainToday(true));

document.querySelectorAll(".care-btn").forEach((b) => b.addEventListener("click", async () => {
  await api.post(`/api/recovery/cardio?profile_id=${currentProfileId}`, {
    activity: b.dataset.act, duration_min: +b.dataset.min,
  });
  document.getElementById("care-status").textContent =
    `${b.dataset.act} ${b.dataset.min} min kirjattu — hyvä! Lihashuolto antaa plussaa valmiuspisteisiin.`;
  loadCardio(); loadReadiness();
}));

document.getElementById("cardio-save").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  if (!v("cardio-min") && !v("cardio-kcal")) return alert("Anna vähintään kesto tai kalorit.");
  await api.post(`/api/recovery/cardio?profile_id=${currentProfileId}`, {
    session_date: v("cardio-date") || null,
    activity: v("cardio-activity"),
    duration_min: v("cardio-min") ? +v("cardio-min") : null,
    kcal: v("cardio-kcal") ? +v("cardio-kcal") : null,
    avg_hr: v("cardio-hr") ? +v("cardio-hr") : null,
    distance_km: v("cardio-km") ? +v("cardio-km") : null,
  });
  ["cardio-min", "cardio-kcal", "cardio-hr", "cardio-km"].forEach((id) => (document.getElementById(id).value = ""));
  loadCardio(); loadReadiness();
});

// Palautumismittarien suunta + oma normaalitaso + hälytysrajat
// Yleisarvio + hälytykset tiiviinä bannerina paneelien yläpuolelle.
async function loadRecoveryInsights() {
  const div = document.getElementById("recovery-verdict");
  const legacy = document.getElementById("recovery-insights");
  if (legacy) legacy.innerHTML = "";
  if (!div) return;
  div.innerHTML = "";
  let d;
  try { d = await api.get(pq("/api/recovery/insights")); } catch (e) { return; }
  if (!d.available) return;  // paneelit näyttävät oman "lisää dataa" -viestinsä
  const vTone = { improving: "var(--accent-2)", stable: "var(--muted)", declining: "#f59e0b" }[d.verdict];
  const banner = el("div", { class: "recovery-verdict", style: `border-color:${vTone}` },
    el("div", { style: `font-weight:600;color:${vTone}` },
      (d.verdict === "improving" ? "📈 " : d.verdict === "declining" ? "📉 " : "➡ ") + d.verdict_label));
  if (d.alerts && d.alerts.length) {
    const ul = el("ul", { style: "margin:6px 0 0;padding-left:18px" });
    d.alerts.forEach((a) => ul.append(el("li", { style: "color:#ef4444;font-size:0.85rem;margin:2px 0" }, a)));
    banner.append(ul);
  }
  div.append(banner);
}

// Kiinteät värit per mittari (erottuvat, värisokealle turvalliset).
const RECOVERY_COLORS = {
  hrv: "#9085e9", resting_hr: "#e66767", sleep_score: "#3987e5", sleep_hours: "#199e70",
};

// Piirtää kunkin palautumismittarin omaan paneeliinsa: oikeat yksiköt, oma
// normaalialue (varjostettu vyöhyke), päivämääräakseli ja tilan/hälytyksen.
async function renderRecoveryPanels() {
  const wrap = document.getElementById("recovery-panels");
  if (!wrap) return;
  wrap.innerHTML = "";
  let data;
  try { data = await api.get(pq("/api/recovery/series")); }
  catch (e) { wrap.textContent = "Datan haku epäonnistui."; return; }
  if (!data.available) { wrap.append(el("p", { class: "muted" }, data.note)); return; }

  const sColor = { good: "var(--accent-2)", ok: "var(--muted)", alert: "#ef4444", neutral: "var(--muted)" };
  const sIcon = { good: "✓", ok: "•", alert: "⚠", neutral: "…" };

  data.panels.forEach((p) => {
    const metricColor = RECOVERY_COLORS[p.key] || CHART_COLORS[0];
    const lineColor = p.status === "alert" ? "#ef4444" : metricColor;
    const panel = el("div", { class: "recovery-panel" });

    panel.append(el("div", { class: "row-between", style: "align-items:baseline" },
      el("strong", {}, p.label),
      el("span", { class: "tag", style: `color:${sColor[p.status]};border-color:${sColor[p.status]}` },
        `${sIcon[p.status]} ${p.recent != null ? "nyt " + p.recent + (p.unit ? " " + p.unit : "") : "—"}`)));

    if (p.band) {
      const zone = p.key === "sleep_hours" ? "Tavoitealue" : "Normaalialue";
      let line = `${zone} ${p.band.low}–${p.band.high}${p.unit ? " " + p.unit : ""}`;
      if (p.baseline != null && p.key !== "sleep_hours") line += ` · oma taso ~${p.baseline}`;
      panel.append(el("div", { class: "muted", style: "font-size:0.8rem" }, line));
    } else {
      panel.append(el("div", { class: "muted", style: "font-size:0.8rem" }, `Vyöhyke muodostuu kun mittauksia on ${p.min_n} (nyt ${p.n}).`));
    }

    const canvas = el("canvas", { width: 820, height: 150 });
    panel.append(canvas);

    if (p.note) panel.append(el("div", { style: `font-size:0.85rem;margin-top:4px;color:${sColor[p.status]}` }, p.note));
    if (p.period_from) panel.append(el("div", { class: "muted", style: "font-size:0.72rem;margin-top:2px" },
      `Jakso ${p.period_from} – ${p.period_to}`));

    wrap.append(panel);

    // Piirto: erillinen tyhjä "band-sarja" pitää vyöhykkeen aina rauhallisen
    // värisenä vaikka viiva olisi punainen (hälytys).
    const pts = p.points.map((d) => ({ x: new Date(d.date).getTime(), y: d.value }));
    const series = [];
    if (p.band && pts.length) {
      const xs = pts.map((q) => q.x);
      series.push({ points: [], color: metricColor,
        band: [{ x: Math.min(...xs), low: p.band.low, high: p.band.high },
               { x: Math.max(...xs), low: p.band.low, high: p.band.high }] });
    }
    series.push({ name: p.label, points: pts, color: lineColor });
    drawLineChart(canvas, series, { unit: p.unit });
  });
}

async function loadRecovery() {
  document.getElementById("cardio-date").value = new Date().toISOString().slice(0, 10);
  await loadReadiness();
  await loadCardio();
  await loadRecoveryInsights();
  await renderRecoveryPanels();

  // Korrelaatiotyökalu
  const metrics = await api.get("/api/stats/correlation/metrics");
  const selA = document.getElementById("corr-a"), selB = document.getElementById("corr-b");
  if (!selA.options.length) {
    Object.entries(metrics).forEach(([k, label]) => {
      selA.append(el("option", { value: k }, label));
      selB.append(el("option", { value: k }, label));
    });
    selA.value = "sleep_score"; selB.value = "tonnage";
    selA.onchange = drawCorrelation; selB.onchange = drawCorrelation;
  }
  await drawCorrelation();
}

async function drawCorrelation() {
  const a = document.getElementById("corr-a").value, b = document.getElementById("corr-b").value;
  const r = await api.get(pq(`/api/stats/correlation?a=${a}&b=${b}`));
  const div = document.getElementById("corr-result");
  div.innerHTML = "";
  if (r.pearson == null) {
    div.append(el("p", { class: "muted" }, `Liian vähän yhteistä viikkodataa (${r.n} viikkoa). Kirjaa molempia muuttujia.`));
    drawLineChart(document.getElementById("corr-chart"), []);
    return;
  }
  const strength = Math.abs(r.pearson) >= 0.7 ? "vahva" : Math.abs(r.pearson) >= 0.4 ? "kohtalainen" : "heikko";
  const dir = r.pearson > 0 ? "samaan suuntaan" : "vastakkaisiin suuntiin";
  div.append(el("div", { class: "result-box" },
    el("div", { class: "big" }, `r = ${r.pearson}`),
    el("div", { class: "muted" }, `${r.a_label} ja ${r.b_label}: ${strength} yhteys, muuttuvat ${dir} (${r.n} viikkoa). ` +
      "Korrelaatio ei tarkoita syy-seuraussuhdetta.")));
  drawLineChart(document.getElementById("corr-chart"), [
    { points: normalize01to100(r.series.map((s) => ({ x: new Date(s.date).getTime(), y: s.a }))), color: CHART_COLORS[0] },
    { points: normalize01to100(r.series.map((s) => ({ x: new Date(s.date).getTime(), y: s.b }))), color: CHART_COLORS[1] },
  ], {});
}

// ---------- Välilehtien laiskat lataukset ----------
TAB_LOADERS.overview = loadOverview;
TAB_LOADERS.progress = loadProgress;
TAB_LOADERS.recovery = loadRecovery;
TAB_LOADERS.body = loadBody;
TAB_LOADERS.nutrition = loadNutrition;
TAB_LOADERS.diet = loadDiet;
TAB_LOADERS.community = loadCommunity;
TAB_LOADERS.profiles = loadProfilesTab;

// ---------- Käynnistys ----------
// Lucide-ikonisprite (vendoroitu, toimii offline) + välilehtien ikonit
const TAB_ICONS = {
  overview: "layout-dashboard", progress: "trending-up", recovery: "heart-pulse",
  body: "person-standing", workouts: "dumbbell", programs: "calendar-days",
  exercises: "clipboard-list", nutrition: "apple", diet: "salad",
  community: "trophy", profiles: "users", calc: "calculator",
};

async function initIcons() {
  try {
    const res = await fetch("/static/vendor/icons.svg");
    const holder = document.createElement("div");
    holder.innerHTML = await res.text();
    holder.style.display = "none";
    document.body.prepend(holder);
    document.querySelectorAll("nav#tabs button").forEach((b) => {
      const name = TAB_ICONS[b.dataset.tab];
      if (!name) return;
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "ico");
      svg.setAttribute("width", "16"); svg.setAttribute("height", "16");
      const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
      use.setAttribute("href", `#i-${name}`);
      svg.append(use);
      b.prepend(svg);
    });
  } catch { /* ikonit ovat koriste — sovellus toimii ilmankin */ }
}

(async function init() {
  initIcons();
  // Profiililukon portti: jos lukko on päällä eikä ole kirjautunut, näytä
  // lukitusnäyttö äläkä lataa dataa ennen kirjautumista.
  const ok = await authGate();
  if (!ok) return;
  await loadProfiles();
  await loadExercises();
  await loadPrograms();
  await loadWorkouts();
  await loadOverview();
})();
