/* PaperCatch viewer logic */
"use strict";

const STORE_KEY = "papercatch.filters.v6";
const CATS_KEY = "papercatch.cats.v6";
const DEFAULT_SOURCES = ["arxiv"];
const SOURCE_LABELS = {
  arxiv: "arXiv",
  openalex: "OpenAlex",
  crossref: "Crossref",
  semantic_scholar: "Semantic Scholar",
  europe_pmc: "Europe PMC",
};
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
  sources: DEFAULT_SOURCES.slice(),
  availableSources: DEFAULT_SOURCES.slice(),
  agentPaper: null,
  agentMode: "ask",
  detailPaperId: "",
  downloading: new Set(),
  timer: null,
};

const $ = (id) => document.getElementById(id);
const modalFocusOrigins = new WeakMap();
const MODAL_FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

function openModal(modalId, focusTarget, returnFocus = document.activeElement) {
  const modal = $(modalId);
  if (!modal) return;
  if (returnFocus && typeof returnFocus.focus === "function") modalFocusOrigins.set(modal, returnFocus);
  modal.classList.add("show");
  modal.setAttribute("aria-hidden", "false");
  modal.scrollTop = 0;
  (focusTarget || modal.querySelector(".modal"))?.focus();
}

function closeModal(modalId) {
  const modal = typeof modalId === "string" ? $(modalId) : modalId;
  if (!modal || !modal.classList.contains("show")) return;
  modal.classList.remove("show");
  modal.setAttribute("aria-hidden", "true");
  if (modal.id === "detailModal") state.detailPaperId = "";
  const origin = modalFocusOrigins.get(modal);
  modalFocusOrigins.delete(modal);
  if (origin?.isConnected) origin.focus();
}

function cycleModalFocus(event, focusable, activeElement) {
  if (event.key !== "Tab" || !focusable.length) return false;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const outside = !focusable.includes(activeElement);
  if (event.shiftKey && (activeElement === first || outside)) {
    event.preventDefault();
    last.focus();
    return true;
  }
  if (!event.shiftKey && (activeElement === last || outside)) {
    event.preventDefault();
    first.focus();
    return true;
  }
  return false;
}

function trapModalFocus(event, modal) {
  const focusable = [...modal.querySelectorAll(MODAL_FOCUSABLE)]
    .filter(element => element.getClientRects().length > 0);
  if (!focusable.length) {
    event.preventDefault();
    modal.querySelector(".modal")?.focus();
    return true;
  }
  return cycleModalFocus(event, focusable, document.activeElement);
}

function sourceLabel(source) {
  return SOURCE_LABELS[source] || String(source || "").replace(/_/g, " ").replace(/\b\w/g, ch => ch.toUpperCase());
}

function normalizeSourceItems(items, fallback = DEFAULT_SOURCES) {
  const list = Array.isArray(items) ? items : [];
  const normalized = list.map(item => {
    if (typeof item === "string") {
      const id = item.trim();
      return id ? { id, label: sourceLabel(id) } : null;
    }
    const id = String(item?.id || item?.source || item?.key || "").trim();
    if (!id) return null;
    return { id, label: String(item?.label || item?.name || sourceLabel(id)) };
  }).filter(Boolean);
  if (normalized.length) return normalized;
  return fallback.map(id => ({ id, label: sourceLabel(id) }));
}

function renderSourceChips(selectedSources = state.sources) {
  const chips = $("sourceChips");
  if (!chips) return;
  const sources = normalizeSourceItems(state.availableSources);
  const selected = new Set((Array.isArray(selectedSources) ? selectedSources : DEFAULT_SOURCES).map(String));
  chips.innerHTML = sources.map(source => {
    const active = selected.has(source.id);
    return `<button class="chip ${active ? "active" : ""}" data-source="${escA(source.id)}" aria-pressed="${active ? "true" : "false"}" type="button">${esc(source.label)}</button>`;
  }).join("");
  chips.querySelectorAll(".chip").forEach(chip => chip.addEventListener("click", () => {
    chip.classList.toggle("active");
    chip.setAttribute("aria-pressed", chip.classList.contains("active") ? "true" : "false");
  }));
}

