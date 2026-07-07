/* PaperCatch viewer logic */
"use strict";

const STORE_KEY = "papercatch.filters.v6";
const CATS_KEY = "papercatch.cats.v6";
const DEFAULT_CATS = [
  { id: "llm", label: "大语言模型", keywords: "LLM,language model,agent,prompt,alignment,reasoning" },
  { id: "cv", label: "计算机视觉", keywords: "vision,image,video,segmentation,detection,VLM,multimodal" },
  { id: "ml", label: "机器学习", keywords: "machine learning,training,optimization,tabular,distillation" },
  { id: "robot", label: "机器人", keywords: "robot,manipulation,grasp,navigation,VLA,embodied" },
  { id: "gen", label: "生成模型", keywords: "generation,diffusion,GAN,VAE,world model" },
  { id: "safety", label: "安全对齐", keywords: "safety,alignment,jailbreak,watermark,refusal,unlearning" },
];
const ARXIV_CATS = ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.RO", "cs.CR", "stat.ML", "cs.SE", "cs.IR", "eess.AS"];

const state = {
  papers: [],
  filtered: [],
  selected: new Set(),
  filters: { query: "", cats: [], startDate: "", endDate: "", minScore: 0, zotero: "all", cn: "all", sort: "date" },
  cats: loadJson(CATS_KEY, DEFAULT_CATS),
  timer: null,
};

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
  Object.assign(state.filters, loadJson(STORE_KEY, {}));
  bind();
  hydrate();
  loadPapers();
});

/* ── 事件绑定 ── */
function bind() {
  $("searchInput").addEventListener("input", debounce(() => {
    state.filters.query = $("searchInput").value.trim();
    $("searchClear").classList.toggle("show", !!state.filters.query);
    render();
  }, 250));
  $("searchInput").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { $("searchInput").value = ""; state.filters.query = ""; render(); }
  });
  $("searchClear").addEventListener("click", () => {
    $("searchInput").value = ""; state.filters.query = "";
    $("searchClear").classList.remove("show");
    $("searchInput").focus();
    render();
  });

  $("refreshBtn").addEventListener("click", loadPapers);
  $("resetBtn").addEventListener("click", resetFilters);
  $("settingsBtn").addEventListener("click", openSettings);
  $("hermesBtn").addEventListener("click", openHermes);

  $("startDate").addEventListener("change", () => { state.filters.startDate = $("startDate").value; render(); });
  $("endDate").addEventListener("change", () => { state.filters.endDate = $("endDate").value; render(); });

  $("scoreRange").addEventListener("input", () => {
    state.filters.minScore = Number($("scoreRange").value);
    $("scoreValue").textContent = state.filters.minScore > 0 ? `≥ ${state.filters.minScore} 分` : "不限";
    render();
  });
  $("sortSelect").addEventListener("change", () => { state.filters.sort = $("sortSelect").value; render(); });

  $("addCatBtn").addEventListener("click", () => {
    $("addCatForm").classList.toggle("hidden");
    if (!$("addCatForm").classList.contains("hidden")) $("newCatLabel").focus();
  });
  $("saveCatBtn").addEventListener("click", saveCategory);

  $("autoRefresh").addEventListener("change", () => {
    clearInterval(state.timer);
    if ($("autoRefresh").checked) state.timer = setInterval(loadPapers, 5 * 60 * 1000);
  });

  $("selectAll").addEventListener("change", () => {
    if ($("selectAll").checked) state.filtered.forEach(p => state.selected.add(p.arxiv_id));
    else state.selected.clear();
    render();
  });
  $("clearSelBtn").addEventListener("click", () => { state.selected.clear(); render(); });
  $("batchZoteroBtn").addEventListener("click", () => addToZotero([...state.selected], $("batchZoteroBtn")));
  $("batchDeleteBtn").addEventListener("click", () => deletePapers([...state.selected], $("batchDeleteBtn")));

  $("hermesSendBtn").addEventListener("click", sendHermes);
  $("hermesInput").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") sendHermes();
  });
  document.querySelectorAll(".hermes-ex").forEach(b =>
    b.addEventListener("click", () => { $("hermesInput").value = b.textContent.trim(); $("hermesInput").focus(); }));

  $("cfgSaveBtn").addEventListener("click", saveSettings);

  document.querySelectorAll("[data-close]").forEach(b =>
    b.addEventListener("click", () => $(b.dataset.close).classList.remove("show")));
  document.querySelectorAll(".modal-backdrop").forEach(m =>
    m.addEventListener("mousedown", (e) => { if (e.target === m) m.classList.remove("show"); }));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") document.querySelectorAll(".modal-backdrop.show").forEach(m => m.classList.remove("show"));
    if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
      e.preventDefault(); $("searchInput").focus();
    }
  });
}

