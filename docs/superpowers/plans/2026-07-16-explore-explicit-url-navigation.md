# Explore Explicit URL Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Explore mode open a user-supplied `http://` or `https://` URL before observing or planning page actions, even when another page is already open.

**Architecture:** Add explicit-URL entry handling to `ExploreAgent`, including task-level deduplication and normalized URL comparison. Invoke it in `AgentLoop` after registered-skill routing but before every Explore fallback path, so skills retain navigation ownership while Explore always honors the user's URL.

**Tech Stack:** Python 3.13, Pydantic, Playwright synchronous API, pytest, Ruff

## Global Constraints

- Explicit user URLs have the highest entry-page priority inside Explore mode.
- Registered skills retain control of their own navigation.
- Each task attempts explicit URL entry at most once.
- Equivalent current URLs are not refreshed.
- URL fragments and insignificant trailing slashes do not affect equivalence.
- Paths and query parameters remain significant.
- A failed explicit navigation must not fall back to an inferred site or search engine.

---

### Task 1: Explicit URL Entry State and Navigation

**Files:**
- Modify: `src/core/explore/agent.py`
- Create: `tests/test_explore/test_explicit_url_navigation.py`

**Interfaces:**
- Consumes: `ExploreAgent.extract_first_url(task: str) -> str | None`
- Produces: `ExploreAgent.bootstrap_explicit_entry(task: str) -> str | None`
- Produces: `ExploreAgent.entry_urls_equivalent(left: str, right: str) -> bool`

- [ ] **Step 1: Write failing unit tests for forced and deduplicated navigation**

```python
def test_explicit_url_replaces_unrelated_current_page(tmp_path):
    page = FakePage("https://example.com/current")
    agent = make_explore_agent(tmp_path, page)

    target = agent.bootstrap_explicit_entry(
        '"https://ncesnext.com/"搜索大物'
    )

    assert target == "https://ncesnext.com/"
    assert page.goto_calls == [
        ("https://ncesnext.com/", "load")
    ]


def test_explicit_url_is_only_processed_once_per_task(tmp_path):
    page = FakePage("about:blank")
    agent = make_explore_agent(tmp_path, page)
    task = '"https://ncesnext.com/"搜索大物'

    assert agent.bootstrap_explicit_entry(task) == "https://ncesnext.com/"
    assert agent.bootstrap_explicit_entry(task) is None
    assert len(page.goto_calls) == 1
```

- [ ] **Step 2: Write a failing test for equivalent current URLs**

```python
def test_equivalent_explicit_url_is_not_refreshed(tmp_path):
    page = FakePage("https://ncesnext.com/#course-list")
    agent = make_explore_agent(tmp_path, page)

    target = agent.bootstrap_explicit_entry(
        '"https://ncesnext.com/"搜索大物'
    )

    assert target == "https://ncesnext.com/"
    assert page.goto_calls == []
    assert agent.explore_mode_active is True
    assert agent.just_navigated_to_entry is True
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_explore/test_explicit_url_navigation.py -q
```

Expected: FAIL because `bootstrap_explicit_entry` and
`entry_urls_equivalent` do not exist.

- [ ] **Step 4: Implement normalized comparison and one-time explicit entry**

Add task-level state reset alongside `_entry_bootstrap_attempted`:

```python
self._explicit_entry_attempted: set[str] = set()
```

Implement:

```python
@staticmethod
def entry_urls_equivalent(left: str, right: str) -> bool:
    def key(value: str):
        parsed = urlparse(value)
        path = parsed.path.rstrip("/") or "/"
        return (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
        )

    return key(left) == key(right)


def bootstrap_explicit_entry(self, task: str) -> str | None:
    target_url = self.extract_first_url(task)
    if not target_url or task in self._explicit_entry_attempted:
        return None

    self._explicit_entry_attempted.add(task)
    self._entry_bootstrap_attempted.add(task)
    page = self._get_browser_manager().get_page()
    current_url = str(getattr(page, "url", "") or "")

    if self.entry_urls_equivalent(current_url, target_url):
        self.just_navigated_to_entry = True
        self.explore_mode_active = True
        return target_url

    return self._goto_initial_entry_url(target_url)
```

