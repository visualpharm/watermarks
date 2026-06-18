// ---------------- routing ----------------
const VIEWS = ["home", "watermarks", "detector"];
function route(){
  closeModal();
  let r = (location.hash || "#home").replace("#", "").replace("/", "");
  if (!VIEWS.includes(r)) r = "home";
  VIEWS.forEach(v => document.getElementById("view-"+v).classList.toggle("hidden", v !== r));
  document.querySelectorAll("nav .nl").forEach(n => n.classList.toggle("on", n.dataset.route === r));
  window.scrollTo(0, 0);
  if (r === "home") initBA();
  if (r === "watermarks") loadVersions();
  if (r === "detector") { checkHealth(); initHistory(); }
}

// ---------------- before/after slider ----------------
let BA_INIT = false;
async function initBA(){
  const ba = document.getElementById("ba");
  if (!ba || BA_INIT) return; BA_INIT = true;

  // load versions (shared cache with the watermarks tab)
  if (!VERSIONS) {
    try { VERSIONS = await (await fetch("/api/versions")).json(); } catch(e){}
  }

  if (VERSIONS && VERSIONS.versions && VERSIONS.versions.length) {
    const versions = VERSIONS.versions;
    const beforeImg = document.getElementById("baBeforeImg");
    const afterImg  = document.getElementById("baAfterImg");
    const verSel    = document.getElementById("baVersionSel");
    const modSel    = document.getElementById("baModelSel");
    const cap       = document.getElementById("baCap");

    // version dropdown — default to the latest
    verSel.innerHTML = versions.map((v, i) =>
      `<option value="${i}">${v.id.toUpperCase()} — ${v.title}</option>`).join("");
    verSel.value = String(versions.length - 1);

    // verdict → how successfully the model removed the mark (best first)
    const SUCCESS = {clean_rescale:3, edited:2, manipulated:1, refused:0};
    // verdict → short outcome word shown in the dropdown option
    const OUTCOME = {clean_rescale:"removed", edited:"removed", manipulated:"removed", refused:"refused"};

    function showModel(){
      const opt = modSel.options[modSel.selectedIndex];
      if (!opt) return;
      const v = versions[+verSel.value];
      const model = opt.dataset.model, img = opt.dataset.img;
      const atk = (v.attacks || []).find(x => x.model === model) || {};
      if (img) {
        afterImg.src = img;
        const score = (atk.score != null)
          ? ` <span class="capscore" title="reconstruction intensity, 0–100">damage ${atk.score}/100</span>` : "";
        const detail = atk.description
          ? ` ${atk.description}` : " the mark is gone, but only because the model rebuilt the asset.";
        cap.innerHTML = `<b>${v.id.toUpperCase()} — ${v.title}.</b> Left: watermarked. ` +
          `Right: after <b>${model}</b>${score} —${detail} Drag to compare.`;
      } else {
        // refused → no removal; the watermark survives, both halves identical
        afterImg.src = beforeImg.src;
        cap.innerHTML = `<b>${v.id.toUpperCase()} — ${v.title}.</b> ` +
          `<b>${model}</b> refused to remove the watermark — the mark survives intact (both halves match).`;
      }
    }
    function showVersion(){
      const v = versions[+verSel.value];
      beforeImg.src = v.image;
      // list EVERY attack model (refused ones included); heaviest rebuild first
      const attacks = v.attacks.slice().sort(
        (x, y) => (SUCCESS[y.verdict]||0) - (SUCCESS[x.verdict]||0)
                || (y.score||0) - (x.score||0));
      modSel.innerHTML = attacks.map(a => {
        const tag = (a.score != null) ? ` · damage ${a.score}` : "";
        return `<option data-img="${a.image||""}" data-model="${a.model}" data-verdict="${a.verdict}">` +
          `${a.model} · ${OUTCOME[a.verdict]||a.verdict}${tag}</option>`; }).join("");
      modSel.selectedIndex = 0;   // most successful attack first
      showModel();
    }
    verSel.addEventListener("change", showVersion);
    modSel.addEventListener("change", showModel);
    showVersion();

    // findings + hero stats
    renderHeroStats(versions);
    renderFindings(versions);
  }

  // slider drag
  const before = document.getElementById("baBefore"), handle = document.getElementById("baHandle");
  const setPos = p => { p = Math.max(2, Math.min(98, p));
    before.style.clipPath = `inset(0 ${100-p}% 0 0)`; handle.style.left = p + "%"; };
  let drag = false;
  const move = e => { if (!drag) return;
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - ba.getBoundingClientRect().left;
    setPos(x / ba.clientWidth * 100); };
  ba.addEventListener("pointerdown", e => { drag = true; move(e); });
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", () => drag = false);
  setPos(50);
}