/* ── 控件回填 ── */
function hydrate() {
  $("searchInput").value = state.filters.query || "";
  $("searchClear").classList.toggle("show", !!state.filters.query);
  $("startDate").value = state.filters.startDate || "";
  $("endDate").value = state.filters.endDate || "";
  $("scoreRange").value = state.filters.minScore || 0;
  $("scoreValue").textContent = state.filters.minScore > 0 ? `≥ ${state.filters.minScore} 分` : "不限";
  $("sortSelect").value = state.filters.sort || "date";
  renderDateChips();
  renderZoteroChips();
  renderCnChips();
  renderCatList();
}

function renderDateChips() {
  const opts = [["1", "今天"], ["3", "近 3 天"], ["7", "近 7 天"], ["30", "近 30 天"], ["all", "全部"]];
  const active = activeDateChip();
  $("dateChips").innerHTML = opts.map(([v, l]) =>
    `<button class="chip ${active === v ? "active" : ""}" data-v="${v}">${l}</button>`).join("");
  $("dateChips").querySelectorAll(".chip").forEach(b => b.addEventListener("click", () => {
    if (b.dataset.v === "all") { state.filters.startDate = ""; state.filters.endDate = ""; }
    else {
      const end = new Date(), start = new Date();
      start.setDate(end.getDate() - Number(b.dataset.v) + 1);
      state.filters.startDate = dstr(start);
      state.filters.endDate = dstr(end);
    }
    $("startDate").value = state.filters.startDate;
    $("endDate").value = state.filters.endDate;
    renderDateChips();
    render();
  }));
}

function activeDateChip() {
  const f = state.filters;
  if (!f.startDate && !f.endDate) return "all";
  const today = dstr(new Date());
  if (f.endDate !== today) return "";
  for (const n of [1, 3, 7, 30]) {
    const s = new Date(); s.setDate(s.getDate() - n + 1);
    if (f.startDate === dstr(s)) return String(n);
  }
  return "";
}

function renderZoteroChips() {
  const opts = [["all", "全部"], ["unadded", "未入库"], ["added", "已入库"]];
  $("zoteroChips").innerHTML = opts.map(([v, l]) =>
    `<button class="chip ${state.filters.zotero === v ? "active" : ""}" data-v="${v}">${l}</button>`).join("");
  $("zoteroChips").querySelectorAll(".chip").forEach(b =>
    b.addEventListener("click", () => { state.filters.zotero = b.dataset.v; renderZoteroChips(); render(); }));
}

function renderCnChips() {
  const opts = [["all", "全部"], ["done", "已有中文"], ["pending", "待生成"]];
  $("cnChips").innerHTML = opts.map(([v, l]) =>
    `<button class="chip ${state.filters.cn === v ? "active" : ""}" data-v="${v}">${l}</button>`).join("");
  $("cnChips").querySelectorAll(".chip").forEach(b =>
    b.addEventListener("click", () => { state.filters.cn = b.dataset.v; renderCnChips(); render(); }));
}

