"""Explore task completion signaling tests."""

from types import SimpleNamespace

from src.core.agent_loop import AgentLoop, AgentState, AgentStep
from src.core.explore.agent import ExploreAgent
from src.core.explore.experience import ExperienceManager
from src.core.explore.models import (
    Action,
    ActionBatch,
    ActionResult,
    ExecutionResult,
    SnapshotMode,
    SnapshotResponse,
)


def test_completion_shape_drift_is_normalized():
    normalized = ExploreAgent.normalize_action_batch_data(
        {
            "actions": [],
            "completed": True,
            "summary": "Search results are visible",
        }
    )

    assert normalized["task_complete"] is True
    assert normalized["completion_summary"] == "Search results are visible"


def test_plan_finishes_when_explore_marks_current_page_complete():
    batch = ActionBatch(
        actions=[],
        task_complete=True,
        completion_summary="目标内容已经显示",
    )
    explore_agent = SimpleNamespace(
        just_navigated_to_entry=False,
        has_pending_snapshot=True,
        explore_mode_active=True,
        plan_actions=lambda _task: batch,
        update_llm_parser=lambda _parser: None,
    )
    agent = AgentLoop(max_steps=3)
    agent._explore_agent = explore_agent
    step = AgentStep(step_number=2, state=AgentState.PLAN, task="搜索目标内容")

    state = agent._do_plan(step, step.task)

    assert state == AgentState.DONE
    assert step.success is True
    assert step.action == "完成 Explore 任务"
    assert step.result == "Explore 任务已完成: 目标内容已经显示"


def test_plan_does_not_skip_actions_when_completion_marker_is_contradictory():
    batch = ActionBatch(
        actions=[Action(action="click", ref="submit")],
        task_complete=True,
        completion_summary="尚未执行提交",
    )
    explore_agent = SimpleNamespace(
        just_navigated_to_entry=False,
        has_pending_snapshot=True,
        explore_mode_active=True,
        plan_actions=lambda _task: batch,
        update_llm_parser=lambda _parser: None,
    )
    agent = AgentLoop(max_steps=3)
    agent._explore_agent = explore_agent
    step = AgentStep(step_number=2, state=AgentState.PLAN, task="提交表单")

    state = agent._do_plan(step, step.task)

    assert state == AgentState.ACT
    assert step.actions == batch.actions


def test_planner_schema_requires_explicit_completion_marker(tmp_path, monkeypatch):
    captured = {}

    def fake_chat_json(_client, _prompt, **kwargs):
        captured["schema"] = kwargs["schema"]
        return {
            "task_complete": True,
            "completion_summary": "问题答案已经显示",
            "actions": [],
        }

    monkeypatch.setattr(
        "src.core.explore.agent.chat_json_with_retry",
        fake_chat_json,
    )
    parser = SimpleNamespace(available=True, _client=object())
    agent = ExploreAgent(
        parser,
        experience_manager=ExperienceManager(tmp_path),
    )
    agent._last_snapshot = SnapshotResponse(
        version="snapshot_v1",
        mode=SnapshotMode.COMPACT,
        url="https://example.com/answer",
        title="Answer",
    )

    batch = agent.plan_actions("询问一个问题")

    assert batch is not None
    assert batch.task_complete is True
    assert batch.actions == []
    assert "task_complete" in captured["schema"]["required"]


def test_complete_action_still_finishes_explore_execution(tmp_path):
    page = SimpleNamespace(url="https://example.com/result")
    result = ExecutionResult(
        success=True,
        status="success",
        results=[
            ActionResult(
                action="complete",
                success=True,
                value="操作已经提交",
            )
        ],
    )
    executor = SimpleNamespace(execute=lambda _batch: result)
    agent = ExploreAgent(
        experience_manager=ExperienceManager(tmp_path),
        browser_manager_getter=lambda: SimpleNamespace(get_page=lambda: page),
    )
    step = AgentStep(
        step_number=3,
        state=AgentState.ACT,
        task="提交操作",
        mode="explore",
        actions=[Action(action="complete", value="操作已经提交")],
    )

    state = agent.execute(step, executor=executor)

    assert state == "done"
    assert step.result == "Explore 任务已完成: 操作已经提交"


def test_agent_loop_automatically_ends_after_completion_marker(
    tmp_path,
    monkeypatch,
):
    class FakeClient:
        def chat_json(self, _prompt, **_kwargs):
            return {
                "task_complete": True,
                "completion_summary": "页面已经显示目标答案",
                "actions": [],
            }

    page = SimpleNamespace(url="https://example.com/answer")
    browser_manager = SimpleNamespace(
        is_alive=lambda: True,
        get_page=lambda: page,
    )
    monkeypatch.setattr(
        "src.core.agent_loop.get_browser_manager",
        lambda: browser_manager,
    )

    agent = AgentLoop(max_steps=4)
    agent._llm_parser = SimpleNamespace(available=True, _client=FakeClient())
    explore_agent = agent._ensure_explore_agent()
    explore_agent.experience_manager = ExperienceManager(tmp_path)

    def observe(step):
        snapshot = SnapshotResponse(
            version="snapshot_v1",
            mode=SnapshotMode.COMPACT,
            url=page.url,
            title="Answer",
        )
        explore_agent._last_snapshot = snapshot
        explore_agent._current_snapshot = snapshot
        step.result = "测试快照"
        return AgentState.PLAN

    agent._do_observe = observe

    result = agent._run_single("询问目标答案")

    assert result.success is True
    assert result.error == ""
    assert len(result.steps) == 2
    assert result.steps[-1].result == "Explore 任务已完成: 页面已经显示目标答案"