function attackTally(versions){
  let total = 0, cleaned = 0, refused = 0, models = 0;
  versions.forEach((v, i) => { if (i === 0) models = v.attacks.length;
    v.attacks.forEach(a => { total++;
      if (a.verdict === "clean_rescale") cleaned++;
      if (a.verdict === "refused") refused++; }); });
  return {total, cleaned, refused, models, manipulated: total - cleaned - refused,
          versions: versions.length};
}
function renderHeroStats(versions){
  const el = document.getElementById("heroStats");
  if (!el) return;
  const t = attackTally(versions);
  const stats = [
    {n: t.models, l: "AI editors tested"},
    {n: t.versions, l: "watermark versions"},
    {n: t.cleaned, l: "clean removals", c: "ok"},
    {n: t.manipulated, l: "reconstructed (caught)", c: "bad"},
    {n: t.refused, l: "refused outright", c: "warn"},
  ];
  el.innerHTML = stats.map(s =>
    `<div class="stat"><span class="n ${s.c||""}">${s.n}</span><span class="l">${s.l}</span></div>`).join("");
}
function renderFindings(versions){
  const wrap = document.getElementById("findings");
  const body = document.getElementById("findingsBody");
  if (!wrap || !body) return;
  const t = attackTally(versions);

  body.innerHTML = `
    <div class="finding-col">
      <div class="k bad">No clean removal — on any version<span class="nm">01</span></div>
      <p>Across ${t.versions} versions — fused layers, baked-in text, adversarial hi-freq noise — ${t.manipulated} of ${t.total} attacks came back forensically <em>manipulated</em>: the editor had to regenerate the whole asset to lose the mark. ${t.refused} were <em>refused</em> outright (Google's Nano Banana Pro declines watermark removal). <strong>${t.cleaned} clean erasures.</strong></p>
    </div>
    <div class="finding-col">
      <div class="k warn">The pivot: detection, not prevention<span class="nm">02</span></div>
      <p>Once an editor can regenerate an image from scratch, no visible or baked-in mark survives intact. So the project shifted from making marks that <em>can't</em> be removed to making their removal <em>provable</em> — three independent signals that outlive any regeneration attempt.</p>
    </div>
    <div class="finding-col">
      <div class="k ok">3 independent proofs of theft<span class="nm">03</span></div>
      <p><strong>Invisible serial</strong> — a block-DCT watermark carrying a registry serial (survives JPEG q85, fails on regeneration by design). <strong>C2PA provenance</strong> — AI output self-declares <code>trainedAlgorithmicMedia</code> in the raw bytes. <strong>Forensic reconstruction</strong> — edge vs. interior-flat error signatures reveal inpainting even on a clean-looking result.</p>
    </div>`;
  wrap.style.display = "";
}
document.querySelectorAll("[data-route]").forEach(el =>
  el.addEventListener("click", () => location.hash = el.dataset.route));
window.addEventListener("hashchange", route);

// ---------------- versions ----------------
let VERSIONS = null;
async function loadVersions(){
  if (VERSIONS) return;
  try { VERSIONS = await (await fetch("/api/versions")).json(); }
  catch(e){ return; }
  const g = document.getElementById("vgrid");
  g.innerHTML = VERSIONS.versions.map((v,i) => `
    <div class="vcard card" data-i="${i}">
      <div class="ph" style="background-image:url('${v.image}')"></div>
      <div class="meta">
        <div class="row"><span class="vtag">${v.id}</span><h3>${v.title}</h3></div>
        <div class="desc">${v.approach.split(".")[0]}.</div>
        <div class="pills">
          <span class="pill vis">visibility: ${v.visibility}</span>
          <span class="pill prot">protection: ${v.protection}</span>
        </div>
      </div>
    </div>`).join("");
  g.querySelectorAll(".vcard").forEach(c =>
    c.addEventListener("click", () => openVersion(+c.dataset.i)));
  document.getElementById("vmeta").textContent =
    `Generated ${VERSIONS.meta.generated_on}. Base: ${VERSIONS.meta.base_source}. ` +
    `Each version attacked with the removal prompt shown in every card's "Prompt & method".`;
}