function renderCatList() {
  $("categoryList").innerHTML = state.cats.map(c => `
    <label class="check-row">
      <input type="checkbox" value="${escA(c.id)}" ${state.filters.cats.includes(c.id) ? "checked" : ""}>
      <span>${esc(c.label)}</span>
      <button class="del" data-del="${escA(c.id)}" title="删除此方向">×</button>
    </label>`).join("");
  $("categoryList").querySelectorAll("input").forEach(i => i.addEventListener("change", () => {
    state.filters.cats = [...$("categoryList").querySelectorAll("input:checked")].map(x => x.value);
    render();
  }));
  $("categoryList").querySelectorAll(".del").forEach(b => b.addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    state.cats = state.cats.filter(c => c.id !== b.dataset.del);
    state.filters.cats = state.filters.cats.filter(x => x !== b.dataset.del);
    saveJson(CATS_KEY, state.cats);
    renderCatList(); render();
  }));
}

function saveCategory() {
  const label = $("newCatLabel").value.trim();
  const kw = $("newCatKeywords").value.trim();
  if (!label) return toast("请输入方向名", true);
  const id = label.toLowerCase().replace(/[^a-z0-9一-鿿]+/g, "_") || `c${Date.now()}`;
  const ex = state.cats.find(c => c.id === id);
  if (ex) { ex.label = label; ex.keywords = kw || label; }
  else state.cats.push({ id, label, keywords: kw || label });
  saveJson(CATS_KEY, state.cats);
  $("newCatLabel").value = ""; $("newCatKeywords").value = "";
  $("addCatForm").classList.add("hidden");
  renderCatList(); render();
  toast(`已添加方向：${label}`);
}

