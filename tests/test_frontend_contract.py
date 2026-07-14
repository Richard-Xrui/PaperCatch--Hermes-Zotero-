"""Small behavior checks for frontend state and accessibility helpers."""

import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = PROJECT_ROOT / "viewer" / "app.js"
INDEX_HTML = PROJECT_ROOT / "viewer" / "index.html"
FRONTEND_SPEC = PROJECT_ROOT / "docs" / "FRONTEND_SPEC.md"
NODE = shutil.which("node")


def run_node(script):
    return subprocess.run(
        [NODE, "-e", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )


def extract_function(source, name):
    match = re.search(
        rf"(?:async\s+)?function {name}\([^)]*\) \{{.*?^\}}",
        source,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        match = re.search(
            rf"(?:async\s+)?function {name}\([^)]*\) \{{[^\n]*\}}",
            source,
        )
    if match is None:
        raise AssertionError(f"{name} helper is missing")
    return match.group(0)


def run_node_with_functions(source, function_names, body):
    fragments = [extract_function(source, name) for name in function_names]
    fragments.append(body)
    return run_node("\n".join(fragments))


class ElementAttributeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.by_id = {}
        self.dialogs = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if element_id := attributes.get("id"):
            self.by_id[element_id] = (tag, attributes)
        if attributes.get("role") == "dialog":
            self.dialogs.append((tag, attributes))


class FrontendApiContractTests(unittest.TestCase):
    def test_frontend_spec_matches_the_server_hosted_api_surface(self):
        app_source = APP_JS.read_text(encoding="utf-8")
        spec = FRONTEND_SPEC.read_text(encoding="utf-8")
        used_endpoints = set(re.findall(r'fetch\("([^"?]+)', app_source))
        self.assertTrue(used_endpoints)
        for endpoint in used_endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertIn(f"`{endpoint}`", spec)
        for stale_instruction in (
            "| 部署 | 本地文件",
            "viewer/run_viewer.py",
            "读取方式**: 静态 JSON 文件",
        ):
            self.assertNotIn(stale_instruction, spec)
        self.assertIn("不支持直接用 `file://` 打开", spec)
        self.assertIn("127.0.0.1", spec)
        self.assertIn("API Key", spec)

    @unittest.skipUnless(NODE, "Node.js is required for the frontend helper check")
    def test_api_error_message_supports_structured_and_legacy_errors(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = (
            "process.stdout.write(JSON.stringify(["
            "apiErrorMessage({error:{message:'nested'}}, 'fallback'),"
            "apiErrorMessage({error:'legacy'}, 'fallback'),"
            "apiErrorMessage({}, 'fallback')"
            "]));"
        )
        result = run_node_with_functions(
            source,
            ("apiErrorMessage",),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(["nested", "legacy", "fallback"], json.loads(result.stdout))
        self.assertNotIn("new Error(res.error ||", source)
        self.assertGreaterEqual(source.count("apiErrorMessage(res,"), 3)

    @unittest.skipUnless(NODE, "Node.js is required for the frontend selection check")
    def test_filtering_prunes_hidden_batch_selection(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = (
            "const selected = new Set(['visible', 'hidden']);\n"
            "retainVisibleSelection(selected, [{arxiv_id: 'visible'}]);\n"
            "process.stdout.write(JSON.stringify([...selected]));"
        )
        result = run_node_with_functions(
            source,
            ("retainVisibleSelection",),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(["visible"], json.loads(result.stdout))
        self.assertRegex(
            source,
            r"state\.filtered = applyFilters\(\);\s*"
            r"retainVisibleSelection\(state\.selected, state\.filtered\);",
        )

    @unittest.skipUnless(NODE, "Node.js is required for the frontend modal check")
    def test_modal_helpers_focus_inside_and_restore_trigger(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
const events = [];
const origin = {{ isConnected: true, focus() {{ events.push('origin'); }} }};
const dialog = {{ focus() {{ events.push('dialog'); }} }};
const classes = new Set();
const modal = {{
  scrollTop: 99,
  classList: {{
    add(value) {{ classes.add(value); }},
    remove(value) {{ classes.delete(value); }},
    contains(value) {{ return classes.has(value); }}
  }},
  setAttribute(name, value) {{ this[name] = value; }},
  querySelector() {{ return dialog; }}
}};
const document = {{ activeElement: origin }};
const $ = () => modal;
const modalFocusOrigins = new WeakMap();
openModal('detailModal', dialog);
closeModal('detailModal');
process.stdout.write(JSON.stringify({{
  events,
  isOpen: classes.has('show'),
  ariaHidden: modal['aria-hidden'],
  scrollTop: modal.scrollTop
}}));
"""
        result = run_node_with_functions(
            source,
            ("openModal", "closeModal"),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            {
                "events": ["dialog", "origin"],
                "isOpen": False,
                "ariaHidden": "true",
                "scrollTop": 0,
            },
            json.loads(result.stdout),
        )
        self.assertRegex(
            source,
            r'modal\.classList\.add\("show"\);\s*'
            r'modal\.setAttribute\("aria-hidden",\s*"false"\);\s*'
            r'modal\.scrollTop\s*=\s*0;\s*'
            r'\(focusTarget\s*\|\|\s*modal\.querySelector\("\.modal"\)\)\?\.focus\(\);',
            "The visible backdrop must reset scroll before focus is moved inside",
        )
        for modal_id in ("detailModal", "hermesModal", "settingsModal"):
            self.assertIn(f'openModal("{modal_id}"', source)

    @unittest.skipUnless(NODE, "Node.js is required for the frontend focus-loop check")
    def test_modal_focus_loop_wraps_tab_in_both_directions(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
const events = [];
const first = {{ focus() {{ events.push('first'); }} }};
const middle = {{ focus() {{ events.push('middle'); }} }};
const last = {{ focus() {{ events.push('last'); }} }};
const outside = {{}};
const focusable = [first, middle, last];
function run(shiftKey, activeElement) {{
  let prevented = false;
  const event = {{ key: 'Tab', shiftKey, preventDefault() {{ prevented = true; }} }};
  const trapped = cycleModalFocus(event, focusable, activeElement);
  return {{ trapped, prevented }};
}}
const forward = run(false, last);
const backward = run(true, first);
const outsideForward = run(false, outside);
const outsideBackward = run(true, outside);
const middleResult = run(false, middle);
process.stdout.write(JSON.stringify({{
  forward,
  backward,
  outsideForward,
  outsideBackward,
  middleResult,
  events
}}));
"""
        result = run_node_with_functions(
            source,
            ("cycleModalFocus",),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            {
                "forward": {"trapped": True, "prevented": True},
                "backward": {"trapped": True, "prevented": True},
                "outsideForward": {"trapped": True, "prevented": True},
                "outsideBackward": {"trapped": True, "prevented": True},
                "middleResult": {"trapped": False, "prevented": False},
                "events": ["first", "last", "first", "last"],
            },
            json.loads(result.stdout),
        )
        self.assertRegex(
            source,
            r'if \(e\.key === "Tab" && openModals\.length\) \{\s*'
            r'trapModalFocus\(e, openModals\.at\(-1\)\);\s*return;',
            "Only the topmost visible modal should receive the focus loop",
        )

    def test_zotero_unconfigured_hint_covers_source_and_desktop_paths(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("设置 → Zotero 集成", source)
        self.assertIn("python start.py --setup", source)
        self.assertIn(
            r"%LOCALAPPDATA%\\PaperCatch\\config.local.json",
            source,
        )
        self.assertIn("zotero.api_key", source)
        self.assertIn("zotero.user_id", source)

    @unittest.skipUnless(NODE, "Node.js is required for the Zotero settings check")
    def test_zotero_settings_render_without_exposing_api_key(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
const elements = {{
  zoteroCfgStatus: {{ textContent: '', className: '' }},
  zoteroUserId: {{ value: '' }},
  zoteroApiKey: {{ value: 'stale-secret' }},
  zoteroDefaultCollection: {{ value: '' }}
}};
const $ = id => elements[id];
renderZoteroSettings({{
  configured: true,
  user_id: '123456',
  api_key: 'must-never-render',
  default_collection: 'PaperCatch/Test'
}});
process.stdout.write(JSON.stringify(elements));
"""
        result = run_node_with_functions(
            source,
            ("renderZoteroSettings",),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        rendered = json.loads(result.stdout)
        self.assertEqual("123456", rendered["zoteroUserId"]["value"])
        self.assertEqual("PaperCatch/Test", rendered["zoteroDefaultCollection"]["value"])
        self.assertEqual("", rendered["zoteroApiKey"]["value"])
        self.assertNotIn("must-never-render", result.stdout)
        self.assertIn("已配置", rendered["zoteroCfgStatus"]["textContent"])

    def test_zotero_settings_use_dedicated_integration_endpoint(self):
        source = APP_JS.read_text(encoding="utf-8")
        parser = ElementAttributeParser()
        parser.feed(INDEX_HTML.read_text(encoding="utf-8"))

        self.assertIn(
            '$("zoteroCfgSaveBtn").addEventListener("click", saveZoteroSettings)',
            source,
        )
        self.assertEqual("password", parser.by_id["zoteroApiKey"][1].get("type"))
        self.assertNotIn("value", parser.by_id["zoteroApiKey"][1])
        self.assertEqual("status", parser.by_id["zoteroCfgStatus"][1].get("role"))
        self.assertRegex(
            source,
            r'fetch\("/api/integrations",\s*\{[\s\S]*?'
            r'body:\s*JSON\.stringify\(\{\s*zotero\s*\}\)',
        )
        self.assertIn('api_key: $("zoteroApiKey").value.trim()', source)
        self.assertIn('user_id: $("zoteroUserId").value.trim()', source)
        self.assertIn(
            'default_collection: $("zoteroDefaultCollection").value.trim()',
            source,
        )
        self.assertGreaterEqual(source.count("apiErrorMessage(res,"), 4)

    @unittest.skipUnless(NODE, "Node.js is required for the source settings check")
    def test_settings_sources_render_and_persist_in_config_payload(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = """
const listeners = new Map();
const DEFAULT_SOURCES = ['arxiv'];
const SOURCE_LABELS = {
  arxiv: 'arXiv',
  openalex: 'OpenAlex',
  crossref: 'Crossref',
  semantic_scholar: 'Semantic Scholar',
  europe_pmc: 'Europe PMC'
};
function classList(initial = []) {
  const values = new Set(initial);
  return {
    add(value) { values.add(value); },
    remove(value) { values.delete(value); },
    toggle(value, force) {
      if (force === undefined) {
        if (values.has(value)) values.delete(value);
        else values.add(value);
      } else if (force) values.add(value);
      else values.delete(value);
    },
    contains(value) { return values.has(value); }
  };
}
function makeChip(source, active) {
  return {
    dataset: { source, c: source },
    classList: classList(active ? ['active'] : []),
    setAttribute() {},
    addEventListener() {},
  };
}
function makeElement(id) {
  return {
    id,
    value: '',
    textContent: '',
    innerHTML: '',
    checked: false,
    classList: classList(),
    _chips: [],
    addEventListener(type, handler) {
      listeners.set(`${id}:${type}`, handler);
    },
    querySelectorAll(selector) {
      if (selector === '.chip') return this._chips;
      if (selector === '.chip.active') return this._chips.filter(el => el.classList.contains('active'));
      return [];
    }
  };
}
const elements = Object.fromEntries([
  'cfgKeywords','cfgMax','cfgDays','cfgCats','sourceChips','zoteroCfgStatus','zoteroUserId',
  'zoteroApiKey','zoteroDefaultCollection','cfgSaveBtn','zoteroCfgSaveBtn'
].map(id => [id, makeElement(id)]));
const state = { availableSources: ['arxiv', 'openalex', 'crossref'], sources: ['openalex', 'crossref'] };
elements.cfgKeywords.value = 'agent';
elements.cfgMax.value = '12';
elements.cfgDays.value = '2';
elements.zoteroUserId.reportValidity = () => true;
elements.zoteroDefaultCollection.reportValidity = () => true;
elements.cfgCats._chips = [makeChip('cs.AI', true), makeChip('cs.CL', false)];
elements.sourceChips._chips = [makeChip('arxiv', false), makeChip('openalex', true), makeChip('crossref', true)];
const $ = id => elements[id];
const document = { activeElement: elements.cfgSaveBtn };
function openModal() {}
function closeModal() {}
function toast() {}
const fetchCalls = [];
async function fetch(url, options) {
  fetchCalls.push([url, options && options.method ? options.method : 'GET', options && options.body ? JSON.parse(options.body) : null]);
  if (url === '/api/config' && options && options.method === 'POST') {
    return { ok: true, json: async () => ({ success: true, config: JSON.parse(options.body) }) };
  }
  throw new Error(`unexpected fetch ${url}`);
}
renderSourceChips(state.sources);
await saveSettings();
process.stdout.write(JSON.stringify({
  rendered: elements.sourceChips.innerHTML,
  fetchCalls
}));
"""
        result = run_node_with_functions(
            source,
            ("esc", "escA", "sourceLabel", "normalizeSourceItems", "renderSourceChips", "saveSettings"),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn('data-source="openalex"', payload["rendered"])
        self.assertIn('data-source="crossref"', payload["rendered"])
        self.assertIn('aria-pressed="true"', payload["rendered"])
        self.assertIn(["/api/config", "POST", {"categories": ["cs.AI"], "keywords": "agent", "max_per_cat": 12, "days": 2, "sources": ["openalex", "crossref"]}], payload["fetchCalls"])

    @unittest.skipUnless(NODE, "Node.js is required for the agent modal check")
    def test_agent_modal_runs_ask_and_notes_with_grounding_and_markdown(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = """
const listeners = new Map();
const SOURCE_LABELS = {
  arxiv: 'arXiv',
  openalex: 'OpenAlex',
  crossref: 'Crossref',
  semantic_scholar: 'Semantic Scholar',
  europe_pmc: 'Europe PMC'
};
function classList(initial = []) {
  const values = new Set(initial);
  return {
    add(value) { values.add(value); },
    remove(value) { values.delete(value); },
    toggle(value, force) {
      if (force === undefined) {
        if (values.has(value)) values.delete(value);
        else values.add(value);
      } else if (force) values.add(value);
      else values.delete(value);
    },
    contains(value) { return values.has(value); }
  };
}
function makeElement(id) {
  return {
    id,
    value: '',
    textContent: '',
    innerHTML: '',
    disabled: false,
    className: '',
    checked: false,
    hidden: false,
    classList: classList(),
    attrs: {},
    dataset: {},
    focusCalls: 0,
    style: {},
    addEventListener(type, handler) {
      listeners.set(`${id}:${type}`, handler);
    },
    setAttribute(name, value) { this.attrs[name] = value; },
    querySelectorAll() { return []; },
    focus() { this.focusCalls += 1; },
    scrollTop: 0
  };
}
const elements = Object.fromEntries([
  'paperAgentModal','agentModalTitle','agentPaperMeta','agentModeHint','agentStatus','agentGrounded',
  'agentAnswer','agentEvidence','agentNotesEvidence','agentMarkdown','agentQuestion','agentFocus',
  'agentAskBtn','agentNotesBtn','agentCopyMarkdownBtn','agentAskTab','agentNotesTab','agentAskPanel',
  'agentNotesPanel','agentEmpty'
].map(id => [id, makeElement(id)]));
const state = { agentPaper: null, lastAgentPaperId: '', papers: [] };
elements.agentQuestion.value = 'Explain the method';
elements.agentFocus.value = '主要发现';
const $ = id => elements[id];
const document = {
  activeElement: elements.agentQuestion,
  body: { classList: classList(), style: { setProperty() {}, removeProperty() {} } },
  addEventListener() {},
  querySelectorAll() { return []; }
};
let openCalls = [];
function openModal(id, focusTarget, returnFocus) { openCalls.push({ id, focusTarget: !!focusTarget, returnFocus: !!returnFocus }); }
function toast(msg, isErr) { toasts.push([msg, !!isErr]); }
function closeModal() {}
function debounce(fn) { return fn; }
function loadPapers() {}
function render() {}
function renderBatch() {}
function syncFilterToggle() {}
function confirm() { return true; }
const requests = [];
const toasts = [];
let clipboardWrites = [];
const navigator = { clipboard: { writeText(text) { clipboardWrites.push(text); return Promise.resolve(); } } };
async function fetch(url, options) {
  const body = options && options.body ? JSON.parse(options.body) : null;
  requests.push([url, options && options.method ? options.method : 'GET', body]);
  if (url === '/hermes/ask') {
    return { ok: true, json: async () => ({ success: true, grounded: true, answer: 'Use the retrieval stack.', evidence: [{ field: 'summary_cn', label: '中文总结', quote: 'grounded evidence' }] }) };
  }
  if (url === '/hermes/notes') {
    return { ok: true, json: async () => ({ success: true, grounded: true, evidence_fields: ['summary_cn', 'abstract_cn'], markdown: '# Notes\\n- one\\n- two' }) };
  }
  throw new Error(`unexpected fetch ${url}`);
}
const paper = { arxiv_id: 'doi:10.1000/paper-a', title: 'Agentic Retrieval', title_cn: 'Agentic Retrieval', sources: ['openalex', 'crossref'] };
openPaperAgent(paper, 'ask');
await submitPaperAgentAsk();
const askStatus = elements.agentStatus.textContent;
const askGrounded = elements.agentGrounded.textContent;
const askAnswer = elements.agentAnswer.textContent;
const askEvidence = elements.agentEvidence.innerHTML;
elements.agentMarkdown.textContent = '# Notes\\n- one\\n- two';
await submitPaperAgentNotes();
navigator.clipboard.writeText = () => Promise.reject(new Error('denied'));
copyAgentMarkdown();
await Promise.resolve();
process.stdout.write(JSON.stringify({
  requests,
  openCalls,
  askStatus,
  askGrounded,
  askAnswer,
  askEvidence,
  status: elements.agentStatus.textContent,
  grounded: elements.agentGrounded.textContent,
  notesEvidence: elements.agentNotesEvidence.innerHTML,
  markdown: elements.agentMarkdown.textContent,
  toasts,
  clipboardWrites,
  modeHint: elements.agentModeHint.textContent
}));
"""
        result = run_node_with_functions(
            source,
            (
                "sourceLabel",
                "esc",
                "currentAgentPaper",
                "renderAgentPaperMeta",
                "clearAgentOutputs",
                "setAgentMode",
                "formatAgentEvidence",
                "showAgentResult",
                "callPaperAgent",
                "openPaperAgent",
                "submitPaperAgentAsk",
                "submitPaperAgentNotes",
                "copyAgentMarkdown",
            ),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(["/hermes/ask", "POST", {"paper_id": "doi:10.1000/paper-a", "question": "Explain the method"}], payload["requests"][0])
        self.assertEqual(["/hermes/notes", "POST", {"paper_id": "doi:10.1000/paper-a", "focus": "主要发现"}], payload["requests"][1])
        self.assertIn("grounded", payload["askStatus"])
        self.assertIn("grounded", payload["askGrounded"])
        self.assertIn("Use the retrieval stack.", payload["askAnswer"])
        self.assertIn("中文总结", payload["askEvidence"])
        self.assertIn("# Notes", payload["markdown"])
        self.assertIn("summary_cn", payload["notesEvidence"])
        self.assertIn("复制 Markdown 失败", payload["toasts"][-1][0])

    def test_modals_expose_dialog_semantics(self):
        parser = ElementAttributeParser()
        parser.feed(INDEX_HTML.read_text(encoding="utf-8"))

        expected_labels = {"modalTitle", "hermesModalTitle", "settingsModalTitle", "agentModalTitle"}
        self.assertEqual(4, len(parser.dialogs))
        self.assertEqual(
            expected_labels,
            {attrs.get("aria-labelledby") for _, attrs in parser.dialogs},
        )
        for tag, attrs in parser.dialogs:
            self.assertEqual("div", tag)
            self.assertEqual("true", attrs.get("aria-modal"))
            self.assertEqual("-1", attrs.get("tabindex"))

        for modal_id in ("detailModal", "hermesModal", "settingsModal", "paperAgentModal"):
            self.assertEqual("true", parser.by_id[modal_id][1].get("aria-hidden"))
        for label_id in expected_labels:
            self.assertEqual("h2", parser.by_id[label_id][0])

    def test_settings_sources_and_agent_modal_entrypoints_exist(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('id="sourceChips"', html)
        self.assertIn("每日研究领域 / 关键词", html)
        self.assertIn('id="paperAgentModal"', html)
        self.assertIn('id="agentCopyMarkdownBtn"', html)
        self.assertIn('fetch("/api/sources"', source)
        self.assertIn('"/hermes/ask"', source)
        self.assertIn('"/hermes/notes"', source)
        self.assertIn('openPaperAgent(', source)
        self.assertIn('copyAgentMarkdown(', source)


class FrontendLayoutContractTests(unittest.TestCase):
    def test_search_input_is_not_overridden_by_generic_text_fields(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertRegex(
            source,
            r"\.search-input\s*\{[^}]*padding:\s*\.6rem\s+4\.6rem\s+\.6rem\s+2\.5rem",
        )
        self.assertIn('input[type="text"]:not(.search-input)', source)
        self.assertNotRegex(
            source,
            r'input\[type="text"\]\s*,\s*input\[type="password"\]',
            "The later generic rule must not override the header search field",
        )

    def test_date_inputs_stack_inside_the_narrow_sidebar(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertRegex(
            source,
            r"\.date-row\s*\{[^}]*grid-template-columns:\s*1fr\s*;",
            "The sidebar date inputs must stack instead of exceeding its width",
        )

    def test_single_column_layout_collapses_filters_by_default(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        toggle = source.index('id="filterToggle"')
        content = source.index('id="filterContent"')
        self.assertLess(toggle, content)
        self.assertIn('for="filterToggle"', source)
        self.assertRegex(
            source,
            r"@media\s*\(max-width:\s*1000px\)[\s\S]*?"
            r"\.filter-content\s*\{[^}]*display:\s*none\s*;[^}]*\}"
            r"[\s\S]*?\.filter-toggle:checked\s*~\s*\.filter-content\s*\{"
            r"[^}]*display:\s*block\s*;",
            "Single-column layouts must hide filters until the native toggle is checked",
        )

    @unittest.skipUnless(NODE, "Node.js is required for the filter toggle check")
    def test_filter_toggle_syncs_accessibility_state_and_label(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        source = APP_JS.read_text(encoding="utf-8")
        parser = ElementAttributeParser()
        parser.feed(html)

        self.assertEqual("false", parser.by_id["filterToggle"][1].get("aria-expanded"))
        self.assertEqual("label", parser.by_id["filterToggleLabel"][0])

        body = f"""
const values = [];
const toggle = {{
  checked: false,
  setAttribute(name, value) {{ values.push([name, value]); }}
}};
const label = {{ textContent: '' }};
syncFilterToggle(toggle, label);
const collapsed = label.textContent;
toggle.checked = true;
syncFilterToggle(toggle, label);
process.stdout.write(JSON.stringify({{ values, collapsed, expanded: label.textContent }}));
"""
        result = run_node_with_functions(
            source,
            ("syncFilterToggle",),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            [["aria-expanded", "false"], ["aria-expanded", "true"]],
            payload["values"],
        )
        self.assertIn("展开", payload["collapsed"])
        self.assertIn("收起", payload["expanded"])
        self.assertRegex(
            source,
            r'\$\("filterToggle"\)\.addEventListener\("change",\s*syncFilterToggle\);',
        )
        self.assertIn("\n  syncFilterToggle();", source)

    def test_mobile_card_badges_move_below_the_title(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertRegex(
            source,
            r"@media\s*\(max-width:\s*620px\)[\s\S]*?"
            r"\.card-top\s*\{[^}]*grid-template-columns:\s*16px\s+minmax\(0,\s*1fr\)"
            r"[\s\S]*?\.card-badges\s*\{[^}]*grid-column:\s*2\s*;[^}]*grid-row:\s*2\s*;",
            "Mobile badges must occupy a second row instead of squeezing the title",
        )

    def test_zotero_fields_expose_client_side_constraints(self):
        parser = ElementAttributeParser()
        parser.feed(INDEX_HTML.read_text(encoding="utf-8"))

        user = parser.by_id["zoteroUserId"][1]
        key = parser.by_id["zoteroApiKey"][1]
        collection = parser.by_id["zoteroDefaultCollection"][1]
        self.assertEqual("[0-9]{1,20}", user.get("pattern"))
        self.assertEqual("20", user.get("maxlength"))
        self.assertIn("required", user)
        self.assertEqual("256", key.get("maxlength"))
        self.assertEqual("500", collection.get("maxlength"))
        self.assertIn("required", collection)

    def test_mobile_toast_reserves_space_instead_of_covering_controls(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        source = APP_JS.read_text(encoding="utf-8")
        parser = ElementAttributeParser()
        parser.feed(html)

        toast = parser.by_id["toast"][1]
        self.assertEqual("status", toast.get("role"))
        self.assertEqual("polite", toast.get("aria-live"))
        self.assertEqual("true", toast.get("aria-atomic"))
        self.assertRegex(
            html,
            r"@media\s*\(max-width:\s*620px\)[\s\S]*?"
            r"body\.toast-visible\s*\{[^}]*padding-top:\s*var\(--toast-height,[^}]+\}"
            r"[\s\S]*?body\.toast-visible\s+\.modal-backdrop\.show\s*\{"
            r"[^}]*top:\s*var\(--toast-height,[^}]+\}"
            r"[\s\S]*?\.toast\s*\{[^}]*top:\s*0\s*;[^}]*bottom:\s*auto\s*;",
            "Mobile notifications must reserve their rendered height above open dialogs",
        )
        self.assertIn('document.body.classList.add("toast-visible")', source)
        self.assertIn('document.body.classList.remove("toast-visible")', source)
        self.assertIn('style.setProperty("--toast-height"', source)
        self.assertIn('isErr ? "alert" : "status"', source)


class FrontendRuntimeContractTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_load_papers_success_normalizes_records_and_calls_render(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
const state = {{ papers: [] }};
const elements = {{
  summaryText: {{ textContent: '' }},
  updateTime: {{ textContent: '' }},
  paperList: {{ innerHTML: '' }}
}};
const $ = id => elements[id];
let renderCalls = 0;
function render() {{
  renderCalls += 1;
  elements.summaryText.textContent = `rendered ${{state.papers.length}}`;
}}
async function fetch() {{
  return {{
    ok: true,
    json: async () => ({{
      updated_at: '2026-07-13T12:00:00+08:00',
      papers: [
        {{ arxiv_id: 'one', title: 'First', quality_score: '8.5' }},
        {{ arxiv_id: 'two', title: 'Second', authors: ['Ada'], categories: ['cs.AI'], tags: ['agent'], quality_score: null }}
      ]
    }})
  }};
}}
await loadPapers();
process.stdout.write(JSON.stringify({{
  renderCalls,
  summaryText: elements.summaryText.textContent,
  updateTime: elements.updateTime.textContent,
  first: state.papers[0],
  second: state.papers[1]
}}));
"""
        result = run_node_with_functions(
            source,
            ("fmtTime", "loadPapers"),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(1, payload["renderCalls"])
        self.assertEqual("rendered 2", payload["summaryText"])
        self.assertTrue(payload["updateTime"].startswith("更新于"))
        self.assertEqual("", payload["first"]["paper_id"])
        self.assertEqual([], payload["first"]["authors"])
        self.assertEqual([], payload["first"]["categories"])
        self.assertEqual([], payload["first"]["tags"])
        self.assertFalse(payload["first"]["open_access"])
        self.assertEqual("", payload["first"]["download_status"])
        self.assertEqual(8.5, payload["first"]["quality_score"])
        self.assertEqual(["Ada"], payload["second"]["authors"])
        self.assertIsNone(payload["second"]["quality_score"])

    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_load_papers_error_surfaces_failure_message(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
const state = {{ papers: [{{ arxiv_id: 'keep' }}] }};
const elements = {{
  summaryText: {{ textContent: '' }},
  updateTime: {{ textContent: '' }},
  paperList: {{ innerHTML: '' }}
}};
const $ = id => elements[id];
let renderCalls = 0;
function render() {{ renderCalls += 1; }}
async function fetch() {{
  return {{ ok: false, status: 500, json: async () => ({{}}) }};
}}
await loadPapers();
process.stdout.write(JSON.stringify({{
  renderCalls,
  summaryText: elements.summaryText.textContent,
  paperList: elements.paperList.innerHTML,
  papers: state.papers
}}));
"""
        result = run_node_with_functions(
            source,
            ("fmtTime", "esc", "loadPapers"),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(0, payload["renderCalls"])
        self.assertEqual("加载失败", payload["summaryText"])
        self.assertIn("加载失败", payload["paperList"])
        self.assertIn("HTTP 500", payload["paperList"])
        self.assertEqual([{"arxiv_id": "keep"}], payload["papers"])

    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_render_list_covers_empty_loading_and_saved_card_markup(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
const paperList = {{
  innerHTML: '',
  querySelectorAll() {{ return []; }}
}};
const state = {{ filtered: [], selected: new Set(), downloading: new Set() }};
const $ = id => paperList;
function hasCn(p) {{ return Boolean(p.title_cn && p.abstract_cn && p.summary_cn); }}
function openDetail() {{}}
function deletePapers() {{}}
function addToZotero() {{}}
function downloadPaper() {{}}
const navigator = {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }};
function requestAnimationFrame() {{}}
function toast() {{}}
renderList();
const emptyHtml = paperList.innerHTML;
const paper = {{
  arxiv_id: '2607.00001',
  title: 'Agentic Retrieval with Sparse Memory',
  title_cn: '稀疏记忆驱动的 Agent 检索',
  authors: ['Ada Lovelace', 'Alan Turing'],
  categories: ['cs.AI', 'cs.IR'],
  published: '2026-07-12',
  quality_score: 8.5,
  citations: 14,
  tags: ['RAG', 'agent'],
  abstract: 'Sparse memory retrieval for agent workflows.',
  abstract_cn: '面向智能体工作流的稀疏记忆检索。',
  summary_cn: '提出面向检索增强智能体的稀疏记忆索引与调度策略。',
  open_access: true,
  zotero_status: 'unadded',
  abs_url: 'https://example.invalid/abs/2607.00001',
  pdf_url: 'https://example.invalid/pdf/2607.00001.pdf'
}};
state.filtered = [paper];
renderList();
const normalHtml = paperList.innerHTML;
state.downloading = new Set([paperIdentity(paper)]);
renderList();
const loadingHtml = paperList.innerHTML;
state.downloading = new Set();
state.filtered = [{{...paper, download_status: 'downloaded'}}];
renderList();
const savedHtml = paperList.innerHTML;
process.stdout.write(JSON.stringify({{
  emptyHtml,
  normalHtml,
  loadingHtml,
  savedHtml
}}));
"""
        result = run_node_with_functions(
            source,
            ("paperIdentity", "hasDownloadablePdf", "isDownloadedStatus", "isDownloadingPaper", "showDownloadAction", "downloadButtonLabel", "esc", "escA", "renderList"),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("没有符合条件的论文", payload["emptyHtml"])
        self.assertIn("paper-card", payload["normalHtml"])
        self.assertIn("act-detail", payload["normalHtml"])
        self.assertIn("加入 Zotero", payload["normalHtml"])
        self.assertIn("act-download", payload["normalHtml"])
        self.assertIn("保存 PDF", payload["normalHtml"])
        self.assertIn("保存中…", payload["loadingHtml"])
        self.assertIn('disabled', payload["loadingHtml"])
        self.assertIn("PDF 已保存", payload["savedHtml"])
        self.assertIn('disabled', payload["savedHtml"])
        self.assertIn("展开摘要", payload["normalHtml"])

    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_open_detail_reflects_download_loading_and_saved_markup(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = """
function classList(initial = []) {
  const values = new Set(initial);
  return {
    add(value) { values.add(value); },
    remove(value) { values.delete(value); },
    contains(value) { return values.has(value); }
  };
}
function makeElement(id) {
  return {
    id,
    innerHTML: '',
    textContent: '',
    classList: classList(),
    setAttribute() {},
    addEventListener() {},
  };
}
const modalFocus = { focus() {} };
const detailModal = {
  classList: classList(),
  setAttribute() {},
  querySelector() { return modalFocus; }
};
const elements = {
  detailModal,
  modalTitle: makeElement('modalTitle'),
  modalBody: makeElement('modalBody'),
  modalAskAgent: makeElement('modalAskAgent'),
  modalNotesAgent: makeElement('modalNotesAgent'),
  modalDownload: makeElement('modalDownload'),
  modalZotero: makeElement('modalZotero'),
};
const state = { downloading: new Set(), detailPaperId: '', papers: [] };
const document = { activeElement: { id: 'origin' } };
const $ = id => elements[id];
function toast() {}
function openModal() {}
const paper = {
  arxiv_id: '2607.00001',
  title: 'Agentic Retrieval with Sparse Memory',
  title_cn: '稀疏记忆驱动的 Agent 检索',
  authors: ['Ada Lovelace'],
  categories: ['cs.AI'],
  published: '2026-07-12',
  abstract_full: 'Sparse memory retrieval for agent workflows.',
  abstract: 'Sparse memory retrieval for agent workflows.',
  tags: ['RAG'],
  zotero_status: 'unadded',
  open_access: true,
  pdf_url: 'https://example.invalid/pdf/2607.00001.pdf',
  abs_url: 'https://example.invalid/abs/2607.00001',
  download_status: '',
  download_reason: '',
  pdf_path: ''
};
state.downloading.add(paperIdentity(paper));
openDetail(paper);
const loadingHtml = elements.modalBody.innerHTML;
state.downloading.clear();
paper.download_status = 'downloaded';
paper.pdf_path = 'PDFs/2607.00001.pdf';
openDetail(paper);
const savedHtml = elements.modalBody.innerHTML;
process.stdout.write(JSON.stringify({
  loadingHtml,
  savedHtml,
  detailPaperId: state.detailPaperId
}));
"""
        result = run_node_with_functions(
            source,
            ("paperIdentity", "hasDownloadablePdf", "isDownloadedStatus", "isDownloadingPaper", "showDownloadAction", "downloadButtonLabel", "esc", "escA", "openDetail"),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("保存中…", payload["loadingHtml"])
        self.assertIn('disabled', payload["loadingHtml"])
        self.assertIn("PDF 已保存", payload["savedHtml"])
        self.assertIn('disabled', payload["savedHtml"])
        self.assertEqual("2607.00001", payload["detailPaperId"])

    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_download_paper_uses_stable_payload_and_updates_saved_state(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
function classList(initial = []) {{
  const values = new Set(initial);
  return {{
    add(value) {{ values.add(value); }},
    remove(value) {{ values.delete(value); }},
    contains(value) {{ return values.has(value); }}
  }};
}}
const detailModal = {{
  classList: classList(),
  setAttribute() {{}}
}};
const elements = {{ detailModal }};
const $ = id => elements[id] || {{ classList: classList(), setAttribute() {{}} }};
const state = {{
  papers: [{{
    paper_id: 'doi:10.1000/demo',
    arxiv_id: '2607.00001',
    doi: '10.1000/demo',
    open_access: true,
    pdf_url: 'https://example.invalid/demo.pdf',
    download_status: '',
    download_reason: '',
    pdf_path: ''
  }}],
  downloading: new Set(),
  detailPaperId: ''
}};
const document = {{ activeElement: {{ id: 'origin' }} }};
const toasts = [];
function toast(msg, isErr) {{ toasts.push([msg, !!isErr]); }}
let renderCalls = 0;
function render() {{ renderCalls += 1; }}
function openDetail() {{}}
const fetchCalls = [];
async function fetch(url, options) {{
  fetchCalls.push([url, options.method, JSON.parse(options.body)]);
  return {{
    ok: true,
    json: async () => ({{
      success: true,
      results: [{{
        requested_id: 'doi:10.1000/demo',
        paper_id: 'doi:10.1000/demo',
        arxiv_id: '2607.00001',
        status: 'downloaded',
        reason: 'ok',
        downloaded_at: '2026-07-14T10:00:00+08:00',
        file_path: 'PDFs/demo.pdf'
      }}]
    }})
  }};
}}
await downloadPaper(state.papers[0]);
process.stdout.write(JSON.stringify({{
  fetchCalls,
  paper: state.papers[0],
  renderCalls,
  toasts
}}));
"""
        result = run_node_with_functions(
            source,
            (
                "paperIdentity",
                "hasDownloadablePdf",
                "isDownloadedStatus",
                "buildDownloadPayload",
                "downloadFeedbackMessage",
                "updatePaperDownloadState",
                "findPaperByIdentity",
                "refreshPaperViews",
                "downloadPaper",
            ),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            [["/api/papers/download", "POST", {"paper_ids": ["doi:10.1000/demo"]}]],
            payload["fetchCalls"],
        )
        self.assertEqual("downloaded", payload["paper"]["download_status"])
        self.assertEqual("ok", payload["paper"]["download_reason"])
        self.assertEqual("PDFs/demo.pdf", payload["paper"]["pdf_path"])
        self.assertEqual("2026-07-14T10:00:00+08:00", payload["paper"]["downloaded_at"])
        self.assertGreaterEqual(payload["renderCalls"], 2)
        self.assertEqual(["开放获取 PDF 已保存", False], payload["toasts"][-1])

    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_download_paper_reports_existing_and_failure_feedback(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
function classList(initial = []) {{
  const values = new Set(initial);
  return {{
    add(value) {{ values.add(value); }},
    remove(value) {{ values.delete(value); }},
    contains(value) {{ return values.has(value); }}
  }};
}}
const detailModal = {{
  classList: classList(),
  setAttribute() {{}}
}};
const elements = {{ detailModal }};
const $ = id => elements[id] || {{ classList: classList(), setAttribute() {{}} }};
const state = {{
  papers: [{{
    paper_id: 'pmid:999',
    arxiv_id: '2607.00002',
    pmid: '999',
    open_access: true,
    pdf_url: 'https://example.invalid/existing.pdf',
    download_status: '',
    download_reason: '',
    pdf_path: ''
  }}, {{
    paper_id: 'doi:10.1000/bad',
    arxiv_id: '2607.00003',
    doi: '10.1000/bad',
    open_access: true,
    pdf_url: 'https://example.invalid/bad.pdf',
    download_status: '',
    download_reason: '',
    pdf_path: ''
  }}],
  downloading: new Set(),
  detailPaperId: ''
}};
const document = {{ activeElement: {{ id: 'origin' }} }};
const toasts = [];
function toast(msg, isErr) {{ toasts.push([msg, !!isErr]); }}
function render() {{}}
function openDetail() {{}}
let call = 0;
async function fetch() {{
  call += 1;
  if (call === 1) {{
    return {{
      ok: true,
      json: async () => ({{
        success: true,
        results: [{{
          requested_id: 'pmid:999',
          paper_id: 'pmid:999',
          arxiv_id: '2607.00002',
          status: 'already_exists',
          reason: 'existing_valid_pdf',
          downloaded_at: '2026-07-14T10:10:00+08:00',
          file_path: 'PDFs/existing.pdf'
        }}]
      }})
    }};
  }}
  return {{
    ok: true,
    json: async () => ({{
      success: true,
      results: [{{
        requested_id: 'doi:10.1000/bad',
        paper_id: 'doi:10.1000/bad',
        arxiv_id: '2607.00003',
        status: 'invalid_pdf',
        reason: 'invalid_pdf_magic',
        downloaded_at: '2026-07-14T10:20:00+08:00',
        file_path: ''
      }}]
    }})
  }};
}}
await downloadPaper(state.papers[0]);
await downloadPaper(state.papers[1]);
process.stdout.write(JSON.stringify({{
  first: state.papers[0],
  second: state.papers[1],
  toasts
}}));
"""
        result = run_node_with_functions(
            source,
            (
                "paperIdentity",
                "hasDownloadablePdf",
                "isDownloadedStatus",
                "buildDownloadPayload",
                "downloadFeedbackMessage",
                "updatePaperDownloadState",
                "findPaperByIdentity",
                "refreshPaperViews",
                "downloadPaper",
            ),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("already_exists", payload["first"]["download_status"])
        self.assertEqual("PDFs/existing.pdf", payload["first"]["pdf_path"])
        self.assertEqual("invalid_pdf", payload["second"]["download_status"])
        self.assertEqual("invalid_pdf_magic", payload["second"]["download_reason"])
        self.assertEqual(["PDF 已保存，已复用现有文件", False], payload["toasts"][0])
        self.assertEqual(["获取到的 PDF 无效，未保存", True], payload["toasts"][1])

    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_download_paper_deduplicates_pending_requests_and_recovers_after_failure(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
function classList(initial = []) {{
  const values = new Set(initial);
  return {{
    add(value) {{ values.add(value); }},
    remove(value) {{ values.delete(value); }},
    contains(value) {{ return values.has(value); }}
  }};
}}
const paperList = {{
  innerHTML: '',
  querySelectorAll() {{ return []; }}
}};
const detailModal = {{
  classList: classList(),
  setAttribute() {{}},
  querySelector() {{ return {{ focus() {{}} }}; }}
}};
const elements = {{
  detailModal,
  paperList
}};
const $ = id => elements[id] || {{ classList: classList(), setAttribute() {{}}, querySelectorAll() {{ return []; }} }};
const state = {{
  papers: [{{
    paper_id: 'doi:10.1000/demo',
    arxiv_id: '2607.00001',
    doi: '10.1000/demo',
    title: 'Agentic Retrieval Demo',
    authors: ['Ada Lovelace'],
    categories: ['cs.AI'],
    tags: ['agent'],
    published: '2026-07-14',
    open_access: true,
    pdf_url: 'https://example.invalid/demo.pdf',
    download_status: '',
    download_reason: '',
    pdf_path: ''
  }}],
  filtered: [],
  selected: new Set(),
  downloading: new Set(),
  detailPaperId: ''
}};
state.filtered = state.papers;
const document = {{ activeElement: {{ id: 'origin' }}, body: {{ classList: classList(), style: {{ setProperty() {{}}, removeProperty() {{}} }} }} }};
const toasts = [];
function toast(msg, isErr) {{ toasts.push([msg, !!isErr]); }}
const snapshots = [];
function render() {{
  renderList();
  snapshots.push(paperList.innerHTML);
}}
function hasCn() {{ return false; }}
function openDetail() {{}}
function deletePapers() {{}}
function addToZotero() {{}}
const navigator = {{ clipboard: {{ writeText() {{ return Promise.resolve(); }} }} }};
function requestAnimationFrame() {{}}
const fetchCalls = [];
async function fetch(url, options) {{
  fetchCalls.push([url, options.method, JSON.parse(options.body)]);
  return Promise.resolve().then(() => ({{
    ok: true,
    json: async () => ({{
      success: false,
      error: {{ message: 'download failed' }}
    }})
  }}));
}}
const first = downloadPaper(state.papers[0]);
const second = downloadPaper(state.papers[0]);
const loadingHtml = snapshots[0] || '';
await Promise.allSettled([first, second]);
const restoredHtml = snapshots[snapshots.length - 1] || '';
process.stdout.write(JSON.stringify({{
  fetchCalls,
  loadingHtml,
  restoredHtml,
  downloadingSize: state.downloading.size,
  toasts
}}));
"""
        result = run_node_with_functions(
            source,
            (
                "paperIdentity",
                "hasDownloadablePdf",
                "isDownloadedStatus",
                "isDownloadingPaper",
                "showDownloadAction",
                "downloadButtonLabel",
                "downloadFeedbackMessage",
                "buildDownloadPayload",
                "apiErrorMessage",
                "findPaperByIdentity",
                "updatePaperDownloadState",
                "refreshPaperViews",
                "downloadPaper",
                "esc",
                "escA",
                "renderList",
            ),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(1, len(payload["fetchCalls"]))
        self.assertIn("保存中…", payload["loadingHtml"])
        self.assertIn('disabled', payload["loadingHtml"])
        self.assertIn("保存 PDF", payload["restoredHtml"])
        self.assertNotIn("保存中…", payload["restoredHtml"])
        self.assertEqual(0, payload["downloadingSize"])
        self.assertEqual(["保存 PDF 失败：download failed", True], payload["toasts"][-1])

    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_download_paper_skips_non_open_access_requests(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
const state = {{
  papers: [{{
    paper_id: 'doi:10.1000/closed',
    arxiv_id: '2607.00004',
    open_access: false,
    pdf_url: 'https://example.invalid/closed.pdf',
    download_status: '',
    download_reason: '',
    pdf_path: ''
  }}],
  downloading: new Set(),
  detailPaperId: ''
}};
const document = {{ activeElement: {{ id: 'origin' }} }};
const toasts = [];
function toast(msg, isErr) {{ toasts.push([msg, !!isErr]); }}
function render() {{}}
function openDetail() {{}}
const $ = () => null;
let fetchCalls = 0;
async function fetch() {{
  fetchCalls += 1;
  throw new Error('should not request');
}}
await downloadPaper(state.papers[0]);
process.stdout.write(JSON.stringify({{ fetchCalls, toasts }}));
"""
        result = run_node_with_functions(
            source,
            ("paperIdentity", "hasDownloadablePdf", "isDownloadedStatus", "downloadPaper"),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(0, payload["fetchCalls"])
        self.assertEqual(["仅明确开放获取且带 PDF 链接的论文支持保存", True], payload["toasts"][0])

    def test_download_actions_bind_card_and_detail_handlers(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn('fetch("/api/papers/download"', source)
        self.assertIn('class="btn btn-sm act-download', source)
        self.assertIn('id="modalDownload"', source)
        self.assertIn('card.querySelector(".act-download")?.addEventListener("click", () => downloadPaper(p, card.querySelector(".act-download")))', source)
        self.assertIn('$("modalDownload")?.addEventListener("click", () => downloadPaper(p, $("modalDownload")))', source)

    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_bind_keeps_search_shortcuts_and_clear_reset_behavior(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
const listeners = new Map();
function classList(initial = []) {{
  const values = new Set(initial);
  return {{
    add(value) {{ values.add(value); }},
    remove(value) {{ values.delete(value); }},
    toggle(value, force) {{
      if (force === undefined) {{
        if (values.has(value)) values.delete(value);
        else values.add(value);
      }} else if (force) values.add(value);
      else values.delete(value);
    }},
    contains(value) {{ return values.has(value); }}
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: '',
    checked: false,
    textContent: '',
    dataset: {{}},
    tagName: 'DIV',
    classList: classList(),
    focusCalls: 0,
    addEventListener(type, handler) {{
      listeners.set(`${{id}}:${{type}}`, handler);
    }},
    focus() {{ this.focusCalls += 1; document.activeElement = this; }},
    setAttribute(name, value) {{ this[name] = value; }}
  }};
}}
const elements = Object.fromEntries([
  'searchInput','searchClear','refreshBtn','resetBtn','settingsBtn','hermesBtn','startDate','endDate',
  'scoreRange','sortSelect','addCatBtn','saveCatBtn','autoRefresh','selectAll','clearSelBtn','batchZoteroBtn',
  'batchDeleteBtn','hermesSendBtn','hermesInput','cfgSaveBtn','zoteroCfgSaveBtn','filterToggle',
  'filterToggleLabel','searchCount','agentAskBtn','agentNotesBtn','agentCopyMarkdownBtn',
  'agentAskTab','agentNotesTab','agentQuestion','agentFocus'
].map(id => [id, makeElement(id)]));
elements.searchInput.tagName = 'INPUT';
elements.searchInput.value = 'agent';
elements.searchClear.classList.add('show');
elements.filterToggle.checked = false;
const state = {{ filters: {{ query: 'agent', minScore: 0 }} }};
const $ = id => elements[id];
const document = {{
  activeElement: {{ tagName: 'DIV' }},
  addEventListener(type, handler) {{ listeners.set(`document:${{type}}`, handler); }},
  querySelectorAll(selector) {{
    if (selector === '.hermes-ex') return [makeElement('hermes-ex-1')];
    if (selector === '[data-close]') {{
      const close = makeElement('close-1');
      close.dataset.close = 'detailModal';
      return [close];
    }}
    if (selector === '.modal-backdrop.show') return [];
    if (selector === '.modal-backdrop') return [makeElement('modal-backdrop-1')];
    return [];
  }}
}};
function debounce(fn) {{ return fn; }}
function loadPapers() {{}}
function resetFilters() {{}}
function openSettings() {{}}
function openHermes() {{}}
function saveCategory() {{}}
function addToZotero() {{}}
function deletePapers() {{}}
function sendHermes() {{}}
function saveSettings() {{}}
function saveZoteroSettings() {{}}
function submitPaperAgentAsk() {{}}
function submitPaperAgentNotes() {{}}
function copyAgentMarkdown() {{}}
function closeModal() {{}}
function trapModalFocus() {{}}
function clearInterval() {{}}
function setInterval() {{ return 1; }}
let renderCalls = 0;
function render() {{ renderCalls += 1; }}
bind();
listeners.get('searchClear:click')();
const slashEvent = {{ key: '/', preventDefaultCalled: false, preventDefault() {{ this.preventDefaultCalled = true; }} }};
document.activeElement = {{ tagName: 'DIV' }};
listeners.get('document:keydown')(slashEvent);
elements.searchInput.value = 'temporary';
state.filters.query = 'temporary';
listeners.get('searchInput:keydown')({{ key: 'Escape' }});
process.stdout.write(JSON.stringify({{
  renderCalls,
  clearVisible: elements.searchClear.classList.contains('show'),
  searchValue: elements.searchInput.value,
  queryValue: state.filters.query,
  slashPrevented: slashEvent.preventDefaultCalled,
  searchFocusCalls: elements.searchInput.focusCalls,
  filterExpanded: elements.filterToggle['aria-expanded'],
  filterLabel: elements.filterToggleLabel.textContent
}}));
"""
        result = run_node_with_functions(
            source,
            ("syncFilterToggle", "bind"),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(2, payload["renderCalls"])
        self.assertFalse(payload["clearVisible"])
        self.assertEqual("", payload["searchValue"])
        self.assertEqual("", payload["queryValue"])
        self.assertTrue(payload["slashPrevented"])
        self.assertGreaterEqual(payload["searchFocusCalls"], 2)
        self.assertEqual("false", payload["filterExpanded"])
        self.assertIn("展开", payload["filterLabel"])

    def test_open_settings_uses_scroll_resetting_modal_helper(self):
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'openModal("settingsModal", $("cfgKeywords"), returnFocus);',
            source,
        )

    @unittest.skipUnless(NODE, "Node.js is required for the frontend runtime checks")
    def test_toast_runtime_sets_and_clears_body_offset(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = f"""
const timers = [];
function setTimeout(fn) {{
  timers.push(fn);
  return timers.length;
}}
function clearTimeout() {{}}
function classList(initial = []) {{
  const values = new Set(initial);
  return {{
    add(value) {{ values.add(value); }},
    remove(value) {{ values.delete(value); }},
    toggle(value, force) {{
      if (force === undefined) {{
        if (values.has(value)) values.delete(value);
        else values.add(value);
      }} else if (force) values.add(value);
      else values.delete(value);
    }},
    contains(value) {{ return values.has(value); }}
  }};
}}
const styleValues = new Map();
const toastElement = {{
  textContent: '',
  classList: classList(),
  attrs: {{}},
  setAttribute(name, value) {{ this.attrs[name] = value; }},
  getBoundingClientRect() {{ return {{ height: 49.6 }}; }}
}};
const document = {{
  body: {{
    classList: classList(),
    style: {{
      setProperty(name, value) {{ styleValues.set(name, value); }},
      removeProperty(name) {{ styleValues.delete(name); }}
    }}
  }}
}};
const $ = () => toastElement;
let toastTimer = null;
let toastCleanupTimer = null;
toast('saved', false);
const activeState = {{
  show: toastElement.classList.contains('show'),
  bodyVisible: document.body.classList.contains('toast-visible'),
  role: toastElement.attrs.role,
  live: toastElement.attrs['aria-live'],
  height: styleValues.get('--toast-height')
}};
timers[0]();
timers[1]();
const cleanedState = {{
  show: toastElement.classList.contains('show'),
  bodyVisible: document.body.classList.contains('toast-visible'),
  hasHeight: styleValues.has('--toast-height')
}};
process.stdout.write(JSON.stringify({{ activeState, cleanedState }}));
"""
        result = run_node_with_functions(
            source,
            ("toast",),
            body,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            {
                "show": True,
                "bodyVisible": True,
                "role": "status",
                "live": "polite",
                "height": "50px",
            },
            payload["activeState"],
        )
        self.assertEqual(
            {
                "show": False,
                "bodyVisible": False,
                "hasHeight": False,
            },
            payload["cleanedState"],
        )


if __name__ == "__main__":
    unittest.main()