function vBadge(verdict){
  const m = {clean_rescale:["CLEAN — restored","b-clean"], manipulated:["MANIPULATED — asset damaged","b-bad"],
    edited:["EDITED","b-edit"], inconclusive:["INCONCLUSIVE","b-inc"], refused:["REMOVAL FAILED","b-refused"]};
  return m[verdict] || ["?","b-inc"];
}
function interpret(verdict){
  if (verdict === "manipulated") return "The eraser had to reconstruct the box to strip the mark — the watermark held.";
  if (verdict === "refused") return "The model declined or failed to remove it — the watermark held.";
  if (verdict === "clean_rescale") return "The model cleanly removed the watermark — this version was beaten.";
  return "";
}
function openVersion(i){
  const v = VERSIONS.versions[i], meta = VERSIONS.meta;
  const atk = v.attacks.map(a => {
    const [lab, cls] = vBadge(a.verdict);
    const img = a.image
      ? `<img src="${a.image}">`
      : `<div class="none">model refused / failed to remove the watermark</div>`;
    // per-attack DAMAGE score (varies a lot); falls back to nothing if absent
    const score = (a.score != null)
      ? ` <span class="score" title="reconstruction intensity, 0–100">${a.score}</span>` : "";
    const text = a.description || interpret(a.verdict);
    return `<div class="a card">
        <div class="hd"><b>${a.model}</b><span class="badge ${cls}">${lab}${score}</span></div>
        ${img}
        <div class="desc" style="color:var(--mut);font-size:12.5px;margin-top:8px">${text}</div>
        <div class="mono" style="font-size:10.5px;color:#9a9385;margin-top:6px">${a.model_id||""}</div>
      </div>`;
  }).join("");
  document.getElementById("sheet").innerHTML = `
    <button class="x" onclick="closeModal()">×</button>
    <h2><span class="vtag mono">${v.id}</span> &nbsp;${v.title}</h2>
    <div class="sub">Generated ${meta.generated_on} · visibility ${v.visibility} · protection ${v.protection}</div>
    <img class="big" src="${v.image}">
    <h2 style="margin:22px 0 4px;font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut)">AI removal attempts</h2>
    <div class="atk">${atk}</div>
    <details class="method">
      <summary>Prompt &amp; method</summary>
      <div class="body">
        <div class="lbl">How this version watermarks</div>
        ${v.approach}
        <div class="lbl">Commit</div>
        <div class="codeblk">${v.commit}</div>
        <div class="lbl">AI removal prompt used to attack it</div>
        <div class="codeblk">${meta.removal_prompt}</div>
      </div>
    </details>`;
  document.getElementById("modal").classList.add("open");
}
function closeModal(){ document.getElementById("modal").classList.remove("open"); }
document.getElementById("modal").addEventListener("click", e => {
  if (e.target.id === "modal") closeModal();
});
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

// ---------------- detector ----------------
const S = {A:null, B:null, nameA:"", nameB:"", active:"A", mode:"algo", aiPw:false};