/* ── 数据 ── */
async function loadPapers() {
  $("summaryText").textContent = "加载中…";
  try {
    const r = await fetch("/api/papers", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    state.papers = (data.papers || []).map(p => ({
      ...p,
      authors: p.authors || [],
      categories: p.categories || [],
      tags: p.tags || [],
      quality_score: p.quality_score == null ? null : Number(p.quality_score),
    }));
    $("updateTime").textContent = "更新于 " + fmtTime(data.updated_at);
    render();
  } catch (e) {
    $("paperList").innerHTML = `<div class="empty"><div class="big">⚠</div>加载失败：${esc(e.message)}</div>`;
    $("summaryText").textContent = "加载失败";
  }
}

function hasCn(p) { return !!(p.title_cn && p.abstract_cn && p.summary_cn); }

function applyFilters() {
  const q = (state.filters.query || "").toLowerCase();
  let out = state.papers.filter(p => {
    if (state.filters.startDate && p.published < state.filters.startDate) return false;
    if (state.filters.endDate && p.published > state.filters.endDate) return false;
    if (state.filters.minScore > 0 && (p.quality_score == null || p.quality_score < state.filters.minScore)) return false;
    if (state.filters.zotero === "added" && p.zotero_status !== "added") return false;
    if (state.filters.zotero === "unadded" && p.zotero_status === "added") return false;
    if (state.filters.cn === "done" && !hasCn(p)) return false;
    if (state.filters.cn === "pending" && hasCn(p)) return false;
    if (state.filters.cats.length) {
      const text = ptext(p);
      const hit = state.filters.cats.some(id => {
        const c = state.cats.find(x => x.id === id);
        return c && String(c.keywords || c.label).split(/[,，]/).some(k => k.trim() && text.includes(k.trim().toLowerCase()));
      });
      if (!hit) return false;
    }
    if (q) {
      const hay = [p.title, p.title_cn, p.abstract, p.abstract_full, p.abstract_cn, p.summary_cn,
        p.authors.join(" "), p.categories.join(" "), p.tags.join(" ")].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const s = state.filters.sort;
  out.sort((a, b) => {
    if (s === "quality") return (b.quality_score || 0) - (a.quality_score || 0) || cmp(b.published, a.published);
    if (s === "citations") return (b.citations || 0) - (a.citations || 0) || cmp(b.published, a.published);
    if (s === "title") return cmp(a.title_cn || a.title, b.title_cn || b.title);
    return cmp(b.published, a.published);
  });
  return out;
}

/* ── 渲染 ── */
function render() {
  saveJson(STORE_KEY, state.filters);
  // prune selection to existing papers
  const ids = new Set(state.papers.map(p => p.arxiv_id));
  [...state.selected].forEach(id => { if (!ids.has(id)) state.selected.delete(id); });

  state.filtered = applyFilters();
  const cnDone = state.papers.filter(hasCn).length;
  $("summaryText").textContent = `显示 ${state.filtered.length} / ${state.papers.length} 篇`;
  $("enrichStat").textContent = state.papers.length
    ? `中文内容：${cnDone}/${state.papers.length} 篇已生成` : "";
  $("searchCount").textContent = state.filters.query ? `${state.filtered.length} 篇` : "";
  $("searchCount").classList.toggle("show", !!state.filters.query);

  renderBatch();
  renderList();
}

function renderBatch() {
  const n = state.selected.size;
  $("batchText").textContent = n ? `已选 ${n} 篇` : "全选本页";
  $("selectAll").checked = state.filtered.length > 0 && state.filtered.every(p => state.selected.has(p.arxiv_id));
  $("clearSelBtn").classList.toggle("hidden", n === 0);
  $("batchZoteroBtn").disabled = n === 0;
  $("batchDeleteBtn").disabled = n === 0;
  $("batchZoteroBtn").textContent = n ? `批量加入 Zotero（${n}）` : "批量加入 Zotero";
  $("batchDeleteBtn").textContent = n ? `批量删除（${n}）` : "批量删除";
}

function renderList() {
  if (!state.filtered.length) {
    $("paperList").innerHTML = `<div class="empty"><div class="big">🍃</div>没有符合条件的论文<br><span class="hint">调整筛选，或点「问 Hermes」搜新论文</span></div>`;
    return;
  }
  $("paperList").innerHTML = state.filtered.map(p => {
    const cn = hasCn(p);
    const mainTitle = p.title_cn || p.title;
    const showEn = !!p.title_cn;
    const abs = p.abstract_cn || p.abstract_full || p.abstract || "";
    const authors = p.authors.slice(0, 5).join("、") + (p.authors.length > 5 ? ` 等 ${p.authors.length} 人` : "");
    return `
    <article class="paper-card" data-id="${escA(p.arxiv_id)}">
      <div class="card-top">
        <div class="card-check"><input type="checkbox" class="sel" ${state.selected.has(p.arxiv_id) ? "checked" : ""}></div>
        <div class="card-titles" title="点击查看详情">
          <div class="title-cn">${esc(mainTitle)}</div>
          ${showEn ? `<div class="title-en">${esc(p.title)}</div>` : ""}
        </div>
        <div class="card-badges">
          ${p.quality_score != null ? `<span class="badge score">${p.quality_score.toFixed(1)} 分</span>` : ""}
          <span class="badge ${p.zotero_status === "added" ? "added" : ""}">${p.zotero_status === "added" ? "已入库" : "未入库"}</span>
          ${cn ? "" : `<span class="badge pending-cn">中文待生成</span>`}
        </div>
      </div>
      <div class="meta-line">${esc(authors)} · ${esc(p.published || "-")} · ${esc(p.categories.slice(0, 3).join(", "))}${p.citations != null ? ` · 引用 ${p.citations}` : ""}</div>
      <div class="abstract clamped">${esc(abs)}</div>
      <button class="expand-toggle">展开摘要 ▾</button>
      ${p.tags.length ? `<div class="tags-row">${p.tags.slice(0, 6).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
      <div class="card-actions">
        <div class="card-actions-left">
          <button class="btn btn-sm act-detail">详情</button>
          <button class="btn btn-sm act-cite">复制引用</button>
          ${p.abs_url ? `<a class="btn btn-sm" href="${escA(p.abs_url)}" target="_blank" rel="noreferrer">arXiv</a>` : ""}
          ${p.pdf_url ? `<a class="btn btn-sm" href="${escA(p.pdf_url)}" target="_blank" rel="noreferrer">PDF</a>` : ""}
          <button class="btn btn-sm act-delete" style="color:var(--zhu-red);border-color:var(--zhu-red)">删除</button>
        </div>
        <button class="btn btn-primary btn-sm act-zotero ${p.zotero_status === "added" ? "added" : ""}" ${p.zotero_status === "added" ? "disabled" : ""}>
          ${p.zotero_status === "added" ? "✓ 已在 Zotero" : "加入 Zotero"}
        </button>
      </div>
    </article>`;
  }).join("");

  $("paperList").querySelectorAll(".paper-card").forEach(card => {
    const id = card.dataset.id;
    const p = state.filtered.find(x => x.arxiv_id === id);
    if (!p) return;
    card.querySelector(".sel").addEventListener("change", (e) => {
      e.target.checked ? state.selected.add(id) : state.selected.delete(id);
      renderBatch();
    });
    card.querySelector(".card-titles").addEventListener("click", () => openDetail(p));
    const absEl = card.querySelector(".abstract");
    const tog = card.querySelector(".expand-toggle");
    // hide toggle if not clamped
    requestAnimationFrame(() => {
      if (absEl.scrollHeight <= absEl.clientHeight + 4) tog.style.display = "none";
    });
    tog.addEventListener("click", () => {
      const clamped = absEl.classList.toggle("clamped");
      tog.textContent = clamped ? "展开摘要 ▾" : "收起 ▴";
    });
    card.querySelector(".act-detail").addEventListener("click", () => openDetail(p));
    card.querySelector(".act-cite").addEventListener("click", () => {
      const c = `${p.authors.join(", ")}. ${p.title}. arXiv:${p.arxiv_id}, ${p.published || ""}.`;
      navigator.clipboard?.writeText(c).then(() => toast("引用已复制"), () => toast("复制失败", true));
    });
    card.querySelector(".act-delete").addEventListener("click", () => deletePapers([id], card.querySelector(".act-delete")));
    const zbtn = card.querySelector(".act-zotero");
    if (p.zotero_status !== "added") zbtn.addEventListener("click", () => addToZotero([id], zbtn));
  });
}

/* ── 详情 ── */
function openDetail(p) {
  $("modalTitle").innerHTML = p.title_cn
    ? `${esc(p.title_cn)}<div class="title-en" style="margin-top:.3rem">${esc(p.title)}</div>`
    : esc(p.title);
  const sec = [];

  sec.push(`<div class="m-section">
    <div class="chips" style="margin-bottom:.3rem">
      ${p.quality_score != null ? `<span class="badge score">${p.quality_score.toFixed(1)} 分</span>` : ""}
      <span class="badge ${p.zotero_status === "added" ? "added" : ""}">${p.zotero_status === "added" ? "已入库" + (p.zotero_collection ? " · " + esc(p.zotero_collection) : "") : "未入库"}</span>
      ${p.citations != null ? `<span class="badge">引用 ${p.citations}</span>` : ""}
      ${p.venue ? `<span class="badge">${esc(p.venue)}</span>` : ""}
      <span class="badge">${esc(p.published || "-")}</span>
    </div>
  </div>`);

  if (p.summary_cn) {
    sec.push(`<div class="m-section"><h3>中文总结</h3><div class="m-text">${esc(p.summary_cn)}</div></div>`);
  }
  if (p.abstract_cn) {
    sec.push(`<div class="m-section"><h3>中文摘要</h3><div class="m-text">${esc(p.abstract_cn)}</div></div>`);
  }
  if (p.background_cn) {
    sec.push(`<div class="m-section"><h3>论文背景</h3><div class="m-text">${esc(p.background_cn)}</div></div>`);
  }
  if (!p.summary_cn && !p.abstract_cn) {
    sec.push(`<div class="m-section"><div class="m-note">中文摘要与总结尚未生成。让 Hermes 运行增强流程即可补全（见 ENRICHMENT_PROMPT.md）。</div></div>`);
  }
  sec.push(`<div class="m-section"><h3>英文摘要</h3><div class="m-text m-en">${esc(p.abstract_full || p.abstract || "")}</div></div>`);

  const meta = [];
  meta.push(`<p><strong>作者：</strong>${esc(p.authors.join("、"))}</p>`);
  if (p.affiliations) meta.push(`<p><strong>单位：</strong>${esc(p.affiliations)}</p>`);
  meta.push(`<p><strong>分类：</strong>${esc(p.categories.join(", "))}</p>`);
  if (p.comment) meta.push(`<p><strong>备注：</strong>${esc(p.comment)}</p>`);
  meta.push(`<p><strong>arXiv ID：</strong>${esc(p.arxiv_id)}</p>`);
  sec.push(`<div class="m-section"><h3>论文信息</h3>${meta.join("")}</div>`);

  if (p.tags.length) {
    sec.push(`<div class="m-section"><h3>标签</h3><div class="tags-row">${p.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div></div>`);
  }

  sec.push(`<div class="m-section" style="display:flex;gap:.5rem;flex-wrap:wrap">
    ${p.abs_url ? `<a class="btn" href="${escA(p.abs_url)}" target="_blank" rel="noreferrer">arXiv 页面</a>` : ""}
    ${p.pdf_url ? `<a class="btn" href="${escA(p.pdf_url)}" target="_blank" rel="noreferrer">下载 PDF</a>` : ""}
    <button class="btn btn-primary" id="modalZotero" ${p.zotero_status === "added" ? "disabled" : ""}>${p.zotero_status === "added" ? "✓ 已在 Zotero" : "加入 Zotero"}</button>
  </div>`);

  $("modalBody").innerHTML = sec.join("");
  const mz = $("modalZotero");
  if (mz && p.zotero_status !== "added") mz.addEventListener("click", () => addToZotero([p.arxiv_id], mz));
  $("detailModal").classList.add("show");
  $("detailModal").scrollTop = 0;
}

/* ── Zotero ── */
async function addToZotero(ids, btn) {
  ids = ids.filter(Boolean);
  if (!ids.length) return;
  const orig = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "正在添加…"; }
  try {
    const r = await fetch("/zotero/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arxiv_ids: ids }),
    });
    const res = await r.json();
    if (!r.ok || !res.success) throw new Error(res.error || "添加失败");
    (res.results || []).forEach(it => {
      const p = state.papers.find(x => x.arxiv_id === it.arxiv_id);
      if (p && it.status === "added") { p.zotero_status = "added"; p.zotero_collection = it.collection; }
    });
    state.selected.clear();
    render();
    if (res.failed > 0) toast(`成功 ${res.added} 篇，失败 ${res.failed} 篇`, true);
    else toast(`已加入 Zotero：${res.added} 篇`);
  } catch (e) {
    const msg = /not configured/i.test(e.message)
      ? "Zotero 未配置：运行 python start.py --setup 填入 API key"
      : `Zotero 失败：${e.message}`;
    toast(msg, true);
    if (btn) { btn.disabled = false; btn.textContent = orig; }
  }
}

/* ── 删除论文 ── */
async function deletePapers(ids, btn) {
  ids = ids.filter(Boolean);
  if (!ids.length) return;

  const count = ids.length;
  const confirmMsg = count === 1
    ? "确定要删除这篇论文吗？\n删除后无法恢复。"
    : `确定要删除选中的 ${count} 篇论文吗？\n删除后无法恢复。`;

  if (!confirm(confirmMsg)) return;

  const orig = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "正在删除…"; }

  try {
    const r = await fetch("/api/papers", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arxiv_ids: ids }),
    });
    const res = await r.json();
    if (!r.ok || !res.success) throw new Error(res.error || "删除失败");

    // 从本地状态中移除
    state.papers = state.papers.filter(p => !ids.includes(p.arxiv_id));
    state.selected.clear();

    // 如果在详情页且删除的是当前论文，关闭详情页
    if (count === 1 && $("detailModal").classList.contains("show")) {
      $("detailModal").classList.remove("show");
    }

    render();
    toast(`已删除 ${res.removed || count} 篇论文`);
  } catch (e) {
    toast(`删除失败：${e.message}`, true);
    if (btn) { btn.disabled = false; btn.textContent = orig; }
  }
}

/* ── Hermes ── */
function openHermes() {
  if (!$("hermesMsgs").children.length) {
    addMsg("bot", "你好，我可以帮你搜 arXiv 论文。说清楚：研究方向、篇数、时间范围，以及要不要加入 Zotero。");
  }
  $("hermesModal").classList.add("show");
  $("hermesInput").focus();
}

function addMsg(role, text) {
  const d = document.createElement("div");
  d.className = `msg ${role}`;
  d.textContent = text;
  $("hermesMsgs").appendChild(d);
  $("hermesMsgs").scrollTop = $("hermesMsgs").scrollHeight;
  return d;
}

async function sendHermes() {
  const text = $("hermesInput").value.trim();
  if (!text) return;
  $("hermesInput").value = "";
  addMsg("user", text);
  const pending = addMsg("bot", "正在搜索 arXiv…");
  pending.classList.add("loading");
  $("hermesSendBtn").disabled = true;
  try {
    const r = await fetch("/hermes/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const res = await r.json();
    if (!r.ok || !res.success) throw new Error(res.error || "搜索失败");
    pending.classList.remove("loading");
    pending.textContent = res.message || "完成";
    if (res.papers?.length) {
      await loadPapers();
      const titles = res.papers.slice(0, 5).map((p, i) => `${i + 1}. ${p.title}`).join("\n");
      addMsg("bot", `新论文（前 ${Math.min(5, res.papers.length)} 篇）：\n${titles}${res.papers.length > 5 ? "\n…" : ""}`);
    }
  } catch (e) {
    pending.classList.remove("loading");
    pending.textContent = `搜索失败：${e.message}`;
  } finally {
    $("hermesSendBtn").disabled = false;
  }
}

/* ── 搜索设置（存服务器） ── */
async function openSettings() {
  let cfg = { categories: ["cs.AI", "cs.CL", "cs.CV", "cs.LG"], keywords: "", max_per_cat: 25, days: 1 };
  try {
    const r = await fetch("/api/config");
    if (r.ok) cfg = { ...cfg, ...(await r.json()) };
  } catch (_) {}
  $("cfgKeywords").value = cfg.keywords || "";
  $("cfgMax").value = cfg.max_per_cat || 25;
  $("cfgDays").value = cfg.days ?? 1;
  $("cfgCats").innerHTML = ARXIV_CATS.map(c =>
    `<button class="chip ${cfg.categories.includes(c) ? "active" : ""}" data-c="${c}">${c}</button>`).join("");
  $("cfgCats").querySelectorAll(".chip").forEach(b =>
    b.addEventListener("click", () => b.classList.toggle("active")));
  $("settingsModal").classList.add("show");
}

async function saveSettings() {
  const cats = [...$("cfgCats").querySelectorAll(".chip.active")].map(b => b.dataset.c);
  const cfg = {
    categories: cats.length ? cats : ["cs.AI", "cs.CL", "cs.CV", "cs.LG"],
    keywords: $("cfgKeywords").value.trim(),
    max_per_cat: Number($("cfgMax").value) || 25,
    days: Number($("cfgDays").value) || 0,
  };
  try {
    const r = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    $("settingsModal").classList.remove("show");
    toast("设置已保存到服务器");
  } catch (e) {
    toast(`保存失败：${e.message}`, true);
  }
}

/* ── 其他 ── */
function resetFilters() {
  state.filters = { query: "", cats: [], startDate: "", endDate: "", minScore: 0, zotero: "all", cn: "all", sort: "date" };
  hydrate();
  render();
}

let toastTimer = null;
function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("error", !!isErr);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
}

function ptext(p) {
  return [p.title, p.title_cn, p.abstract, p.abstract_full, p.abstract_cn,
    (p.categories || []).join(" "), (p.tags || []).join(" ")].join(" ").toLowerCase();
}
function cmp(a, b) { return String(a || "").localeCompare(String(b || "")); }
function dstr(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
function fmtTime(v) {
  if (!v) return "-";
  const d = new Date(v);
  return isNaN(d) ? v : d.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function escA(s) { return esc(s); }
function loadJson(k, fb) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fb; } catch { return fb; } }
function saveJson(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