function currentAgentPaper() {
  return state.agentPaper || state.papers.find(p => p.arxiv_id === state.lastAgentPaperId) || null;
}

function setAgentMode(mode) {
  state.agentMode = mode === "notes" ? "notes" : "ask";
  const askActive = state.agentMode === "ask";
  $("agentAskTab")?.classList.toggle("active", askActive);
  $("agentNotesTab")?.classList.toggle("active", !askActive);
  $("agentAskTab")?.setAttribute("aria-pressed", askActive ? "true" : "false");
  $("agentNotesTab")?.setAttribute("aria-pressed", askActive ? "false" : "true");
  if ($("agentAskPanel")) $("agentAskPanel").hidden = !askActive;
  if ($("agentNotesPanel")) $("agentNotesPanel").hidden = askActive;
  if ($("agentModeHint")) {
    $("agentModeHint").textContent = askActive
      ? "针对当前论文提问，回答会显示 grounding 结果和证据。"
      : "生成可直接复制到 Obsidian / Markdown 的学习笔记。";
  }
}

function clearAgentOutputs() {
  if ($("agentStatus")) $("agentStatus").textContent = "尚未提问。";
  if ($("agentGrounded")) $("agentGrounded").textContent = "";
  if ($("agentAnswer")) $("agentAnswer").textContent = "";
  if ($("agentEvidence")) $("agentEvidence").innerHTML = "";
  if ($("agentNotesEvidence")) $("agentNotesEvidence").innerHTML = "";
  if ($("agentMarkdown")) $("agentMarkdown").textContent = "";
  if ($("agentEmpty")) $("agentEmpty").classList.remove("hidden");
}

function renderAgentPaperMeta(paper) {
  if (!paper) return;
  const sources = Array.isArray(paper.sources) && paper.sources.length
    ? `来源：${paper.sources.map(sourceLabel).join(" / ")}`
    : "";
  $("agentPaperMeta").textContent = [paper.title_cn || paper.title || "", paper.arxiv_id || "", sources].filter(Boolean).join(" · ");
}

function formatAgentEvidence(items, fallbackLabel = "证据") {
  const list = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (!item) continue;
    if (typeof item === "string") {
      list.push({ label: fallbackLabel, quote: item });
      continue;
    }
    const label = String(item.label || item.field || item.source || fallbackLabel);
    const quote = String(item.quote || item.text || item.value || item.snippet || item.message || "");
    list.push({ label, quote: quote || label });
  }
  if (!list.length) return `<div class="m-note">暂无证据。</div>`;
  return list.map(item => `
    <div class="agent-evidence-item">
      <div class="agent-evidence-title">${esc(item.label)}</div>
      <div class="m-text">${esc(item.quote)}</div>
    </div>
  `).join("");
}

function showAgentResult(mode, res) {
  const grounded = Boolean(res?.grounded);
  if ($("agentStatus")) {
    $("agentStatus").textContent = res?.message || `${grounded ? "grounded：是" : "grounded：否"}${res?.answer ? ` · ${res.answer}` : ""}`;
  }
  if ($("agentGrounded")) {
    $("agentGrounded").textContent = grounded ? "grounded：是" : "grounded：否";
  }
  if ($("agentEmpty")) $("agentEmpty").classList.add("hidden");

  if (mode === "ask") {
    if ($("agentAnswer")) $("agentAnswer").textContent = res?.answer || res?.message || "";
    if ($("agentEvidence")) $("agentEvidence").innerHTML = formatAgentEvidence(res?.evidence, "证据");
  } else {
    if ($("agentAnswer")) $("agentAnswer").textContent = res?.summary || res?.answer || res?.message || "";
    if ($("agentNotesEvidence")) $("agentNotesEvidence").innerHTML = formatAgentEvidence(res?.evidence || res?.evidence_items || res?.evidence_fields, "字段");
    if ($("agentMarkdown")) $("agentMarkdown").textContent = res?.markdown || "";
  }
}