function setActive(side){
  S.active = side;
  ["A","B"].forEach(s => document.getElementById("dz"+s).classList.toggle("active", s === side));
}
function read(file, side){
  const fr = new FileReader();
  fr.onload = () => set(side, fr.result, file.name || "pasted.png");
  fr.readAsDataURL(file);
}
function set(side, dataurl, name){
  S[side] = dataurl; S["name"+side] = name || "image";
  redraw(side); setActive(side);
  document.getElementById("go").disabled = !(S.A && S.B);
}
function redraw(side){
  const img = document.getElementById("prev"+side), hint = document.getElementById("hint"+side),
        fn = document.getElementById("fn"+side);
  if (!S[side]){ img.style.display = "none"; hint.style.display = ""; fn.textContent = ""; return; }
  const tmp = new Image();
  tmp.onload = () => fn.textContent = S["name"+side] + "  ·  " + tmp.naturalWidth + "×" + tmp.naturalHeight;
  tmp.src = S[side];
  img.src = S[side]; img.style.display = "inline-block"; hint.style.display = "none";
}
["A","B"].forEach(side => {
  const dz = document.getElementById("dz"+side), inp = document.getElementById("f"+side),
        br = document.getElementById("br"+side);
  dz.addEventListener("click", () => setActive(side));        // click selects the area
  br.addEventListener("click", e => { e.stopPropagation(); inp.click(); });
  inp.addEventListener("click", e => e.stopPropagation());
  inp.addEventListener("change", e => { if (e.target.files[0]) read(e.target.files[0], side); e.target.value = ""; });
  dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", e => { e.preventDefault(); dz.classList.remove("over");
    if (e.dataTransfer.files[0]) read(e.dataTransfer.files[0], side); });
});
window.addEventListener("paste", e => {
  if (document.getElementById("view-detector").classList.contains("hidden")) return;
  for (const it of e.clipboardData.items)
    if (it.type.startsWith("image/")) { read(it.getAsFile(), S.active); break; }
});
document.getElementById("swap").addEventListener("click", () => {
  [S.A, S.B] = [S.B, S.A]; [S.nameA, S.nameB] = [S.nameB, S.nameA];
  redraw("A"); redraw("B");
});
document.getElementById("demo").addEventListener("click", async () => {
  try {
    const r = await (await fetch("/api/example?case=theft")).json();
    if (r.original){ set("A", r.original, "master · serial WM-7F3A9C2B"); set("B", r.review, "ai-suspect · gpt-image-2"); }
  } catch(e){ alert("Could not load example."); }
});

let HEALTH = null;
async function checkHealth(){
  if (!HEALTH){ try { HEALTH = await (await fetch("/api/health")).json(); } catch(e){ HEALTH = {}; } }
  updateMode();
}
document.getElementById("seg").addEventListener("click", e => {
  if (!e.target.dataset.m) return;
  S.mode = e.target.dataset.m;
  document.querySelectorAll("#seg button").forEach(b => b.classList.toggle("on", b === e.target));
  updateMode();
});
function updateMode(){
  const pw = document.getElementById("pw"), warn = document.getElementById("aiwarn");
  const needPw = S.mode === "ai" && HEALTH && HEALTH.ai_requires_password;
  pw.style.display = needPw ? "inline-flex" : "none";
  if (S.mode === "ai" && HEALTH && !HEALTH.ai){
    warn.classList.remove("hidden"); warn.textContent = "AI mode is not configured on this server — it will return the algorithmic result.";
  } else warn.classList.add("hidden");
}

async function runAnalysis(){
  if (!(S.A && S.B)) return;
  const go = document.getElementById("go"), out = document.getElementById("out");
  go.disabled = true; go.innerHTML = '<span class="spin"></span>Analyzing…'; out.style.display = "none";
  try {
    const headers = {"Content-Type":"application/json"};
    const pwval = document.getElementById("pwin").value;
    if (S.mode === "ai" && pwval) headers["X-AI-Password"] = pwval;
    const res = await fetch("/api/forensic", {method:"POST", headers,
      body: JSON.stringify({original:S.A, review:S.B, mode:S.mode})});
    const data = await res.json();
    if (data.error) out.innerHTML = `<div class="err">${data.error}</div>`;
    else {
      render(data);
      if (S.mode === "ai" && pwval) localStorage.setItem("wm_ai_pw", pwval);  // remember
      pushHistory(data.algo);
    }
    out.style.display = "block";
  } catch(e){ out.innerHTML = `<div class="err">Request failed: ${e}</div>`; out.style.display = "block"; }
  go.disabled = false; go.textContent = "Analyze";
}
document.getElementById("go").addEventListener("click", runAnalysis);