Reset `_explicit_entry_attempted` in `reset_task_state()`.

- [ ] **Step 5: Run the unit tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_explore/test_explicit_url_navigation.py -q
```

Expected: the explicit-entry unit tests pass.

---

### Task 2: AgentLoop Explore Routing Integration

**Files:**
- Modify: `src/core/agent_loop.py`
- Modify: `tests/test_explore/test_explicit_url_navigation.py`

**Interfaces:**
- Consumes: `ExploreAgent.bootstrap_explicit_entry(task: str) -> str | None`
- Produces: `_do_plan()` transition `PLAN -> OBSERVE -> EXPLORE`

- [ ] **Step 1: Write a failing integration test for `llm_explore`**

```python
def test_llm_explore_forces_explicit_url_before_snapshot(tmp_path, monkeypatch):
    page = FakePage("https://unrelated.example/")
    agent = make_agent_loop(tmp_path, page, source="llm_explore")
    step = AgentStep(
        step_number=2,
        state=AgentState.PLAN,
        task='"https://ncesnext.com/"搜索大物',
        page_summary="unrelated page",
    )

    state = agent._do_plan(step, step.task)

    assert state == AgentState.OBSERVE
    assert page.goto_calls == [
        ("https://ncesnext.com/", "load")
    ]
    assert "https://ncesnext.com/" in step.result
```

- [ ] **Step 2: Write failing routing-priority tests**

Verify that a registered skill still returns `ACT` without forced navigation,
and that a normal no-skill Explore fallback also forces the explicit URL.

- [ ] **Step 3: Run the integration tests and verify RED**

Run:

```powershell
python -m pytest tests/test_explore/test_explicit_url_navigation.py -q
```

Expected: FAIL because `_do_plan()` returns `EXPLORE` for `llm_explore`
before invoking explicit URL entry.

- [ ] **Step 4: Invoke explicit entry before Explore fallback**

In `_do_plan()`:

1. Keep registered skill execution before explicit URL handling.
2. Reject desktop-only fallback as before.
3. Call `explore_agent.bootstrap_explicit_entry(task)`.
4. When it returns a URL, populate the Explore entry event and return
   `AgentState.OBSERVE`.
5. Only then process `decision.source == "llm_explore"`.
6. Keep inferred/LLM entry bootstrap later for tasks without explicit URLs.

The emitted event uses:

```python
{
    "source": "explore_explicit_url",
    "url": explicit_url,
}
```

- [ ] **Step 5: Run focused Explore tests**

Run:

```powershell
python -m pytest tests/test_explore/test_explicit_url_navigation.py tests/test_explore/test_completion.py -q
```

Expected: all focused tests pass.

---

### Task 3: Regression and Quality Verification

**Files:**
- Verify: `src/core/agent_loop.py`
- Verify: `src/core/explore/agent.py`
- Verify: `tests/test_explore/test_explicit_url_navigation.py`

**Interfaces:**
- Consumes: completed implementation from Tasks 1 and 2
- Produces: verified Explore explicit URL behavior

- [ ] **Step 1: Run all Explore tests**

Run:

```powershell
python -m pytest tests/test_explore -q
```

Expected: new tests pass; report any unrelated existing failures separately.

- [ ] **Step 2: Run code-quality checks**

Run:

```powershell
python -m ruff check src/core/agent_loop.py src/core/explore/agent.py tests/test_explore/test_explicit_url_navigation.py
python -m compileall -q src/core/agent_loop.py src/core/explore/agent.py
git diff --check
```

Expected: all checks pass.

- [ ] **Step 3: Review the scoped diff**

Run:

```powershell
git diff -- src/core/agent_loop.py src/core/explore/agent.py tests/test_explore/test_explicit_url_navigation.py
```

Confirm the diff does not modify unrelated desktop files or registered skills.

