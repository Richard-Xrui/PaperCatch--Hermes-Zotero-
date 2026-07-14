# PaperCatch Stage 2 Storage Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development while executing each bugfix. Work in the current checkout, one task at a time, with review checkpoints.

**Goal:** Eliminate lost updates and torn JSON writes across PaperCatch, make local enrichment idempotent, and safely restore search-triggered enrichment.

**Architecture:** A new standard-library JSON store owns strict reads, same-directory atomic replacement, and file-based cross-process locking. Business functions receive explicit paths and perform their whole read-modify-write transaction through that store; the HTTP layer calls enrichment functions directly and reports best-effort failures as structured warnings.

**Tech Stack:** Python 3.11 standard library: `json`, `tempfile`, `os.replace`, `msvcrt.locking`, `fcntl.flock`, `unittest`, `multiprocessing`, `threading`, `unittest.mock`.

## Global Constraints

- Do not access or mutate real `papers_database.json`, `config.local.json`, Zotero, SMTP, arXiv, Hermes, or LLM services.
- Keep the existing paper JSON field meanings and add no third-party dependencies.
- Missing JSON files may use the caller's default; malformed or unreadable existing JSON must raise a path-specific error and must never be overwritten with an empty default.
- Every `papers_database.json` read-modify-write transaction must hold the same cross-process lock through atomic replacement.
- Do not create a branch, commit, push, merge, or publish.
- Record RED evidence, root cause, file changes, verification commands, and cleanup in `docs/ISSUE_FIX_LOG.md`.
- Keep runtime artifacts in temporary directories and remove all task-generated scratch files before completion.

---

### Task 1: Strict atomic JSON store

**Files:**
- Create: `json_store.py`
- Create: `tests/test_json_store.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `JsonStoreError`, whose message includes the failing path.
- Produces: `read_json(path, default)`; only a missing path returns an independent copy of `default`.
- Produces: `write_json_atomic(path, data)` using a same-directory temporary file, UTF-8 JSON, `flush()`, `os.fsync()`, and `os.replace()`.
- Produces: `locked_update_json(path, default, updater)` using `<data-path>.lock`, `msvcrt.locking` on Windows, and `fcntl.flock` on POSIX.

- [x] **Step 1: Write RED storage tests**

Cover missing-file defaults, malformed JSON with a path-specific exception, original-byte preservation when serialization or `os.replace()` fails, temporary-file cleanup, no replacement for a no-op update, thread contention, and multiple spawned processes incrementing one temporary JSON value without lost updates.

- [x] **Step 2: Run RED**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_json_store -v
```

Expected: import failure because `json_store.py` does not exist yet.

- [x] **Step 3: Implement the minimal store**

The lock file must contain at least one byte before `msvcrt.locking(..., 1)`, all platforms must release in `finally`, updater exceptions must leave the target untouched, and lock files must remain stable rather than being unlinked after each transaction.

- [x] **Step 4: Run GREEN**

Run the Task 1 command repeatedly. Expected: all storage tests pass with no lock or temp files under the repository.

### Task 2: Idempotent and path-injectable enrichment

**Files:**
- Modify: `enrich.py`
- Create: `tests/test_enrich.py`

**Interfaces:**
- Produces: `local_enrich(force=False, db_path=DB_PATH) -> int`.
- Produces: `mark_pending(db_path=DB_PATH, pending_path=PENDING_PATH) -> int`.
- Produces: `apply_batch(batch_path, db_path=DB_PATH) -> int`.

- [x] **Step 1: Write RED enrichment tests**

Use only temporary databases. Verify a paper with no matching tag keywords and an already-correct empty `tags` list does not trigger a second write; verify score/signals are generated once; verify `apply_batch` preserves a concurrent paper; verify malformed JSON raises without changing its bytes.