function vClass(v){ return v==="clean_rescale"?"v-clean":v==="manipulated"?"v-bad":v==="edited"?"v-edit":"v-inc"; }
function vLabel(v){ return v==="clean_rescale"?"CLEAN RESCALE":v==="manipulated"?"MANIPULATED":v==="edited"?"EDITED":"INCONCLUSIVE"; }

function render(data){
  const a = data.algo, out = document.getElementById("out");
  let h = "";
  // forgery-evidence panel (the hero)
  const ev = data.evidence;
  if (ev && ev.proofs){
    const tone = ev.signals >= 2 ? "bad" : ev.signals === 1 ? "warn" : "ok";
    h += `<div class="evid ${tone}"><div class="ehead">${ev.headline}</div>`;
    ev.proofs.forEach(p => { h += `<div class="proof ${p.sev}">
      <span class="pd">${p.sev==="ok"?"✓":p.sev==="warn"?"!":"✕"}</span>
      <span><b>${p.label}</b><span class="det">${p.detail}</span></span></div>`; });
    h += `</div>`;
  }
  h += `<div class="verdict ${vClass(a.verdict)}"><span class="vbadge">${vLabel(a.verdict)}</span>
    <span class="sum">${a.summary}</span><span class="conf">algorithmic<b>${a.confidence}%</b></span></div><div class="grid2">`;
  h += `<div class="panel card"><h3>Evidence</h3><ul class="reasons">`;
  (a.reasons||[]).forEach(r => h += `<li class="${r[0]}">${r[1]}</li>`);
  h += `</ul>`;
  if (a.metrics && Object.keys(a.metrics).length){
    h += `<details class="metrics"><summary>Show all metrics</summary><table class="mx">`;
    for (const k in a.metrics) h += `<tr><td style="color:var(--mut)">${k}</td><td class="mono">${a.metrics[k]}</td></tr>`;
    h += `</table></details>`;
  }
  h += `</div>`;
  if (a.heatmap){
    h += `<div class="panel card"><h3>Difference heat-map</h3><img class="heat" src="${a.heatmap}">
      <div class="legend">
        <span><span class="dot" style="background:#cc2222"></span>edge (normal resize)</span>
        <span><span class="dot" style="background:#ffe628"></span>smooth-area (removal)</span>
        <span><span class="dot" style="background:#00c8ff"></span>added</span>
        <span><span class="dot" style="background:#ff3cc8"></span>removed</span>
      </div></div>`;
  }
  h += `</div>`;
  if (data.ai){
    const ai = data.ai;
    if (ai.error) h += `<div class="ai card"><h3>AI examiner</h3><div class="err">${ai.error}</div></div>`;
    else {
      h += `<div class="ai card"><h3>AI examiner — ${vLabel(ai.verdict||"inconclusive")} (${ai.confidence??"?"}%)</h3>
        <div>${ai.reasoning||""}</div>`;
      if (ai.artifacts && ai.artifacts.length){
        h += `<ul class="reasons" style="margin-top:10px">`;
        ai.artifacts.forEach(x => h += `<li class="warn">${x}</li>`); h += `</ul>`;
      }
      h += `<div class="meta">watermark removal suspected: <b>${ai.watermark_removal_suspected?"yes":"no"}</b>
        · background/scene added: <b>${ai.background_or_scene_added?"yes":"no"}</b> · model ${ai._model||""}</div></div>`;
    }
  }
  out.innerHTML = h;
}

// ---------------- detection history (localStorage) ----------------
const HK = "wm_hist";
function tinyThumb(dataurl){
  return new Promise(res => {
    const im = new Image();
    im.onload = () => {
      const s = 64 / Math.max(im.width, im.height);
      const c = document.createElement("canvas");
      c.width = Math.round(im.width*s); c.height = Math.round(im.height*s);
      c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
      res(c.toDataURL("image/jpeg", 0.6));
    };
    im.onerror = () => res("");
    im.src = dataurl;
  });
}
async function pushHistory(algo){
  const [a, b] = await Promise.all([tinyThumb(S.A), tinyThumb(S.B)]);
  let list = [];
  try { list = JSON.parse(localStorage.getItem(HK) || "[]"); } catch(e){}
  list.unshift({t: Date.now(), verdict: algo.verdict, conf: algo.confidence, mode: S.mode, a, b});
  list = list.slice(0, 8);
  try { localStorage.setItem(HK, JSON.stringify(list)); } catch(e){}
  renderHistory();
}
function badgeColor(v){ return v==="clean_rescale"?"#3c7d4d":v==="manipulated"?"#b3331f":v==="edited"?"#2f6dab":"#b06a16"; }
function ago(t){ const s=(Date.now()-t)/1000;
  if (s<60) return "just now"; if (s<3600) return Math.floor(s/60)+"m ago";
  if (s<86400) return Math.floor(s/3600)+"h ago"; return Math.floor(s/86400)+"d ago"; }

