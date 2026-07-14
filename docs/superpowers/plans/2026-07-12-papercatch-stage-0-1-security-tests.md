# PaperCatch Stage 0+1 Security and Test Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development while executing each bugfix. Work in the current checkout, one task at a time, with review checkpoints.

**Goal:** Replace destructive and false-positive test scripts with isolated `unittest` coverage, then close the confirmed HTTP path traversal, binding, CORS, invalid JSON, and unknown API defects.

**Architecture:** Tests start the real `Handler` on an OS-assigned loopback port while redirecting all module-level data paths to a `TemporaryDirectory`. Production changes stay inside `zotero_server.py`: strict static path resolution, JSON API errors, invalid body rejection, and a loopback-only server factory.

**Tech Stack:** Python 3.11 standard library: `unittest`, `unittest.mock`, `tempfile`, `http.client`, `threading`, `http.server`, `pathlib`.

## Global Constraints

- Do not access or mutate real `papers_database.json`, `config.local.json`, Zotero, SMTP, arXiv, Hermes, or LLM services.
- Do not add third-party dependencies or change the existing JSON paper schema.
- Do not create a branch, commit, push, merge, or publish.
- Record every status change and verification result in `docs/ISSUE_FIX_LOG.md`.
- Keep runtime artifacts under temporary directories and remove them before completion.

---

### Task 1: Reusable isolated HTTP test harness

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/server_harness.py`

**Interfaces:**
- Produces: `IsolatedServerTestCase(unittest.TestCase)` with `request(method, path, body=None, headers=None)`.
- Produces fixture paths: `root`, `viewer_dir`, `db_path`, `cats_path`, `config_path`, `viewer_config_path`.
- Each test receives a real `ThreadingHTTPServer` at `127.0.0.1:<random-port>`.

- [x] **Step 1: Create the harness**

The harness must insert the repository root into `sys.path`, import `zotero_server`, create minimal `viewer/index.html`, database, categories, and both search config files, patch `VIEWER_DIR`, `DB_JSON`, `CATS_JSON`, `CONFIG_JSON`, and `CRAWLED_IDS_FILE`, then start `zotero_server.Handler` on port `0`.

`request()` must use `http.client.HTTPConnection`, serialize dict/list bodies with UTF-8 JSON, preserve raw string/bytes bodies for malformed JSON tests, return `(status, headers, raw_body)`, and close the connection in `finally`.

- [x] **Step 2: Verify the harness without touching production data**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_features -v
```

Expected at this point: import failure because `tests.test_features` has not yet been converted. Confirm no project-root runtime JSON file was created.

### Task 2: Convert false-positive and destructive scripts into isolated tests

**Files:**
- Modify: `tests/test_features.py`
- Modify: `tests/test_delete.py`
- Create: `tests/test_test_entrypoints.py`
- Test helper: `tests/server_harness.py`

**Interfaces:**
- Consumes: `IsolatedServerTestCase.request()`.
- Produces discoverable `unittest.TestCase` methods and nonzero process exit on assertion failure.

- [x] **Step 1: Rewrite feature coverage**

Create separate assertions for:

```python
def test_health(self): ...
def test_papers_api(self): ...
def test_categories_api(self): ...
def test_config_api(self): ...
def test_frontend_index(self): ...
```

Each test must assert HTTP status, content type where relevant, parsed JSON fields, and expected fixture content. Remove `requests`, console-only pass/fail printing, fixed port `8765`, and 10-second network timeouts.

- [x] **Step 2: Rewrite delete coverage**

Seed two fake papers in the temporary database. DELETE one ID, assert `200`, `success is True`, `removed == 1`, and verify the other paper remains. Add invalid/unknown ID coverage without reading the user's database.

