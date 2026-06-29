"""Tests for core.agent_loop — autonomous browser operation loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.agent_loop import (
    AgentLoop,
    AgentState,
    AgentStep,
    AgentTaskResult,
    run_task,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_browser():
    """Mock the entire browser + module stack."""
    with patch("src.core.agent_loop.get_browser_manager") as mock_get_bm:
        bm = MagicMock()
        page = MagicMock()
        page.url = "https://example.com"
        page.title.return_value = "Example"
        bm.is_alive.return_value = True
        bm.get_page.return_value = page
        mock_get_bm.return_value = bm
        yield bm, page


@pytest.fixture
def mock_vision():
    """Mock VisionModule."""
    with patch("src.core.agent_loop.get_vision_module") as mock_get:
        from src.core.vision import ElementInfo, PageAnalysis

        vision = MagicMock()
        vision.analyze_page.return_value = PageAnalysis(
            summary="测试页面",
            elements=[
                ElementInfo(
                    description="搜索按钮",
                    x=100,
                    y=200,
                    suggested_selector="#btn",
                    confidence=0.9,
                ),
            ],
            suggested_actions=["点击搜索"],
        )
        mock_get.return_value = vision
        yield vision


@pytest.fixture
def mock_script_engine():
    """Mock ScriptEngine."""
    with patch("src.core.agent_loop.get_script_engine") as mock_get:
        from src.core.script_engine import ScriptResult

        engine = MagicMock()
        engine.execute.return_value = ScriptResult(success=True, output="done\n")
        mock_get.return_value = engine
        yield engine


@pytest.fixture
def mock_registry():
    """Mock SkillRegistry."""
    with patch("src.core.agent_loop.get_skill_registry") as mock_get:
        from src.skill_library.registry import SkillDetail, SkillEntry

        reg = MagicMock()
        reg.search.return_value = [
            SkillEntry(
                id="baidu_search",
                name="百度搜索",
                type="domain",
                triggers=["百度", "搜索"],
            ),
        ]
        from src.skill_library.skill_base import SkillMeta

        reg.get_detail.return_value = SkillDetail(
            meta=SkillMeta(
                id="baidu_search", name="百度搜索", type="domain", triggers=[]
            ),
            source_code='goto("https://baidu.com")\nfill("#kw", "test")\nclick("#su")',
        )
        mock_get.return_value = reg
        yield reg


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_agent_state_values(self):
        assert AgentState.OBSERVE == "observe"
        assert AgentState.PLAN == "plan"
        assert AgentState.ACT == "act"
        assert AgentState.DONE == "done"
        assert AgentState.FAILED == "failed"

    def test_agent_step_defaults(self):
        step = AgentStep(step_number=1, state=AgentState.OBSERVE)
        assert step.step_number == 1
        assert step.success is True
        assert step.script == ""

    def test_agent_task_result_defaults(self):
        result = AgentTaskResult(success=True, task="test")
        assert result.steps == []
        assert result.error == ""


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------


class TestKeywordExtraction:
    def test_extract_chinese_keyword(self):
        from src.core.script_generator import ScriptGenerator

        gen = ScriptGenerator()
        assert gen._extract_keyword("帮我在百度搜索 Python 教程") == "Python 教程"
        assert gen._extract_keyword("搜索人工智能") == "人工智能"
        assert gen._extract_keyword("百度搜索机器学习") == "机器学习"

    def test_extract_english_keyword(self):
        from src.core.script_generator import ScriptGenerator

        gen = ScriptGenerator()
        assert gen._extract_keyword("search for Python tutorial") is not None

    def test_extract_no_keyword(self):
        from src.core.script_generator import ScriptGenerator

        gen = ScriptGenerator()
        # 纯动词没有关键词
        result = gen._extract_keyword("搜索")
        assert result is None or len(result) <= 1


class TestUrlExtraction:
    def test_extract_full_url(self):
        from src.core.script_generator import ScriptGenerator

        gen = ScriptGenerator()
        assert gen._extract_url("打开 https://example.com") == "https://example.com"

    def test_extract_domain(self):
        from src.core.script_generator import ScriptGenerator

        gen = ScriptGenerator()
        url = gen._extract_url("打开 example.com")
        assert url == "https://example.com"

    def test_no_url(self):
        from src.core.script_generator import ScriptGenerator

        gen = ScriptGenerator()
        assert gen._extract_url("帮我搜索东西") is None


class TestGitHubLoginScript:
    def test_extract_login_credentials_english(self):
        credentials = AgentLoop._extract_login_credentials(
            "login GitHub username alice password s3cr3t"
        )

        assert credentials == ("alice", "s3cr3t")

    def test_extract_login_credentials_chinese(self):
        credentials = AgentLoop._extract_login_credentials(
            "使用用户名alice 和密码s3cr3t 登录 GitHub"
        )

        assert credentials == ("alice", "s3cr3t")

    def test_build_github_login_script_passes_two_arguments(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(username, password):\n    log(username)"

        script = agent._build_skill_script(
            source,
            "login GitHub username alice password s3cr3t",
            "domain/github_login",
        )

        assert 'run("alice", "s3cr3t")' in script

    def test_extract_phone_number_chinese(self):
        phone_number = AgentLoop._extract_phone_number(
            "登录小红书，手机号 13800138000"
        )

        assert phone_number == "13800138000"

    def test_extract_phone_number_with_country_code(self):
        phone_number = AgentLoop._extract_phone_number(
            "login xhs phone +86 138-0013-8000"
        )

        assert phone_number == "13800138000"

    def test_build_xiaohongshu_login_script_passes_phone_number(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(phone_number):\n    log(phone_number)"

        script = agent._build_skill_script(
            source,
            "登录小红书，手机号 13800138000",
            "domain/xiaohongshu_login",
        )

        assert 'run("13800138000")' in script

    def test_build_douyin_login_script_passes_phone_number(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(phone_number):\n    log(phone_number)"

        script = agent._build_skill_script(
            source,
            "抖音登录，电话号码是13574133406",
            "domain/douyin_login",
        )

        assert 'run("13574133406")' in script

    def test_build_bilibili_login_script_passes_phone_number(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(phone_number):\n    log(phone_number)"

        script = agent._build_skill_script(
            source,
            "B站登录，电话号码是13574133406",
            "domain/bilibili_login",
        )

        assert 'run("13574133406")' in script

    def test_select_bilibili_login_beats_bilibili_search_and_generic_login(self):
        from src.skill_library.skill_base import SkillMeta

        agent = AgentLoop(max_steps=3)
        skills = [
            SkillMeta(
                id="domain/bilibili_search",
                name="Bilibili 搜索",
                type="domain",
                triggers=["bilibili", "B站", "搜索"],
                url_patterns=["bilibili.com", "search.bilibili.com"],
            ),
            SkillMeta(
                id="domain/bilibili_login",
                name="Bilibili 短信登录",
                type="domain",
                triggers=["bilibili", "B站", "登录", "验证码"],
                url_patterns=["bilibili.com", "*.bilibili.com"],
            ),
            SkillMeta(
                id="interaction/login_flow",
                name="通用登录",
                type="interaction",
                triggers=["登录", "login"],
                url_patterns=[],
            ),
        ]

        selected = agent._select_best_skill(
            skills,
            "B站登录，电话号码是13574133406",
        )

        assert selected.id == "domain/bilibili_login"

# ---------------------------------------------------------------------------
# Full loop
# ---------------------------------------------------------------------------


class TestAgentLoop:
    def test_browser_not_running(self, mock_browser):
        """Should fail gracefully when browser not running."""
        bm, page = mock_browser
        bm.is_alive.return_value = False

        agent = AgentLoop(max_steps=3)
        result = agent.run("测试任务")

        assert result.success is False
        assert "未启动" in result.error

    def test_skill_hit_flow(
        self, mock_browser, mock_vision, mock_script_engine, mock_registry
    ):
        """Should hit skill library and execute."""
        agent = AgentLoop(max_steps=3)
        result = agent.run("在百度搜索 Python")

        assert result.success is True
        assert len(result.steps) >= 2  # OBSERVE + PLAN + ACT
        assert any("百度" in s.action or "技能" in s.result for s in result.steps)

    def test_max_steps_exceeded(self, mock_browser, mock_vision, mock_registry):
        """Should stop at max steps."""
        from src.core.script_engine import ScriptResult

        # Make script engine always fail to force looping
        with patch("src.core.agent_loop.get_script_engine") as mock_get:
            engine = MagicMock()
            engine.execute.return_value = ScriptResult(
                success=False, error="always fail"
            )
            mock_get.return_value = engine

            agent = AgentLoop(max_steps=2)
            result = agent.run("测试任务")

        assert result.success is False

    def test_on_step_callback(
        self, mock_browser, mock_vision, mock_script_engine, mock_registry
    ):
        """Should call on_step callback for each step."""
        steps_received = []

        def callback(step):
            steps_received.append(step)

        agent = AgentLoop(max_steps=3, on_step=callback)
        agent.run("在百度搜索 Python")

        assert len(steps_received) > 0

    def test_navigate_task(
        self, mock_browser, mock_vision, mock_script_engine, mock_registry
    ):
        """Should handle navigation tasks."""
        mock_registry.search.return_value = []  # No skill hit

        agent = AgentLoop(max_steps=3)
        result = agent.run("打开 https://example.com")

        assert result.success is True

    def test_screenshot_task(
        self, mock_browser, mock_vision, mock_script_engine, mock_registry
    ):
        """Should handle screenshot tasks."""
        mock_registry.search.return_value = []  # No skill hit

        agent = AgentLoop(max_steps=3)
        result = agent.run("截图")

        assert result.success is True


# ---------------------------------------------------------------------------
# Vision fallback
# ---------------------------------------------------------------------------


class TestVisionFallback:
    def test_heal_with_vision(self, mock_browser, mock_vision, mock_registry):
        """Should try vision fallback when script fails."""
        from src.core.script_engine import ScriptResult

        with patch("src.core.agent_loop.get_script_engine") as mock_get:
            engine = MagicMock()
            # First call fails, second call (vision fallback) succeeds
            engine.execute.side_effect = [
                ScriptResult(success=False, error="选择器不可用"),
                ScriptResult(success=True, output="clicked"),
            ]
            mock_get.return_value = engine

            agent = AgentLoop(max_steps=5)
            result = agent.run("点击搜索按钮")

        # Should have tried vision fallback
        assert any("视觉" in s.result for s in result.steps)

    def test_no_vision_module(self, mock_browser, mock_registry):
        """Should handle missing vision module gracefully."""
        from src.core.script_engine import ScriptResult

        with patch("src.core.agent_loop.get_vision_module") as mock_vision:
            mock_vision.side_effect = ValueError("no API key")

            with patch("src.core.agent_loop.get_script_engine") as mock_get:
                engine = MagicMock()
                engine.execute.return_value = ScriptResult(
                    success=False, error="选择器不可用"
                )
                mock_get.return_value = engine

                agent = AgentLoop(max_steps=3)
                result = agent.run("测试")

        # Should fail but not crash
        assert result.success is False


# ---------------------------------------------------------------------------
# run_task convenience function
# ---------------------------------------------------------------------------


class TestRunTask:
    @patch("src.core.agent_loop.AgentLoop")
    def test_run_task_calls_agent(self, mock_agent_cls):

        mock_agent = MagicMock()
        mock_agent.run.return_value = AgentTaskResult(success=True, task="test")
        mock_agent_cls.return_value = mock_agent

        result = run_task("test task")
        assert result.success is True
        mock_agent.run.assert_called_once_with("test task")