- [x] **Step 2: Run RED**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_enrich -v
```

Expected: path injection is unsupported and the second local enrichment still reports an update for empty tags.

- [x] **Step 3: Move enrichment transactions onto the store**

Compute desired tags, quality score, and signals, then update only when the stored value differs. Write `pending_enrichment.json` atomically and run database batch application inside `locked_update_json`.

- [x] **Step 4: Run GREEN**

Expected: the second local enrichment returns `0`, performs no database replacement, and all malformed/concurrent cases preserve data.

### Task 3: Migrate every paper database writer

**Files:**
- Modify: `zotero_server.py`
- Modify: `merge_papers.py`
- Modify: `classify_papers.py`
- Create: `tests/test_storage_integration.py`
- Modify: existing server/delete tests as needed for stable storage errors.

**Interfaces:**
- `zotero_server.merge_into_db`, enrich save, Zotero status writeback, and delete all use `locked_update_json` rather than `DB_LOCK` plus an in-place write.
- `merge_papers.merge_papers(new_path=NEW_JSON, db_path=DB_JSON)` performs one locked merge.
- `classify_papers.classify_database(db_path=DB_PATH, categories_path=CATS_PATH)` performs one locked classification and module import has no write side effect.

- [x] **Step 1: Write a deterministic RED interleaving test**

Pause `local_enrich` after it has read paper A, concurrently merge paper B through the server writer, then resume enrichment. Require the final database to contain A and B. Against the current code, enrichment's old snapshot overwrites B.

- [x] **Step 2: Add writer-specific behavior tests**

Verify merge preserves enriched fields, classify updates temporary papers only, HTTP delete and enrich save preserve unrelated concurrent additions, and malformed database JSON returns structured HTTP `500 storage_error` without overwrite.

- [x] **Step 3: Run RED**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_storage_integration -v
```

Expected: at least the controlled interleaving loses paper B and corrupted-data handling does not satisfy the structured error contract.

- [x] **Step 4: Migrate writers and run GREEN**

Remove the process-local `DB_LOCK` as a correctness mechanism. Keep network work outside the database lock and apply only final Zotero status changes in a short locked transaction.

### Task 4: Restore search-triggered local enrichment

**Files:**
- Modify: `zotero_server.py`
- Create: `tests/test_server_enrichment.py`

**Interfaces:**
- Search calls `local_enrich(db_path=DB_JSON)` and `mark_pending(db_path=DB_JSON, pending_path=BASE_DIR / "pending_enrichment.json")` directly.
- A successful response includes `enrichment` counts.
- Best-effort failures leave merged papers intact and return `warnings: [{"code": "enrichment_failed", "message": ...}]`.

- [x] **Step 1: Write RED HTTP tests**

Patch only the external arXiv/LLM boundary and exercise the real merge and enrichment functions on the server harness's temporary paths. Require new agent/LLM papers to have tags and a quality score. Force one enrichment exception and require HTTP `200`, a persisted paper, and a structured warning.

- [x] **Step 2: Run RED**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_server_enrichment -v
```

Expected: current missing `subprocess` usage is swallowed, no local fields are generated, and no warning is returned.

- [x] **Step 3: Replace subprocess calls with direct functions**

Run local scoring and pending generation independently so one best-effort failure does not hide the other. Do not expose stack traces or invoke external integrations.

- [x] **Step 4: Run GREEN**

Expected: success and warning paths both pass; no real arXiv, LLM, Zotero, or SMTP call occurs.

### Task 5: Atomic ancillary JSON and full stage regression

**Files:**
- Modify: `config.py`
- Modify: `arxiv_daily_search.py`
- Modify: `docs/ISSUE_FIX_LOG.md`
- Modify: `CODEX_PROJECT_MEMORY.md`

- [x] **Step 1: Use atomic writes for non-database JSON touched by current flows**

Use `write_json_atomic` for local config, search output, `run_status.json`, server search/category config, and pending enrichment. Do not change stage 3's CLI precedence, failure propagation, or crawled-ID transaction semantics here.

- [x] **Step 2: Run detailed verification**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -v
python tests/test_features.py
python tests/test_delete.py
python -c "import ast, pathlib; files=list(pathlib.Path('.').glob('*.py'))+list(pathlib.Path('tests').glob('*.py')); [compile(ast.parse(p.read_text(encoding='utf-8'), filename=str(p)), str(p), 'exec') for p in files]; print(f'compiled {len(files)} Python files')"
node --check viewer/app.js
git diff --check
git status --short
```

Expected: all discovered and direct-entry tests pass, all Python files compile, JavaScript syntax is valid, and the diff has no whitespace errors.

- [x] **Step 3: Verify isolation and cleanup**

Confirm there is no repository lock/temp JSON, `__pycache__`, `codex-work/`, test database, service process, listening test port, screenshot, log, backup, or test data. Confirm no external service was called.

- [x] **Step 4: Update durable records**

Mark PC-003, PC-004, and PC-024 `已验证` only after their focused tests and full regression pass. Record exact counts and commands. Record the `classify_papers.py` half of PC-019 as fixed while leaving PC-019 open until `cron_wrapper.py` is also corrected.