async function callPaperAgent(endpoint, payload, mode, busyButton) {
  const paper = currentAgentPaper();
  if (!paper) return toast("请先打开一篇论文", true);
  if (!paper.arxiv_id) return toast("当前论文缺少可识别的 ID", true);
  if (busyButton) {
    busyButton.disabled = true;
    busyButton.dataset.originalText = busyButton.textContent;
    busyButton.textContent = "处理中…";
  }
  try {
    const r = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const res = await r.json();
    if (!r.ok || !res.success) throw new Error(apiErrorMessage(res, mode === "ask" ? "提问失败" : "生成笔记失败"));
    showAgentResult(mode, res);
  } catch (e) {
    if ($("agentStatus")) $("agentStatus").textContent = `${mode === "ask" ? "提问" : "生成笔记"}失败：${e.message}`;
    if ($("agentGrounded")) $("agentGrounded").textContent = "";
    toast(`${mode === "ask" ? "提问" : "生成笔记"}失败：${e.message}`, true);
  } finally {
    if (busyButton) {
      busyButton.disabled = false;
      busyButton.textContent = busyButton.dataset.originalText || busyButton.textContent;
      delete busyButton.dataset.originalText;
    }
  }
}

async function submitPaperAgentAsk() {
  const paper = currentAgentPaper();
  const question = $("agentQuestion")?.value.trim();
  if (!paper) return toast("请先打开一篇论文", true);
  if (!question) return toast("请先输入问题", true);
  await callPaperAgent("/hermes/ask", { paper_id: paper.arxiv_id, question }, "ask", $("agentAskBtn"));
}

async function submitPaperAgentNotes() {
  const paper = currentAgentPaper();
  const focus = $("agentFocus")?.value.trim();
  if (!paper) return toast("请先打开一篇论文", true);
  if (!focus) return toast("请先填写学习关注点", true);
  await callPaperAgent("/hermes/notes", { paper_id: paper.arxiv_id, focus }, "notes", $("agentNotesBtn"));
}

function openPaperAgent(paper, mode = "ask", returnFocus = document.activeElement) {
  state.agentPaper = paper;
  state.lastAgentPaperId = paper?.arxiv_id || "";
  renderAgentPaperMeta(paper);
  clearAgentOutputs();
  setAgentMode(mode);
  openModal("paperAgentModal", mode === "notes" ? $("agentFocus") : $("agentQuestion"), returnFocus);
}

function copyAgentMarkdown() {
  const markdown = $("agentMarkdown")?.textContent.trim();
  if (!markdown) return toast("当前没有可复制的 Markdown", true);
  navigator.clipboard?.writeText(markdown).then(
    () => toast("Markdown 已复制"),
    () => toast("复制 Markdown 失败", true),
  );
}

function paperIdentity(paper) {
  return String(paper?.paper_id || paper?.arxiv_id || paper?.doi || paper?.pmid || "").trim();
}

function hasDownloadablePdf(paper) {
  return Boolean(paper?.open_access === true && String(paper?.pdf_url || "").trim());
}

function isDownloadedStatus(status) {
  return status === "downloaded" || status === "already_exists";
}

function isDownloadingPaper(paper) {
  return state.downloading.has(paperIdentity(paper));
}

function showDownloadAction(paper) {
  return hasDownloadablePdf(paper) || isDownloadedStatus(paper?.download_status);
}

function downloadButtonLabel(paper) {
  if (isDownloadingPaper(paper)) return "保存中…";
  return isDownloadedStatus(paper?.download_status) ? "PDF 已保存" : "保存 PDF";
}

function downloadButtonDisabled(paper) {
  return isDownloadingPaper(paper) || isDownloadedStatus(paper?.download_status);
}

function buildDownloadPayload(paper) {
  const stableId = String(paper?.paper_id || paper?.doi || paper?.pmid || "").trim();
  if (stableId) return { paper_ids: [stableId] };
  const arxivId = String(paper?.arxiv_id || "").trim();
  if (arxivId) return { arxiv_ids: [arxivId] };
  return null;
}

function downloadFeedbackMessage(result) {
  switch (result?.status) {
    case "downloaded":
      return "开放获取 PDF 已保存";
    case "already_exists":
      return "PDF 已保存，已复用现有文件";
    case "no_authorized_pdf_found":
      return "未找到可授权保存的开放获取 PDF";
    case "invalid_pdf":
      return "获取到的 PDF 无效，未保存";
    case "failed_after_retry":
      return "保存 PDF 失败：重试后仍未成功";
    case "not_found":
      return "论文不存在或已被移除";
    default:
      return `保存 PDF 失败：${result?.reason || result?.status || "未知错误"}`;
  }
}

