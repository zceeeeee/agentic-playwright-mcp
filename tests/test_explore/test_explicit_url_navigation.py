"""Explore explicit URL entry navigation tests."""

from types import SimpleNamespace

from src.core.agent_loop import AgentLoop, AgentState, AgentStep
from src.core.explore.agent import ExploreAgent
from src.core.explore.experience import ExperienceManager


class FakePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self.goto_calls: list[tuple[str, str | None]] = []

    def goto(self, url: str, wait_until: str | None = None):
        self.goto_calls.append((url, wait_until))
        self.url = url
        return None

    def wait_for_load_state(self, _state: str, timeout: int | None = None) -> None:
        return None

    def title(self) -> str:
        return "Test page"


class FakeBrowserManager:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    def get_page(self) -> FakePage:
        return self.page


def make_explore_agent(tmp_path, page: FakePage) -> ExploreAgent:
    browser_manager = FakeBrowserManager(page)
    return ExploreAgent(
        experience_manager=ExperienceManager(tmp_path),
        browser_manager_getter=lambda: browser_manager,
    )


def make_agent_loop(
    tmp_path,
    monkeypatch,
    page: FakePage,
    *,
    decision,
) -> AgentLoop:
    browser_manager = FakeBrowserManager(page)
    monkeypatch.setattr(
        "src.core.agent_loop.get_browser_manager",
        lambda: browser_manager,
    )
    loop = AgentLoop(max_steps=4)
    loop._explore_agent = ExploreAgent(
        experience_manager=ExperienceManager(tmp_path),
        browser_manager_getter=lambda: browser_manager,
    )
    loop._skill_router = SimpleNamespace(
        route=lambda *_args, **_kwargs: decision,
    )
    loop._generate_script = lambda _task, _summary: None
    return loop


def test_explicit_url_replaces_unrelated_current_page(tmp_path):
    page = FakePage("https://example.com/current")
    agent = make_explore_agent(tmp_path, page)

    target = agent.bootstrap_explicit_entry(
        '"https://ncesnext.com/"搜索大物'
    )

    assert target == "https://ncesnext.com/"
    assert page.goto_calls == [("https://ncesnext.com/", "load")]


def test_explicit_url_is_only_processed_once_per_task(tmp_path):
    page = FakePage("about:blank")
    agent = make_explore_agent(tmp_path, page)
    task = '"https://ncesnext.com/"搜索大物'

    assert agent.bootstrap_explicit_entry(task) == "https://ncesnext.com/"
    assert agent.bootstrap_explicit_entry(task) is None
    assert page.goto_calls == [("https://ncesnext.com/", "load")]


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


def test_llm_explore_forces_explicit_url_before_snapshot(tmp_path, monkeypatch):
    page = FakePage("https://unrelated.example/")
    decision = SimpleNamespace(
        skill=None,
        script="",
        source="llm_explore",
        confidence=0.95,
        reason="unknown site requires Explore",
    )
    loop = make_agent_loop(
        tmp_path,
        monkeypatch,
        page,
        decision=decision,
    )
    step = AgentStep(
        step_number=2,
        state=AgentState.PLAN,
        task='"https://ncesnext.com/"搜索大物',
        page_summary="unrelated page",
    )

    state = loop._do_plan(step, step.task)

    assert state == AgentState.OBSERVE
    assert page.goto_calls == [("https://ncesnext.com/", "load")]
    assert "https://ncesnext.com/" in step.result


def test_no_skill_explore_forces_explicit_url_before_experience(
    tmp_path,
    monkeypatch,
):
    page = FakePage("https://unrelated.example/")
    decision = SimpleNamespace(
        skill=None,
        script="",
        source="none",
        confidence=0,
        reason="no matching skill",
    )
    loop = make_agent_loop(
        tmp_path,
        monkeypatch,
        page,
        decision=decision,
    )
    step = AgentStep(
        step_number=2,
        state=AgentState.PLAN,
        task='"https://ncesnext.com/"搜索大物',
        page_summary="unrelated page",
    )

    state = loop._do_plan(step, step.task)

    assert state == AgentState.OBSERVE
    assert page.goto_calls == [("https://ncesnext.com/", "load")]


def test_registered_skill_keeps_navigation_control(tmp_path, monkeypatch):
    page = FakePage("https://unrelated.example/")
    decision = SimpleNamespace(
        skill=SimpleNamespace(id="example/search", name="Example search"),
        script="run_search()",
        source="keyword",
        confidence=1.0,
        reason="registered skill",
    )
    loop = make_agent_loop(
        tmp_path,
        monkeypatch,
        page,
        decision=decision,
    )
    step = AgentStep(
        step_number=2,
        state=AgentState.PLAN,
        task='"https://ncesnext.com/"搜索大物',
        page_summary="unrelated page",
    )

    state = loop._do_plan(step, step.task)

    assert state == AgentState.ACT
    assert step.script == "run_search()"
    assert page.goto_calls == []


def test_plain_open_url_uses_builtin_navigation_instead_of_explore(
    tmp_path,
    monkeypatch,
):
    page = FakePage("about:blank")
    decision = SimpleNamespace(
        skill=None,
        script="",
        source="none",
        confidence=0,
        reason="no matching skill",
    )
    loop = make_agent_loop(
        tmp_path,
        monkeypatch,
        page,
        decision=decision,
    )
    loop._generate_script = lambda _task, _summary: (
        'goto("https://example.com")\nlog("navigation complete")'
    )
    step = AgentStep(
        step_number=2,
        state=AgentState.PLAN,
        task="打开 https://example.com",
        page_summary="about:blank",
    )

    state = loop._do_plan(step, step.task)

    assert state == AgentState.ACT
    assert step.script.startswith('goto("https://example.com")')
    assert page.goto_calls == []