// permanent worked-example strip — server-fed, ALWAYS shown, independent of
// localStorage (the old seed-once-into-history approach silently no-op'd for
// anyone with stale state or a cached JS bundle). Render directly from the API.
let EXAMPLES = null;
async function renderExamples(){
  const wrap = document.getElementById("examples"), list = document.getElementById("exlist");
  if (!wrap || !list) return;
  if (!EXAMPLES){
    try { EXAMPLES = (await (await fetch("/api/example-history")).json()).items || []; }
    catch(e){ EXAMPLES = []; }
  }
  if (!EXAMPLES.length){ wrap.style.display = "none"; return; }
  wrap.style.display = "";
  list.innerHTML = EXAMPLES.map(x => `
    <div class="hitem clk" data-case="${x.case}" title="Click to load &amp; re-run this test">
      <div class="thumbs">${x.a?`<img src="${x.a}">`:""}${x.b?`<img src="${x.b}">`:""}</div>
      <div class="hmeta"><div><span class="hbadge" style="background:${badgeColor(x.verdict)}">${vLabel(x.verdict)}</span>
        <b>${x.conf??""}%</b></div>
        ${x.title?`<div class="ht">${x.title}</div>`:""}
        ${x.label?`<div class="t">${x.label}</div>`:""}</div>
    </div>`).join("");
  list.querySelectorAll(".hitem.clk").forEach(el =>
    el.addEventListener("click", () => loadCase(el.dataset.case)));
}
async function initHistory(){ renderExamples(); renderHistory(); }

async function loadCase(c){
  try {
    const r = await (await fetch("/api/example?case=" + encodeURIComponent(c))).json();
    if (r.original){
      set("A", r.original, "original"); set("B", r.review, "under review");
      document.getElementById("view-detector").scrollIntoView({behavior:"smooth", block:"start"});
      runAnalysis();           // load AND run, so the verdict shows immediately
    }
  } catch(e){}
}
function renderHistory(){
  const wrap = document.getElementById("hist"), list = document.getElementById("hlist");
  let h = [];
  try { h = JSON.parse(localStorage.getItem(HK) || "[]"); } catch(e){}
  if (!h.length){ wrap.classList.add("hidden"); return; }
  wrap.classList.remove("hidden");
  list.innerHTML = h.map((x,i) => `
    <div class="hitem${x.case?" clk":""}" ${x.case?`data-case="${x.case}"`:""} title="${x.case?"Click to re-run this test":""}">
      <div class="thumbs">${x.a?`<img src="${x.a}">`:""}${x.b?`<img src="${x.b}">`:""}</div>
      <div class="hmeta"><div><span class="hbadge" style="background:${badgeColor(x.verdict)}">${vLabel(x.verdict)}</span>
        <b>${x.conf??""}%</b></div>
        ${x.title?`<div class="ht">${x.title}</div>`:""}
        <div class="t">${x.seed?"sample":(x.mode==="ai"?"AI":"algo")} · ${ago(x.t)}</div></div>
    </div>`).join("");
  list.querySelectorAll(".hitem.clk").forEach(el =>
    el.addEventListener("click", () => loadCase(el.dataset.case)));
}
document.getElementById("histClear").addEventListener("click", () => {
  localStorage.setItem(HK, "[]"); renderHistory();   // examples strip is separate, stays
});

// remember the AI password across visits
(function(){
  const saved = localStorage.getItem("wm_ai_pw");
  if (saved) document.getElementById("pwin").value = saved;
})();

setActive("A");
route();