function updatePaperDownloadState(paper, result) {
  const requestedKey = paperIdentity(paper);
  const resultKey = paperIdentity(result);
  for (const current of state.papers) {
    const currentKey = paperIdentity(current);
    if (![currentKey, current.arxiv_id].includes(requestedKey) && ![currentKey, current.arxiv_id].includes(resultKey)) continue;
    current.download_status = result?.status || "";
    current.download_reason = result?.reason || "";
    current.downloaded_at = result?.downloaded_at || "";
    if (result?.paper_id) current.paper_id = result.paper_id;
    if (result?.arxiv_id) current.arxiv_id = result.arxiv_id;
    if (result?.status === "downloaded" || result?.status === "already_exists") {
      if (result?.file_path) current.pdf_path = result.file_path;
    }
  }
}

function findPaperByIdentity(paper) {
  const key = paperIdentity(paper);
  return state.papers.find(current => paperIdentity(current) === key || (paper?.arxiv_id && current.arxiv_id === paper.arxiv_id)) || paper;
}

function refreshPaperViews(paper, returnFocus = document.activeElement) {
  const current = findPaperByIdentity(paper);
  const detailOpenForPaper = $("detailModal")?.classList.contains("show")
    && state.detailPaperId
    && state.detailPaperId === paperIdentity(current);
  render();
  if (detailOpenForPaper) openDetail(findPaperByIdentity(current), returnFocus);
}

