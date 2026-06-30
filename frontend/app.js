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
      tags.push(el("span", { class: "tag" }, `${ex.default_sets}×${ex.default_reps}`));
      if (ex.sport) tags.push(el("span", { class: "tag" }, ex.sport));
      const item = el("div", { class: "item" },
        el("div", { class: "row-between" },
          el("div", {}, el("strong", {}, ex.name),
            ex.muscle_group ? el("span", { class: "muted" }, " · " + ex.muscle_group) : ""),
          el("button", { class: "small danger", onclick: async () => {
            if (confirm(`Poista liike "${ex.name}"?`)) { await api.del(`/api/exercises/${ex.id}`); loadExercises(); }
          } }, "Poista")),
        el("div", { class: "btn-row" }, ...tags));
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
  const programs = await api.get(pq("/api/programs"));
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
async function loadWorkouts() {
  const workouts = await api.get(pq("/api/workouts"));
  const list = document.getElementById("workout-list");
  list.innerHTML = "";
  if (!workouts.length) list.append(el("p", { class: "muted" }, "Ei treenejä vielä."));
  for (const w of workouts) {
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
    const item = el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("div", { class: "btn-row", style: "align-items:center" },
          el("strong", {}, `${w.session_date} — ${w.name || "Treeni"}`),
          el("span", { class: "tag " + statusInfo[1] }, statusInfo[0]),
          feelEmoji ? el("span", { title: w.feeling_note || "" }, feelEmoji) : ""),
        el("div", { class: "btn-row" },
          el("button", { class: "small", onclick: () => openWorkoutEditor(w.id) }, "Avaa"),
          el("button", { class: "small danger", onclick: async () => {
            if (confirm("Poista treeni?")) { await api.del(`/api/workouts/${w.id}`); loadWorkouts(); }
          } }, "Poista"))),
      el("div", { class: "muted" }, `${w.exercises.length} liikettä · kokonaiskuorma ${Math.round(total)} kg` +
        (w.duration_min ? ` · ${w.duration_min} min` : "") + (w.kcal_burned ? ` · ${Math.round(w.kcal_burned)} kcal` : ""))
    );
    list.append(item);
  }
}

