"""AgentLoop integration coverage for Explore experience handling."""

from types import SimpleNamespace

from src.core.agent_loop import AgentLoop, AgentState, AgentStep
from src.core.explore.experience import ExperienceManager
from src.core.explore.models import (
    Action,
    ActionResult,
    AriaNode,
    ElementInfo,
    ExecutionResult,
    ExploreConfig,
    ExploreExperience,
    SnapshotMode,
    SnapshotResponse,
)


class FakeBrowserManager:
    def __init__(self, page):
        self._page = page

    def get_page(self):
        return self._page


class FakeExecutor:
    def __init__(self, result=None, mapping=None):
        self.result = result or ExecutionResult(success=True, status="success")
        self.mapping = mapping or {}
        self.snapshots = []

    def execute(self, _batch):
        return self.result

    def update_snapshot(self, snapshot):
        self.snapshots.append(snapshot)

    def get_ref_locator_mapping(self):
        return self.mapping


class FakeSnapshotGenerator:
    def __init__(self, snapshot):
        self.snapshot_result = snapshot

    def snapshot(self, *_args, **_kwargs):
        return self.snapshot_result


def _snapshot(version="snapshot_v1"):
    return SnapshotResponse(
        version=version,
        mode=SnapshotMode.COMPACT,
        url="https://example.com/search",
        nodes=[
            AriaNode(role="textbox", name="Keyword", ref="e1", selector="#kw"),
            AriaNode(role="button", name="Search", ref="e2", selector="#go"),
        ],
        interactive_count=2,
    )


def test_explore_success_saves_experience(tmp_path, monkeypatch):
    page = SimpleNamespace(url="https://example.com/search")
    monkeypatch.setattr(
        "src.core.agent_loop.get_browser_manager",
        lambda: FakeBrowserManager(page),
    )

    agent = AgentLoop(max_steps=3)
    agent._explore_config = ExploreConfig(experience_save_threshold=1)
    agent._explore_experience_mgr = ExperienceManager(tmp_path)
    agent._current_explore_snapshot = _snapshot()
    agent._ensure_explore_executor = lambda: FakeExecutor(
        mapping={"e1": "#kw", "e2": "#go"}
    )

    step = AgentStep(
        step_number=1,
        state=AgentState.ACT,
        task="search phone on example",
        mode="explore",
        actions=[
            Action(action="fill", ref="e1", value="phone", snapshot_v="snapshot_v1"),
            Action(action="click", ref="e2", snapshot_v="snapshot_v1"),
        ],
    )

    state = agent._do_explore_act(step)

    assert state == AgentState.DONE
    saved = agent._explore_experience_mgr.list_all()
    assert len(saved) == 1
    assert saved[0].task == "search phone on example"
    assert saved[0].element_map["e1"].selector == "#kw"
    assert saved[0].actions[0].snapshot_v is None


def test_prepare_explore_experience_actions_remaps_refs(monkeypatch):
    snapshot = _snapshot("snapshot_v7")
    page = SimpleNamespace(url="https://example.com/search")
    executor = FakeExecutor()
    monkeypatch.setattr(
        "src.core.agent_loop.get_browser_manager",
        lambda: FakeBrowserManager(page),
    )

    agent = AgentLoop(max_steps=3)
    agent._explore_config = ExploreConfig()
    agent._snapshot_gen = FakeSnapshotGenerator(snapshot)
    agent._ensure_explore_executor = lambda: executor
    experience = ExploreExperience(
        id="exp1",
        task="search phone on example",
        site="example",
        actions=[Action(action="fill", ref="old_kw", value="phone")],
        element_map={
            "old_kw": ElementInfo(selector="#kw", role="textbox", name="Keyword")
        },
    )

    actions = agent._prepare_explore_experience_actions(experience)

    assert actions is not None
    assert actions[0].ref == "e1"
    assert actions[0].snapshot_v == "snapshot_v7"
    assert executor.snapshots == [snapshot]


def test_explore_panel_prompt_answer_is_saved_for_next_plan(monkeypatch):
    page = SimpleNamespace(url="https://example.com/search")
    monkeypatch.setattr(
        "src.core.agent_loop.get_browser_manager",
        lambda: FakeBrowserManager(page),
    )
    executor = FakeExecutor(
        result=ExecutionResult(
            success=True,
            status="user_input_received",
            need_snapshot=True,
            results=[
                ActionResult(
                    action="panel_prompt",
                    success=True,
                    value="use SMS login",
                )
            ],
        )
    )

    agent = AgentLoop(max_steps=3)
    agent._ensure_explore_executor = lambda: executor
    step = AgentStep(
        step_number=1,
        state=AgentState.ACT,
        task="login",
        mode="explore",
        actions=[Action(action="panel_prompt", value="How continue?")],
    )

    state = agent._do_explore_act(step)

    assert state == AgentState.EXPLORE
    assert agent._last_panel_answer == "use SMS login"