async function downloadPaper(paper, button = null) {
  if (!hasDownloadablePdf(paper) && !isDownloadedStatus(paper?.download_status)) {
    toast("仅明确开放获取且带 PDF 链接的论文支持保存", true);
    return;
  }
  const payload = buildDownloadPayload(paper);
  if (!payload) {
    toast("当前论文缺少可识别的稳定 ID", true);
    return;
  }

  const key = paperIdentity(paper);
  if (state.downloading.has(key)) return;
  state.downloading.add(key);
  refreshPaperViews(paper, button || document.activeElement);

  try {
    const r = await fetch("/api/papers/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const res = await r.json();
    if (!r.ok || !res.success) throw new Error(apiErrorMessage(res, `保存 PDF 失败（HTTP ${r.status}）`));
    const result = (res.results || [])[0];
    if (!result) throw new Error("下载接口未返回结果");
    updatePaperDownloadState(paper, result);
    toast(downloadFeedbackMessage(result), !isDownloadedStatus(result.status));
  } catch (e) {
    toast(`保存 PDF 失败：${e.message}`, true);
  } finally {
    state.downloading.delete(key);
    refreshPaperViews(paper, button || document.activeElement);
  }
}

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
  $("agentAskBtn").addEventListener("click", submitPaperAgentAsk);
  $("agentNotesBtn").addEventListener("click", submitPaperAgentNotes);
  $("agentCopyMarkdownBtn").addEventListener("click", copyAgentMarkdown);
  $("agentAskTab").addEventListener("click", () => setAgentMode("ask"));
  $("agentNotesTab").addEventListener("click", () => setAgentMode("notes"));
  $("agentQuestion").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submitPaperAgentAsk();
  });
  $("agentFocus").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submitPaperAgentNotes();
  });
  document.querySelectorAll(".hermes-ex").forEach(b =>
    b.addEventListener("click", () => { $("hermesInput").value = b.textContent.trim(); $("hermesInput").focus(); }));

  $("cfgSaveBtn").addEventListener("click", saveSettings);
  $("zoteroCfgSaveBtn").addEventListener("click", saveZoteroSettings);
  $("filterToggle").addEventListener("change", syncFilterToggle);
  syncFilterToggle();

  document.querySelectorAll("[data-close]").forEach(b =>
    b.addEventListener("click", () => closeModal(b.dataset.close)));
  document.querySelectorAll(".modal-backdrop").forEach(m =>
    m.addEventListener("mousedown", (e) => { if (e.target === m) closeModal(m); }));
  document.addEventListener("keydown", (e) => {
    const openModals = [...document.querySelectorAll(".modal-backdrop.show")];
    if (e.key === "Tab" && openModals.length) {
      trapModalFocus(e, openModals.at(-1));
      return;
    }
    if (e.key === "Escape" && openModals.length) {
      e.preventDefault();
      closeModal(openModals.at(-1));
      return;
    }
    if (e.key === "/" && !openModals.length && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
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
  renderSourceChips();
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
      paper_id: p.paper_id || "",
      doi: p.doi || "",
      pmid: p.pmid || "",
      open_access: p.open_access === true,
      authors: p.authors || [],
      categories: p.categories || [],
      tags: p.tags || [],
      download_status: p.download_status || "",
      download_reason: p.download_reason || "",
      downloaded_at: p.downloaded_at || "",
      pdf_path: p.pdf_path || "",
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
  state.filtered = applyFilters();
  retainVisibleSelection(state.selected, state.filtered);
  const cnDone = state.papers.filter(hasCn).length;
  $("summaryText").textContent = `显示 ${state.filtered.length} / ${state.papers.length} 篇`;
  $("enrichStat").textContent = state.papers.length
    ? `中文内容：${cnDone}/${state.papers.length} 篇已生成` : "";
  $("searchCount").textContent = state.filters.query ? `${state.filtered.length} 篇` : "";
  $("searchCount").classList.toggle("show", !!state.filters.query);

  renderBatch();
  renderList();
}

function retainVisibleSelection(selected, papers) {
  const visibleIds = new Set(papers.map(p => p.arxiv_id));
  [...selected].forEach(id => { if (!visibleIds.has(id)) selected.delete(id); });
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
    const canSavePdf = showDownloadAction(p);
    const pdfSaved = isDownloadedStatus(p.download_status);
    const pdfDownloading = isDownloadingPaper(p);
    const downloadDisabled = pdfDownloading || pdfSaved;
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
          ${pdfSaved ? `<span class="badge added">PDF 已保存</span>` : ""}
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
          <button class="btn btn-sm act-agent-ask">问这篇论文</button>
          <button class="btn btn-sm act-agent-notes">生成学习笔记</button>
          ${canSavePdf ? `<button class="btn btn-sm act-download ${pdfSaved ? "added" : ""}" ${downloadDisabled ? "disabled" : ""}>${downloadButtonLabel(p)}</button>` : ""}
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
    card.querySelector(".act-agent-ask").addEventListener("click", () => openPaperAgent(p, "ask"));
    card.querySelector(".act-agent-notes").addEventListener("click", () => openPaperAgent(p, "notes"));
    card.querySelector(".act-download")?.addEventListener("click", () => downloadPaper(p, card.querySelector(".act-download")));
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
function openDetail(p, returnFocus = document.activeElement) {
  const pdfSaved = isDownloadedStatus(p.download_status);
  const pdfDownloading = isDownloadingPaper(p);
  const downloadDisabled = pdfDownloading || pdfSaved;
  const canSavePdf = showDownloadAction(p);
  state.detailPaperId = paperIdentity(p);
  $("modalTitle").innerHTML = p.title_cn
    ? `${esc(p.title_cn)}<div class="title-en" style="margin-top:.3rem">${esc(p.title)}</div>`
    : esc(p.title);
  const sec = [];

  sec.push(`<div class="m-section">
    <div class="chips" style="margin-bottom:.3rem">
      ${p.quality_score != null ? `<span class="badge score">${p.quality_score.toFixed(1)} 分</span>` : ""}
      <span class="badge ${p.zotero_status === "added" ? "added" : ""}">${p.zotero_status === "added" ? "已入库" + (p.zotero_collection ? " · " + esc(p.zotero_collection) : "") : "未入库"}</span>
      ${pdfSaved ? `<span class="badge added">PDF 已保存</span>` : ""}
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
    <button class="btn" id="modalAskAgent">问这篇论文</button>
    <button class="btn" id="modalNotesAgent">生成学习笔记</button>
    ${canSavePdf ? `<button class="btn ${pdfSaved ? "added" : ""}" id="modalDownload" ${downloadDisabled ? "disabled" : ""}>${downloadButtonLabel(p)}</button>` : ""}
    ${p.abs_url ? `<a class="btn" href="${escA(p.abs_url)}" target="_blank" rel="noreferrer">arXiv 页面</a>` : ""}
    ${p.pdf_url ? `<a class="btn" href="${escA(p.pdf_url)}" target="_blank" rel="noreferrer">下载 PDF</a>` : ""}
    <button class="btn btn-primary" id="modalZotero" ${p.zotero_status === "added" ? "disabled" : ""}>${p.zotero_status === "added" ? "✓ 已在 Zotero" : "加入 Zotero"}</button>
  </div>`);

  $("modalBody").innerHTML = sec.join("");
  $("modalAskAgent")?.addEventListener("click", () => openPaperAgent(p, "ask"));
  $("modalNotesAgent")?.addEventListener("click", () => openPaperAgent(p, "notes"));
  $("modalDownload")?.addEventListener("click", () => downloadPaper(p, $("modalDownload")));
  const mz = $("modalZotero");
  if (mz && p.zotero_status !== "added") mz.addEventListener("click", () => addToZotero([p.arxiv_id], mz));
  openModal("detailModal", $("detailModal").querySelector(".modal"), returnFocus);
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
    if (!r.ok || !res.success) throw new Error(apiErrorMessage(res, "添加失败"));
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
      ? "Zotero 未配置：请在“设置 → Zotero 集成”填写 User ID 和 API Key；源码也可执行 python start.py --setup，桌面配置位于 %LOCALAPPDATA%\\PaperCatch\\config.local.json（zotero.user_id / zotero.api_key）"
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
    if (!r.ok || !res.success) throw new Error(apiErrorMessage(res, "删除失败"));

    // 从本地状态中移除
    state.papers = state.papers.filter(p => !ids.includes(p.arxiv_id));
    state.selected.clear();

    // 如果在详情页且删除的是当前论文，关闭详情页
    if (count === 1 && $("detailModal").classList.contains("show")) {
      closeModal("detailModal");
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
  openModal("hermesModal", $("hermesInput"));
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
    if (!r.ok || !res.success) throw new Error(apiErrorMessage(res, "搜索失败"));
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
  const returnFocus = document.activeElement;
  let cfg = { categories: ["cs.AI", "cs.CL", "cs.CV", "cs.LG"], keywords: "", max_per_cat: 25, days: 1 };
  let sources = DEFAULT_SOURCES.slice();
  let zotero = { configured: false, user_id: "", default_collection: "PaperCatch/Hermes Search" };
  try {
    const r = await fetch("/api/config");
    if (r.ok) cfg = { ...cfg, ...(await r.json()) };
  } catch (_) {}
  try {
    const r = await fetch("/api/sources");
    if (r.ok) {
      const res = await r.json();
      sources = normalizeSourceItems(res.sources).map(item => item.id);
      state.availableSources = normalizeSourceItems(res.sources);
    }
  } catch (_) {
    state.availableSources = normalizeSourceItems(DEFAULT_SOURCES);
  }
  state.sources = normalizeSourceItems(cfg.sources || sources).map(item => item.id);
  try {
    const r = await fetch("/api/integrations");
    const res = await r.json();
    if (!r.ok) throw new Error(apiErrorMessage(res, `读取 Zotero 设置失败（HTTP ${r.status}）`));
    zotero = { ...zotero, ...(res.zotero || {}) };
  } catch (e) {
    toast(`读取 Zotero 设置失败：${e.message}`, true);
  }

  $("cfgKeywords").value = cfg.keywords || "";
  $("cfgMax").value = cfg.max_per_cat || 25;
  $("cfgDays").value = cfg.days ?? 1;
  $("cfgCats").innerHTML = ARXIV_CATS.map(c =>
    `<button class="chip ${cfg.categories.includes(c) ? "active" : ""}" data-c="${c}">${c}</button>`).join("");
  $("cfgCats").querySelectorAll(".chip").forEach(b =>
    b.addEventListener("click", () => b.classList.toggle("active")));
  renderSourceChips(state.sources);
  renderZoteroSettings(zotero);
  openModal("settingsModal", $("cfgKeywords"), returnFocus);
}

async function saveSettings() {
  const cats = [...$("cfgCats").querySelectorAll(".chip.active")].map(b => b.dataset.c);
  const sources = [...$("sourceChips").querySelectorAll(".chip.active")].map(b => b.dataset.source);
  const cfg = {
    categories: cats.length ? cats : ["cs.AI", "cs.CL", "cs.CV", "cs.LG"],
    keywords: $("cfgKeywords").value.trim(),
    max_per_cat: Number($("cfgMax").value) || 25,
    days: Number($("cfgDays").value) || 0,
    sources: sources.length ? sources : DEFAULT_SOURCES,
  };
  try {
    const r = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    const res = await r.json();
    if (!r.ok || !res.success) throw new Error(apiErrorMessage(res, `保存搜索设置失败（HTTP ${r.status}）`));
    state.sources = cfg.sources;
    closeModal("settingsModal");
    toast("设置已保存到服务器");
  } catch (e) {
    toast(`保存失败：${e.message}`, true);
  }
}

function renderZoteroSettings(zotero = {}) {
  const configured = Boolean(zotero.configured);
  $("zoteroCfgStatus").textContent = configured ? "已配置，可直接加入 Zotero" : "未配置，请填写 Zotero 凭据";
  $("zoteroCfgStatus").className = `m-note zotero-status ${configured ? "configured" : "unconfigured"}`;
  $("zoteroUserId").value = String(zotero.user_id || "");
  // GET never includes the key. Always clear the password field to avoid stale secrets.
  $("zoteroApiKey").value = "";
  $("zoteroDefaultCollection").value = String(zotero.default_collection || "PaperCatch/Hermes Search");
}

async function saveZoteroSettings() {
  const requiredFields = [$("zoteroUserId"), $("zoteroDefaultCollection")];
  if (!requiredFields.every(field => field.reportValidity())) return;
  const btn = $("zoteroCfgSaveBtn");
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在保存…";
  const zotero = {
    api_key: $("zoteroApiKey").value.trim(),
    user_id: $("zoteroUserId").value.trim(),
    default_collection: $("zoteroDefaultCollection").value.trim(),
  };
  try {
    const r = await fetch("/api/integrations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ zotero }),
    });
    const res = await r.json();
    if (!r.ok || !res.success) throw new Error(apiErrorMessage(res, `保存 Zotero 设置失败（HTTP ${r.status}）`));
    renderZoteroSettings(res.zotero || zotero);
    toast("Zotero 设置已保存");
  } catch (e) {
    toast(`保存 Zotero 设置失败：${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

function syncFilterToggle(toggle, label) {
  if (toggle?.target?.id === "filterToggle") toggle = toggle.target;
  toggle ||= $("filterToggle");
  label ||= $("filterToggleLabel");
  if (!toggle || !label) return;
  const expanded = Boolean(toggle.checked);
  toggle.setAttribute("aria-expanded", String(expanded));
  label.textContent = expanded ? "收起筛选条件" : "展开全部筛选条件";
}

/* ── 其他 ── */
function resetFilters() {
  state.filters = { query: "", cats: [], startDate: "", endDate: "", minScore: 0, zotero: "all", cn: "all", sort: "date" };
  hydrate();
  render();
}

let toastTimer = null;
let toastCleanupTimer = null;
function apiErrorMessage(response, fallback) {
  const error = response?.error;
  if (typeof error === "string") return error;
  return error?.message || fallback;
}

function toast(msg, isErr) {
  const t = $("toast");
  clearTimeout(toastTimer);
  clearTimeout(toastCleanupTimer);
  t.setAttribute("role", isErr ? "alert" : "status");
  t.setAttribute("aria-live", isErr ? "assertive" : "polite");
  t.textContent = msg;
  t.classList.toggle("error", !!isErr);
  t.classList.add("show");
  document.body.style.setProperty("--toast-height", `${Math.ceil(t.getBoundingClientRect().height)}px`);
  document.body.classList.add("toast-visible");
  toastTimer = setTimeout(() => {
    t.classList.remove("show");
    toastCleanupTimer = setTimeout(() => {
      if (t.classList.contains("show")) return;
      document.body.classList.remove("toast-visible");
      document.body.style.removeProperty("--toast-height");
    }, 260);
  }, 3200);
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