document.getElementById("new-workout-btn").addEventListener("click", async () => {
  const w = await api.post("/api/workouts", { name: "Vapaa treeni", profile_id: currentProfileId, exercises: [] });
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
        await api.post(`/api/workouts/${id}/complete`); loadWorkouts(); openWorkoutEditor(id);
      } }, "✓ Kuittaa valmiiksi"),
      el("button", { class: "small", onclick: async () => {
        if (confirm("Skipataanko tämä treeni? Sitä ei lasketa kehitykseen.")) {
          await api.post(`/api/workouts/${id}/skip`); loadWorkouts(); openWorkoutEditor(id);
        }
      } }, "Skip"),
      el("button", { class: "small", onclick: () => { editor.classList.add("hidden"); } }, "Sulje"))));
  editor.append(el("div", { class: "grid" },
    el("label", {}, "Nimi", nameInput), el("label", {}, "Päivä", dateInput),
    el("label", {}, "Kehon paino", bw), el("label", {}, "Kesto (min)", dur),
    el("label", {}, "Poltetut kcal", kcal), el("label", {}, "Fiilis", feeling),
    el("label", {}, "Fiilis-huomio", feelingNote), el("label", {}, "Huomiot", notes)));

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
      we.done ? el("span", { class: "tag status-done" }, "OK") : ""),
    el("div", { class: "btn-row" },
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

  // Arvioitu 1RM tästä treenistä (paras suoritettu sarja)
  block.append(el("div", { class: "muted", style: "margin-top:6px" }, `Arvioitu 1RM: ${oneRm}`));

  // Vajaus-pikakenttä: montako toistoa jäi yhteensä vajaaksi (ei tarvitse
  // kirjata 5,5,4,2 — riittää "4 vajaa"). Vähennetään kehitysvolyymistä.
  const missed = el("input", { type: "number", value: we.missed_reps || 0, style: "width:70px" });
  missed.addEventListener("change", async () => {
    await api.patch(`/api/workouts/exercises/${we.id}`, { exercise_id: we.exercise_id, missed_reps: +missed.value || 0 });
    loadWorkouts();
  });

  const suggestBox = el("span", { class: "muted" });
  block.append(el("div", { class: "btn-row", style: "align-items:center;margin-top:8px" },
    el("button", { class: "small", onclick: async () => {
      const last = we.sets[we.sets.length - 1];
      await api.post(`/api/workouts/exercises/${we.id}/sets`, {
        set_index: we.sets.length, reps: last ? last.reps : 5, weight: last ? last.weight : 0,
      });
      openWorkoutEditor(workoutId);
    } }, "+ Sarja"),
    el("label", { style: "flex-direction:row;align-items:center;gap:6px" }, "Vajaaksi jäi (toistot)", missed),
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
  // Sisällytä ennustehaarukan (band) pisteet akseleihin
  const bandPts = series.flatMap((s) => s.band || []);
  const xs = allPts.map((p) => p.x).concat(bandPts.map((p) => p.x));
  const ys = allPts.map((p) => p.y).concat(bandPts.flatMap((p) => [p.low, p.high]));
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
  const span = maxY - minY;
  const fmtY = (v) => (span < 10 ? v.toFixed(1) : String(Math.round(v)));
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (plotH / 4) * i;
    const val = maxY - (span / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillText(fmtY(val) + (opts.unit || ""), 6, y + 3);
  }
  // X-akselin päivämäärät (alku ja loppu)
  const fmt = (ms) => new Date(ms).toLocaleDateString("fi-FI", { day: "numeric", month: "numeric", year: "2-digit" });
  ctx.fillText(fmt(minX), pad.l, H - 12);
  ctx.textAlign = "right"; ctx.fillText(fmt(maxX), W - pad.r, H - 12); ctx.textAlign = "left";

  // Piirrä ennustehaarukat (band) ensin taustalle
  series.forEach((s, idx) => {
    if (!s.band || !s.band.length) return;
    const color = s.color || CHART_COLORS[idx % CHART_COLORS.length];
    const b = [...s.band].sort((a, p) => a.x - p.x);
    ctx.fillStyle = color + "22";
    ctx.beginPath();
    b.forEach((p, i) => { const X = xPix(p.x), Y = yPix(p.high); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    for (let i = b.length - 1; i >= 0; i--) ctx.lineTo(xPix(b[i].x), yPix(b[i].low));
    ctx.closePath(); ctx.fill();
  });

  series.forEach((s, idx) => {
    const color = s.color || CHART_COLORS[idx % CHART_COLORS.length];
    const pts = [...s.points].sort((a, b) => a.x - b.x);
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2;
    ctx.setLineDash(s.dashed ? [6, 5] : []);
    ctx.beginPath();
    pts.forEach((p, i) => { const X = xPix(p.x), Y = yPix(p.y); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    ctx.stroke();
    ctx.setLineDash([]);
    if (!s.dashed) pts.forEach((p) => { ctx.beginPath(); ctx.arc(xPix(p.x), yPix(p.y), 3, 0, Math.PI * 2); ctx.fill(); });
  });
}

// =================== YLEISNÄKYMÄ ===================
async function loadOverview() {
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

async function loadProgress() {
  renderProgressChips();
  renderBackfill();
  await loadVolume();
  await loadLevels();
  await loadSports();
  await loadLoadTimeline();
  await loadRecordsTable();
}

async function loadVolume() {
  const div = document.getElementById("volume-content");
  div.innerHTML = "";
  const data = await api.get(pq("/api/stats/volume-analysis"));
  if (!data.categories || !data.categories.length) {
    div.append(el("p", { class: "muted" }, data.message || "Ei dataa.")); return;
  }
  const statusTag = { low: ["Kasvata", "status-planned"], high: ["Kevennä", "status-skip"],
    ok: ["OK", "status-done"], none: ["—", "status-skip"] };
  const tbl = el("table", {});
  tbl.append(el("tr", {}, el("th", {}, "Lihasryhmä"), el("th", {}, "Sarjat (vk)"),
    el("th", {}, "Edell. vk"), el("th", {}, "Tila"), el("th", {}, "Ehdotus")));
  data.categories.forEach((c) => {
    const si = statusTag[c.status] || ["", ""];
    tbl.append(el("tr", {},
      el("td", { style: "text-transform:capitalize" }, c.category),
      el("td", {}, String(c.sets_week)), el("td", { class: "muted" }, String(c.sets_prev)),
      el("td", {}, el("span", { class: "tag " + si[1] }, si[0])),
      el("td", { class: "muted" }, data.acknowledged && c.status !== "ok" ? "(kuitattu)" : c.suggestion)));
  });
  div.append(el("div", { class: "muted", style: "margin-bottom:6px" }, `Yhteensä ${data.total_sets_week} työsarjaa tällä viikolla.`));
  div.append(tbl);
  if (data.acknowledged) {
    div.append(el("div", { class: "muted", style: "margin-top:8px" }, "✓ Kuittasit tämän viikon — ei muutostarvetta."));
  } else {
    div.append(el("button", { class: "small success", style: "margin-top:10px", onclick: async () => {
      await api.post(pq(`/api/stats/volume-ack?week_key=${data.week_key}`)); loadVolume();
    } }, "Kuittaa: tilanne OK, ei muutoksia"));
  }
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
  data.lifts.forEach((l) => {
    const pct = Math.min(100, Math.round(((l.level_index + 1) / data.all_levels.length) * 100));
    const box = el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("strong", {}, l.exercise_name),
        el("span", { class: "tag main" }, `${l.level} (${l.ratio}× paino)`)),
      el("div", { class: "level-bar" }, el("div", { class: "level-fill", style: `width:${pct}%` })),
      el("div", { class: "muted" },
        `${l.current_1rm} kg` + (l.next_level ? ` · seuraava: ${l.next_level} @ ${l.next_threshold_kg} kg` : " · huipputaso!")));
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
  alert("Tulos tallennettu.");
});

async function loadLoadTimeline() {
  const data = await api.get(pq("/api/stats/load-timeline"));
  const sum = document.getElementById("load-summary");
  sum.innerHTML = "";
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
    [{ points: data.map((d) => ({ x: new Date(d.date).getTime(), y: d.total_kg })) }], { unit: "kg" });
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
  const single = selectedProgress.size === 1;
  for (const id of selectedProgress) {
    const h = await api.get(pq(`/api/stats/exercises/${id}/history`));
    const color = CHART_COLORS[idx % CHART_COLORS.length];
    series.push({
      points: h.points.map((p) => ({ x: new Date(p.date).getTime(), y: p.estimated_1rm })),
      color,
    });
    legend.append(el("span", { class: "tag", style: `color:${color};border-color:${color}` }, h.exercise_name));
    // Ennuste (katkoviiva + haarukka) vain kun yksi liike valittuna -> selkeä
    if (single && h.forecast && h.forecast.length) {
      const lastPt = h.points[h.points.length - 1];
      const anchor = { x: new Date(lastPt.date).getTime(), y: lastPt.estimated_1rm };
      const fc = h.forecast.map((p) => ({ x: new Date(p.date).getTime(), y: p.mid }));
      const band = h.forecast.map((p) => ({ x: new Date(p.date).getTime(), low: p.low, high: p.high }));
      series.push({ points: [anchor, ...fc], band, color, dashed: true });
      legend.append(el("span", { class: "muted" }, " — katkoviiva = ennuste, alue = haarukka"));
      if (h.forecast_meta) {
        document.getElementById("progress-legend").append(
          el("div", { class: "muted", style: "margin-top:6px;width:100%" }, h.forecast_meta.note));
      }
    }
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
    el("div", {}, `${sport} — tämänhetkinen total`),
    el("div", { class: "big" }, `${t.total_mid} kg`),
    el("div", { class: "muted" }, `Haarukka ${t.total_low}–${t.total_high} kg`),
    el("div", { class: "muted" }, t.per_lift.map((l) => `${l.exercise_name}: ${l.current_1rm}kg`).join(" · ")),
    fcEnd ? el("div", { class: "muted", style: "margin-top:6px" },
      `Ennuste ~6 kk: ${fcEnd.low}–${fcEnd.high} kg (mihin tällä tahdilla ollaan menossa)`) : ""));

  const series = [{ points: t.timeline.map((p) => ({ x: new Date(p.date).getTime(), y: p.total })) }];
  if (t.forecast && t.forecast.length && t.timeline.length) {
    const last = t.timeline[t.timeline.length - 1];
    const anchor = { x: new Date(last.date).getTime(), y: last.total };
    const fc = t.forecast.map((p) => ({ x: new Date(p.date).getTime(), y: p.mid }));
    const band = t.forecast.map((p) => ({ x: new Date(p.date).getTime(), low: p.low, high: p.high }));
    series.push({ points: [anchor, ...fc], band, dashed: true, color: CHART_COLORS[1] });
  }
  drawLineChart(document.getElementById("total-chart"), series, { unit: "kg" });
}

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
  const planNames = { bodaus: "Lihasmassa (bodaus)", voimanosto: "Voimanosto", olympia: "Olympianosto" };
  const planSel = el("select", {});
  plans.forEach((p) => planSel.append(el("option", { value: p.id }, planNames[p.id] || p.id)));
  const daysSel = el("select", {});
  const info = el("div", { class: "muted", style: "margin:8px 0" });
  function refreshDays() {
    const p = plans.find((x) => x.id === planSel.value);
    daysSel.innerHTML = "";
    p.days_options.forEach((d) => daysSel.append(el("option", { value: d }, `${d}× viikossa`)));
    info.textContent = p.guidance;
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
  if (currentProfileId == null || !profilesCache.some((p) => p.id === currentProfileId)) {
    currentProfileId = profilesCache[0].id;
  }
  renderProfileSwitch();
}

function renderProfileSwitch() {
  const sel = document.getElementById("profile-select");
  sel.innerHTML = "";
  profilesCache.forEach((p) => {
    const o = el("option", { value: p.id }, p.name);
    sel.append(o);
  });
  sel.value = currentProfileId;
  const cur = profilesCache.find((p) => p.id === currentProfileId);
  const av = document.getElementById("profile-avatar");
  av.textContent = cur ? initials(cur.name) : "";
  av.style.background = cur && cur.color ? cur.color : "var(--accent)";
}

document.getElementById("profile-select").addEventListener("change", async (e) => {
  currentProfileId = +e.target.value;
  renderProfileSwitch();
  await refreshActiveTab();
});

async function refreshActiveTab() {
  // Lataa nykyiset perusnäkymät + aktiivisen välilehden data.
  await loadPrograms();
  await loadWorkouts();
  const activeTab = document.querySelector("nav#tabs button.active");
  const loader = activeTab && TAB_LOADERS[activeTab.dataset.tab];
  if (loader) await loader(); else await loadOverview();
}

async function loadProfilesTab() {
  await loadProfiles();
  const list = document.getElementById("profile-list");
  list.innerHTML = "";
  for (const p of profilesCache) {
    const isCurrent = p.id === currentProfileId;
    const item = el("div", { class: "item" },
      el("div", { class: "row-between" },
        el("div", { class: "btn-row", style: "align-items:center" },
          el("span", { class: "avatar", style: `background:${p.color || "var(--accent)"}` }, initials(p.name)),
          el("strong", {}, p.name + (isCurrent ? " (aktiivinen)" : ""))),
        el("div", { class: "btn-row" },
          isCurrent ? "" : el("button", { class: "small primary", onclick: async () => {
            currentProfileId = p.id; renderProfileSwitch(); await refreshActiveTab(); loadProfilesTab();
          } }, "Valitse"),
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

document.getElementById("new-profile-btn").addEventListener("click", () => {
  const form = document.getElementById("profile-form");
  form.classList.remove("hidden");
  form.innerHTML = "";
  const name = el("input", { placeholder: "Nimi" });
  const sex = el("select", {}, el("option", { value: "" }, "—"),
    el("option", { value: "mies" }, "mies"), el("option", { value: "nainen" }, "nainen"),
    el("option", { value: "muu" }, "muu"));
  const bd = el("input", { type: "date" });
  const height = el("input", { type: "number", step: "0.5", placeholder: "cm" });
  const color = el("input", { type: "color", value: "#4f8cff" });
  form.append(
    el("div", { class: "grid" },
      el("label", {}, "Nimi", name), el("label", {}, "Sukupuoli", sex),
      el("label", {}, "Syntymäaika", bd), el("label", {}, "Pituus", height),
      el("label", {}, "Väri", color)),
    el("div", { class: "btn-row" },
      el("button", { class: "success", onclick: async () => {
        if (!name.value.trim()) return alert("Anna nimi.");
        const p = await api.post("/api/profiles", {
          name: name.value.trim(), sex: sex.value || null, birthdate: bd.value || null,
          height_cm: height.value ? +height.value : null, color: color.value,
        });
        form.classList.add("hidden");
        currentProfileId = p.id;
        await loadProfiles(); loadProfilesTab(); await refreshActiveTab();
      } }, "Tallenna"),
      el("button", { onclick: () => form.classList.add("hidden") }, "Peruuta")));
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

async function loadBody() {
  document.getElementById("b-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("m-date").value = new Date().toISOString().slice(0, 10);
  const s = await api.get(pq("/api/body/summary"));
  renderBodyScore();

  // Koostumus
  const comp = document.getElementById("composition");
  comp.innerHTML = "";
  if (s.composition) {
    const c = s.composition;
    comp.append(el("div", { class: "result-box" },
      el("div", {}, `Paino ${c.bodyweight} kg · rasva ${c.body_fat_pct}%`),
      el("div", { class: "big" }, `Lihasmassa ~${c.lean_mass_kg} kg`),
      el("div", { class: "muted" },
        `Rasvamassa ~${c.fat_mass_kg} kg` +
        (c.bmi ? ` · BMI ${c.bmi}` : "") + (c.ffmi ? ` · FFMI ${c.ffmi}` : ""))));
    // Fysiikkataso (aloittelija → IFBB Pro)
    if (s.physique) {
      const p = s.physique;
      const pct = Math.min(100, Math.round(((p.level_index + 1) / p.levels.length) * 100));
      comp.append(el("div", { style: "margin-top:12px" },
        el("div", { class: "row-between" },
          el("strong", {}, "Fysiikkataso"),
          el("span", { class: "tag main" }, `${p.level} (FFMI ${p.ffmi})`)),
        el("div", { class: "level-bar" }, el("div", { class: "level-fill", style: `width:${pct}%` })),
        el("div", { class: "muted" }, p.next_level ? `Seuraava: ${p.next_level} @ FFMI ${p.next_ffmi}` : "Huipputaso!")));
    }
  } else {
    comp.append(el("p", { class: "muted" }, "Anna paino ja rasva-% nähdäksesi koostumusarvion."));
  }

  // Painokäyrä
  drawLineChart(document.getElementById("weight-chart"),
    [{ points: s.weight_series.map((p) => ({ x: new Date(p.date).getTime(), y: p.value })) }], { unit: "kg" });

  // Mitat
  const legend = document.getElementById("measure-legend");
  legend.innerHTML = "";
  const series = [];
  let idx = 0;
  const fcs = s.measurement_forecasts || {};
  let hasFc = false;
  for (const [site, pts] of Object.entries(s.measurement_sites)) {
    const color = CHART_COLORS[idx % CHART_COLORS.length];
    series.push({ color, points: pts.map((p) => ({ x: new Date(p.date).getTime(), y: p.value })) });
    legend.append(el("span", { class: "tag", style: `color:${color};border-color:${color}` }, site));
    // Ennuste (katkoviiva + haarukka) jos dataa riittää
    if (fcs[site] && fcs[site].length && pts.length) {
      const last = pts[pts.length - 1];
      const anchor = { x: new Date(last.date).getTime(), y: last.value };
      const fc = fcs[site].map((p) => ({ x: new Date(p.date).getTime(), y: p.mid }));
      const band = fcs[site].map((p) => ({ x: new Date(p.date).getTime(), low: p.low, high: p.high }));
      series.push({ color, dashed: true, points: [anchor, ...fc], band });
      hasFc = true;
    }
    idx++;
  }
  if (hasFc) legend.append(el("span", { class: "muted" }, " — katkoviiva = ennuste (oman datan trendistä)"));
  drawLineChart(document.getElementById("measure-chart"), series, { unit: "cm" });

  // Tulkinnat (kasvu rasvaa/lihasta, vakaa dieetillä, lähellä kattoa…)
  const ins = document.getElementById("measure-insights");
  ins.innerHTML = "";
  const insights = s.measurement_insights || {};
  const rows = Object.entries(insights).filter(([, v]) => v.note || v.ceiling);
  if (rows.length) {
    rows.forEach(([site, v]) => {
      const parts = [];
      if (v.note) parts.push(v.note);
      if (v.ceiling) parts.push(`arvioitu luonnollinen katto ~${v.ceiling} cm`);
      ins.append(el("div", { class: "muted", style: "margin-top:4px" },
        `${site}: ${parts.join(" · ")}`));
    });
  }
}

document.getElementById("b-save").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  const body = {
    entry_date: v("b-date") || null,
    bodyweight: v("b-weight") ? +v("b-weight") : null,
    body_fat_pct: v("b-bf") ? +v("b-bf") : null,
    sleep_hours: v("b-sleep") ? +v("b-sleep") : null,
    sleep_score: v("b-sscore") ? +v("b-sscore") : null,
    hrv: v("b-hrv") ? +v("b-hrv") : null,
    resting_hr: v("b-rhr") ? +v("b-rhr") : null,
    kcal: v("b-kcal") ? +v("b-kcal") : null,
  };
  await api.post(pq("/api/body/entries"), body);
  ["b-weight", "b-bf", "b-sleep", "b-sscore", "b-hrv", "b-rhr", "b-kcal"].forEach((id) => (document.getElementById(id).value = ""));
  loadBody();
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

async function renderDayLog() {
  const s = await api.get(pq("/api/nutrition/summary") + "&on_date=" + nDate());
  const t = s.today;
  // Yhteenveto + liikaa/liian vähän -arvio dieettitavoitteeseen nähden
  const today = document.getElementById("nutrition-today");
  today.innerHTML = "";
  const box = el("div", { class: "result-box" },
    el("div", { class: "big" }, `${Math.round(t.kcal)} kcal`),
    el("div", { class: "muted" }, `Proteiini ${Math.round(t.protein_g)} g · hiilarit ${Math.round(t.carbs_g)} g · rasva ${Math.round(t.fat_g)} g`));
  try {
    const diet = await api.get(pq("/api/diet/status"));
    if (diet.targets && t.kcal > 0) {
      const tgt = diet.targets.kcal, diff = Math.round(t.kcal - tgt);
      let msg;
      if (diff < -300) msg = `Syöty ${Math.abs(diff)} kcal alle tavoitteen (${tgt}) — syöt liian vähän.`;
      else if (diff > 300) msg = `Syöty ${diff} kcal yli tavoitteen (${tgt}) — syöt liikaa.`;
      else msg = `Tavoitteessa (${tgt} kcal ±300).`;
      box.append(el("div", { class: "muted", style: "margin-top:6px" }, msg));
      if (t.protein_g < diet.targets.protein_g * 0.8)
        box.append(el("div", { class: "muted" }, `Proteiinia jää tavoitteesta (${diet.targets.protein_g} g) — lisää proteiinia.`));
    }
  } catch (e) {}
  today.append(box);

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

  // Makrograafi (kcal + P/C/F ajan yli)
  const tl = s.timeline;
  const legend = document.getElementById("macro-legend");
  legend.innerHTML = "";
  const macroSeries = [
    ["kcal", "kcal", CHART_COLORS[0]], ["protein_g", "Proteiini", CHART_COLORS[1]],
    ["carbs_g", "Hiilarit", CHART_COLORS[2]], ["fat_g", "Rasva", CHART_COLORS[3]],
  ];
  const series = macroSeries.map(([key, label, color]) => {
    legend.append(el("span", { class: "tag", style: `color:${color};border-color:${color}` }, label));
    return { color, points: tl.map((p) => ({ x: new Date(p.date).getTime(), y: p[key] })) };
  });
  // Normalisoi 0–100 jotta eri mittakaavat näkyvät samassa
  drawLineChart(document.getElementById("intake-chart"),
    series.map((s) => ({ ...s, points: normalize01to100(s.points) })), {});
}

document.getElementById("n-date").addEventListener("change", renderDayLog);
document.getElementById("food-search").addEventListener("input", renderFoodResults);
document.getElementById("food-cat").addEventListener("change", renderFoodResults);
document.getElementById("food-fav-only").addEventListener("change", renderFoodResults);

// ---- Omat ateriat ----
async function renderMeals() {
  const meals = await api.get(pq("/api/nutrition/meals"));
  const list = document.getElementById("meals-list");
  list.innerHTML = "";
  if (!meals.length) list.append(el("p", { class: "muted" }, "Ei tallennettuja aterioita vielä."));
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
  const itemsBox = el("div", {});
  const allFoods = await api.get("/api/nutrition/foods");
  function renderItems() {
    itemsBox.innerHTML = "";
    items.forEach((it, i) => {
      const sel = el("select", { onchange: (e) => (it.food_id = +e.target.value) });
      allFoods.forEach((f) => sel.append(el("option", { value: f.id }, f.name)));
      sel.value = it.food_id;
      const g = el("input", { type: "number", value: it.grams, style: "width:75px", oninput: (e) => (it.grams = +e.target.value) });
      itemsBox.append(el("div", { class: "btn-row" }, sel, g, el("span", { class: "muted" }, "g"),
        el("button", { class: "small danger", onclick: () => { items.splice(i, 1); renderItems(); } }, "x")));
    });
  }
  editor.append(el("div", { class: "card" },
    el("label", {}, "Nimi", name), itemsBox,
    el("div", { class: "btn-row", style: "margin-top:8px" },
      el("button", { class: "small", onclick: () => { items.push({ food_id: allFoods[0].id, grams: 100 }); renderItems(); } }, "+ Ruoka"),
      el("button", { class: "success", onclick: async () => {
        if (!name.value.trim() || !items.length) return alert("Anna nimi ja vähintään yksi ruoka.");
        await api.post(`/api/nutrition/meals?profile_id=${currentProfileId}`, { name: name.value.trim(), items });
        editor.classList.add("hidden"); renderMeals();
      } }, "Tallenna ateria"),
      el("button", { class: "small", onclick: () => editor.classList.add("hidden") }, "Peruuta"))));
  renderItems();
});

document.getElementById("nf-save").addEventListener("click", async () => {
  const v = (id) => document.getElementById(id).value;
  if (!v("nf-name").trim()) return alert("Anna ruoalle nimi.");
  try {
    await api.post("/api/nutrition/foods", {
      name: v("nf-name").trim(), category: v("nf-cat").trim() || null,
      kcal: +v("nf-kcal") || 0, protein_g: +v("nf-prot") || 0,
      carbs_g: +v("nf-carb") || 0, fat_g: +v("nf-fat") || 0,
      default_grams: v("nf-grams") ? +v("nf-grams") : null,
    });
    ["nf-name", "nf-cat", "nf-kcal", "nf-prot", "nf-carb", "nf-fat", "nf-grams"].forEach((id) => (document.getElementById(id).value = ""));
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
      (s.intake_avg_kcal ? ` · keskisyönti ${s.intake_avg_kcal} kcal` : "")),
    el("div", { class: "result-box", style: "margin-top:10px" }, s.recommendation)));

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

async function loadRecovery() {
  const entries = await api.get(pq("/api/body/entries"));
  const fields = [
    ["sleep_score", "Unipisteet"], ["sleep_hours", "Uni (h)"],
    ["hrv", "HRV"], ["resting_hr", "Leposyke"],
  ];
  const series = [];
  const legend = document.getElementById("recovery-legend");
  legend.innerHTML = "";
  let idx = 0;
  for (const [key, label] of fields) {
    const pts = entries.filter((e) => e[key] != null)
      .map((e) => ({ x: new Date(e.entry_date).getTime(), y: e[key] }));
    if (pts.length < 2) continue;
    const color = CHART_COLORS[idx % CHART_COLORS.length];
    series.push({ points: normalize01to100(pts), color });
    const latest = pts.sort((a, b) => a.x - b.x)[pts.length - 1].y;
    legend.append(el("span", { class: "tag", style: `color:${color};border-color:${color}` }, `${label} (nyt ${latest})`));
    idx++;
  }
  if (!series.length) legend.append(el("span", { class: "muted" }, "Lisää uni-/HRV-/syke-dataa Keho-välilehdellä."));
  else legend.append(el("span", { class: "muted" }, " · arvot normalisoitu 0–100 vertailtavuuden vuoksi"));
  drawLineChart(document.getElementById("recovery-chart"), series, {});

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
TAB_LOADERS.profiles = loadProfilesTab;

// ---------- Käynnistys ----------
(async function init() {
  await loadProfiles();
  await loadExercises();
  await loadPrograms();
  await loadWorkouts();
  await loadOverview();
})();