- [x] **Step 3: Run the converted tests**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_features tests.test_delete -v
python -m unittest discover -v
```

Expected: feature/delete tests are discovered and pass against temporary data; the reported test count is greater than zero.

- [x] **Step 4: Preserve documented direct entrypoints**

Run `tests/test_features.py` and `tests/test_delete.py` as subprocesses from `tests/test_test_entrypoints.py`. Both direct commands must exit `0` on the isolated fixtures, while assertion failures still produce nonzero exits.

### Task 3: Add failing HTTP security regression tests

**Files:**
- Create: `tests/test_server_security.py`
- Test helper: `tests/server_harness.py`

**Interfaces:**
- Consumes: isolated server fixture and raw HTTP request support.
- Specifies the production behavior required from `zotero_server.py`.

- [x] **Step 1: Write the RED tests**

Add these tests:

```python
def test_plain_path_traversal_cannot_read_outside_viewer(self): ...
def test_encoded_path_traversal_cannot_read_outside_viewer(self): ...
def test_unknown_api_returns_json_404(self): ...
def test_invalid_config_json_returns_400_without_overwrite(self): ...
def test_json_response_has_no_wildcard_cors(self): ...
def test_options_has_no_wildcard_cors(self): ...
def test_default_server_factory_binds_loopback(self): ...
```

For traversal, write `config.local.json` beside the temporary `viewer/` with a marker string and request both `/../config.local.json` and `/%2e%2e/config.local.json`. Require `404` and require the marker to be absent.

For invalid JSON, preserve known contents in `config_path` and `viewer_config_path`, POST raw `{"days":` to `/api/config`, require structured JSON `400`, and assert both files are byte-for-byte unchanged.

For unknown API, request `/api/config/status`, require `404`, `Content-Type: application/json`, and payload `{"success": false, "error": {"code": "not_found", ...}}`.

- [x] **Step 2: Run and verify RED**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_server_security -v
```

Expected baseline failures:

- raw traversal returns `200` and exposes the marker;
- encoded traversal and unknown API return `200` frontend HTML;
- malformed config JSON returns `200` and overwrites both files with `{}`;
- JSON/OPTIONS responses include `Access-Control-Allow-Origin: *`;
- `zotero_server.create_server` does not exist.

The RED set also covers malformed UTF-8, invalid `Content-Length`, null-byte paths, nested payload types, and mutation requests from non-local Host/Origin values.

Do not modify production code until these failures are observed.

### Task 4: Implement strict HTTP and static-file boundaries

**Files:**
- Modify: `zotero_server.py`
- Test: `tests/test_server_security.py`

**Interfaces:**
- Produces: `create_server(port: int) -> ThreadingHTTPServer`, always bound to `127.0.0.1`.
- Produces: `Handler.json_error(code: str, message: str, status: int)`.
- `Handler.read_body()` raises a request-body validation exception for malformed UTF-8/JSON instead of returning `{}`.

- [x] **Step 1: Fix static resolution and API fallback**

Decode the URL path with `urllib.parse.unquote`. Resolve both `VIEWER_DIR` and the candidate path, reject any candidate that cannot be made relative to the viewer root, and return static `404` for missing files. Only `/` maps to `viewer/index.html`; unknown `/api/`, `/zotero/`, and `/hermes/` routes use structured JSON `404`.

- [x] **Step 2: Reject malformed request bodies**

Route unknown POST/DELETE paths before parsing the body. For known routes, catch malformed UTF-8, invalid `Content-Length`, and `json.JSONDecodeError`; return `invalid_json` with HTTP `400` and do not call a handler or write a file.

- [x] **Step 3: Remove permissive CORS and bind loopback**

Remove `Access-Control-Allow-Origin` from JSON and OPTIONS responses. Add `create_server(port)` using `ThreadingHTTPServer(("127.0.0.1", port), Handler)` and call it from `main()`.

- [x] **Step 4: Run GREEN tests**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_server_security -v
python -m unittest tests.test_features tests.test_delete -v
```

Expected: all security, feature, and delete tests pass with no real service or external integration.

- [x] **Step 5: Enforce mutation origin and payload contracts**

Require `Content-Type: application/json` for POST/DELETE routes, reject non-loopback `Host` and `Origin`, and validate route-specific shapes before calling handlers: search `message` is a string, enrich `items` is a non-empty array of objects with string `arxiv_id`, and delete/Zotero IDs are arrays of non-empty strings. Invalid requests return structured `400/403/415` without a write or external call.

### Task 5: Full stage regression and documentation

**Files:**
- Modify: `docs/ISSUE_FIX_LOG.md`
- Modify: `CODEX_PROJECT_MEMORY.md`

- [x] **Step 1: Run complete verification**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -v
python -c "import ast, pathlib; files=list(pathlib.Path('.').glob('*.py'))+list(pathlib.Path('tests').glob('*.py')); [compile(ast.parse(p.read_text(encoding='utf-8'), filename=str(p)), str(p), 'exec') for p in files]; print(f'compiled {len(files)} Python files')"
git diff --check
git status --short
```

Expected: nonzero discovered test count, zero failures/errors, all Python files compile, and no whitespace errors.

- [x] **Step 2: Verify isolation and cleanup**

Confirm no server process or listening test port remains, no `codex-work/`, `__pycache__`, test database, temporary config, screenshot, log, or backup remains in the repository.

- [x] **Step 3: Update durable records**

Mark PC-001, PC-002, PC-010, PC-011, PC-016, and PC-017 `已验证` only if their regression tests pass. Record exact commands, counts, remaining limitations, and that no external services or real data were used. Update `CODEX_PROJECT_MEMORY.md` with the new test command and HTTP security behavior.

The API error-contract migration is covered for the current HTTP routes; integration behavior that still needs external adapters remains in the later integrations phase.
