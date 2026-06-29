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
document.querySelectorAll("nav#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav#tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
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
          block.append(el("div", { class: "btn-row" }, sel,
            el("label", {}, "sarjat", sets), el("label", {}, "toistot", reps),
            el("label", {}, "kg", wt), el("label", {}, "palautus s", rest),
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

// ---------- Käynnistys ----------
(async function init() {
  await loadExercises();
  await loadPrograms();
  await loadWorkouts();
})();
