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
from src.core.skill_router import SkillRouter
from src.skill_library.registry import SkillRegistry

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

    def test_extract_gmail_credentials_from_example_text(self):
        credentials = AgentLoop._extract_gmail_credentials(
            "完成登录gmail功能，账号邮箱（测试用例che53438@gmail.com），密码(测试用例8105432a)"
        )

        assert credentials == ("che53438@gmail.com", "8105432a")

    def test_build_gmail_login_script_passes_email_and_password(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(email, password):\n    log(email)"

        script = agent._build_skill_script(
            source,
            "Gmail登录，邮箱是che53438@gmail.com，密码是8105432a",
            "domain/gmail_login",
        )

        assert 'run("che53438@gmail.com", "8105432a")' in script

    def test_extract_gmail_send_fields_from_example_text(self):
        fields = AgentLoop._extract_gmail_send_fields(
            "Gmail发送邮件，收件人是alice@example.com，标题是“测试标题”，正文是“测试正文”。"
        )

        assert fields == ("alice@example.com", "测试标题", "测试正文")

    def test_extract_gmail_send_fields_from_user_text(self):
        fields = AgentLoop._extract_gmail_send_fields(
            "gmail发送邮件，收件邮箱是12412639@mail.sustech.edu.cn，标题是“测试邮件”，内容是“测试邮件内容”"
        )

        assert fields == ("12412639@mail.sustech.edu.cn", "测试邮件", "测试邮件内容")

    def test_extract_gmail_send_account_from_user_text(self):
        account = AgentLoop._extract_gmail_send_account(
            "gmail发送邮件，发件邮箱是12412639@mail.sustech.edu.cn，密码是8105432a，收件邮箱是alice@example.com，标题是“测试邮件”，内容是“测试邮件内容”"
        )

        assert account == ("12412639@mail.sustech.edu.cn", "8105432a")

    def test_build_gmail_send_script_passes_recipient_subject_and_body(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(recipient, subject, body):\n    log(subject)"

        script = agent._build_skill_script(
            source,
            "Gmail发送邮件，收件人是alice@example.com，标题是“测试标题”，正文是“测试正文”。",
            "domain/gmail_send",
        )

        assert 'run("alice@example.com", "测试标题", "测试正文")' in script

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

    def test_extract_xiaohongshu_publish_content(self):
        content = AgentLoop._extract_xiaohongshu_publish_content(
            "小红书发布图文，电话号码是13574133406，内容是“今天的穿搭灵感”"
        )

        assert content == "今天的穿搭灵感"

    def test_build_xiaohongshu_publish_script_passes_content_and_optional_phone(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(content, phone_number=None):\n    log(content)"

        script = agent._build_skill_script(
            source,
            "小红书发布图文，电话号码是13574133406，内容是“今天的穿搭灵感”",
            "domain/xiaohongshu_publish",
        )

        assert 'mode="text_to_image"' in script
        assert 'phone_number="13574133406"' in script

    def test_build_xiaohongshu_publish_script_allows_missing_phone(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(content, phone_number=None):\n    log(content)"

        script = agent._build_skill_script(
            source,
            "小红书发布图文，内容是“今天的穿搭灵感”",
            "domain/xiaohongshu_publish",
        )

        assert 'mode="text_to_image"' in script
        assert "phone_number=" not in script.split("# 自动调用", 1)[-1]

    def test_build_xiaohongshu_publish_script_uploads_image_path(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(content=None, **kwargs):\n    log(content)"

        script = agent._build_skill_script(
            source,
            r'小红书发布内容 "wecqc", 图片地址是 "D:\xxx\cover.jpg"',
            "domain/xiaohongshu_publish",
        )

        assert 'run("wecqc", mode="image_upload", image_path="D:\\\\xxx\\\\cover.jpg")' in script

    def test_build_xiaohongshu_publish_script_uploads_video_path(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(content=None, **kwargs):\n    log(content)"

        script = agent._build_skill_script(
            source,
            r'小红书上传视频，视频地址是 "D:\xxx\clip.mp4"，标题是“视频标题”，正文是“视频正文”',
            "domain/xiaohongshu_publish",
        )

        assert 'mode="video"' in script
        assert 'video_path="D:\\\\xxx\\\\clip.mp4"' in script
        assert 'title="视频标题"' in script
        assert 'run("视频正文"' in script

    def test_build_xiaohongshu_publish_script_writes_article(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(content=None, **kwargs):\n    log(content)"

        script = agent._build_skill_script(
            source,
            "小红书写长文，标题是“长文标题”，正文是“第一段内容”",
            "domain/xiaohongshu_publish",
        )

        assert 'mode="article"' in script
        assert 'title="长文标题"' in script
        assert 'run("第一段内容"' in script

    def test_build_xiaohongshu_publish_script_writes_article_from_publish_keyword(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(content=None, **kwargs):\n    log(content)"

        script = agent._build_skill_script(
            source,
            "小红书发布文章，标题是“测试发布功能”，内容“测试发布功能”。",
            "domain/xiaohongshu_publish",
        )

        assert 'mode="article"' in script
        assert 'title="测试发布功能"' in script
        assert 'run("测试发布功能"' in script

    def test_router_routes_xiaohongshu_article_to_publish_script(self):
        router = SkillRouter(library_dir="src/skill_library")

        decision = router.route(
            "小红书发布文章，标题是“测试发布功能”，内容“测试发布功能”。"
        )

        assert decision.skill is not None
        assert decision.skill.id == "domain/xiaohongshu_publish"
        assert 'keyword="测试发布功能"' in decision.script
        assert 'title="测试发布功能"' in decision.script
        assert 'mode="article"' in decision.script

    def test_router_routes_xiaohongshu_video_upload_to_publish_script(self):
        router = SkillRouter(library_dir="src/skill_library")

        decision = router.route(
            r'小红书上传视频，视频地址是 "D:\xxx\clip.mp4"，标题是“视频标题”，正文是“视频正文”'
        )

        assert decision.skill is not None
        assert decision.skill.id == "domain/xiaohongshu_publish"
        assert 'mode="video"' in decision.script
        assert 'video_path="D:\\\\xxx\\\\clip.mp4"' in decision.script
        assert 'title="视频标题"' in decision.script
        assert 'body="视频正文"' in decision.script

    def test_router_keeps_xiaohongshu_search_on_search_intent(self):
        router = SkillRouter(library_dir="src/skill_library")

        decision = router.route("小红书搜索旅游攻略")

        assert decision.skill is not None
        assert decision.skill.id == "domain/xiaohongshu_search"

    def test_router_defaults_generic_publish_content_to_xiaohongshu_publish_script(self):
        router = SkillRouter(library_dir="src/skill_library")

        decision = router.route("发布内容“测试内容”")

        assert decision.skill is not None
        assert decision.skill.id == "domain/xiaohongshu_publish"
        assert 'keyword="测试内容"' in decision.script
        assert 'mode="text_to_image"' in decision.script

    def test_registry_fallback_builds_xiaohongshu_article_publish_script(self):
        task = "小红书发布文章，标题是“测试发布功能”，内容“测试发布功能”。"
        registry = SkillRegistry(library_dir="src/skill_library")
        registry.load_from_yaml()
        agent = AgentLoop(max_steps=3)

        skills = registry.search(query=task)
        selected = agent._select_best_skill(skills, task)
        detail = registry.get_detail(selected.id)
        assert detail is not None

        script = agent._build_skill_script(detail.source_code, task, selected.id)

        assert selected.id == "domain/xiaohongshu_publish"
        assert 'mode="article"' in script
        assert 'title="测试发布功能"' in script
        assert 'run("测试发布功能"' in script

    def test_registry_fallback_builds_xiaohongshu_video_publish_script(self):
        task = r'小红书上传视频，视频地址是 "D:\xxx\clip.mp4"，标题是“视频标题”，正文是“视频正文”'
        registry = SkillRegistry(library_dir="src/skill_library")
        registry.load_from_yaml()
        agent = AgentLoop(max_steps=3)

        skills = registry.search(query=task)
        selected = agent._select_best_skill(skills, task)
        detail = registry.get_detail(selected.id)
        assert detail is not None

        script = agent._build_skill_script(detail.source_code, task, selected.id)

        assert selected.id == "domain/xiaohongshu_publish"
        assert 'mode="video"' in script
        assert 'video_path="D:\\\\xxx\\\\clip.mp4"' in script
        assert 'title="视频标题"' in script
        assert 'run("视频正文"' in script

    def test_router_routes_gmail_send_to_send_script(self):
        router = SkillRouter(library_dir="src/skill_library")

        decision = router.route(
            "Gmail发送邮件，收件人是alice@example.com，标题是测试标题，正文是测试正文"
        )

        assert decision.skill is not None
        assert decision.skill.id == "domain/gmail_send"
        assert 'recipient="alice@example.com"' in decision.script
        assert 'subject="测试标题"' in decision.script
        assert 'body="测试正文"' in decision.script

    def test_router_routes_gmail_send_with_sender_login_to_send_script(self):
        router = SkillRouter(library_dir="src/skill_library")

        decision = router.route(
            "gmail发送邮件，发件邮箱是12412639@mail.sustech.edu.cn，密码是8105432a，收件邮箱是12412639@mail.sustech.edu.cn，标题是“测试邮件”，内容是“测试邮件内容”"
        )

        assert decision.skill is not None
        assert decision.skill.id == "domain/gmail_send"
        assert 'recipient="12412639@mail.sustech.edu.cn"' in decision.script
        assert 'subject="测试邮件"' in decision.script
        assert 'body="测试邮件内容"' in decision.script
        assert 'sender_email="12412639@mail.sustech.edu.cn"' in decision.script
        assert 'password="8105432a"' in decision.script

    def test_registry_fallback_builds_gmail_send_script(self):
        task = "Gmail发送邮件，收件人是alice@example.com，标题是测试标题，正文是测试正文"
        registry = SkillRegistry(library_dir="src/skill_library")
        registry.load_from_yaml()
        agent = AgentLoop(max_steps=3)

        skills = registry.search(query=task)
        selected = agent._select_best_skill(skills, task)
        detail = registry.get_detail(selected.id)
        assert detail is not None

        script = agent._build_skill_script(detail.source_code, task, selected.id)

        assert selected.id == "domain/gmail_send"
        assert 'run("alice@example.com", "测试标题", "测试正文")' in script

    def test_registry_fallback_builds_gmail_send_script_from_user_text(self):
        task = "gmail发送邮件，收件邮箱是12412639@mail.sustech.edu.cn，标题是“测试邮件”，内容是“测试邮件内容”"
        registry = SkillRegistry(library_dir="src/skill_library")
        registry.load_from_yaml()
        agent = AgentLoop(max_steps=3)

        skills = registry.search(query=task)
        selected = agent._select_best_skill(skills, task)
        detail = registry.get_detail(selected.id)
        assert detail is not None

        script = agent._build_skill_script(detail.source_code, task, selected.id)

        assert selected.id == "domain/gmail_send"
        assert 'run("12412639@mail.sustech.edu.cn", "测试邮件", "测试邮件内容")' in script

    def test_registry_fallback_builds_gmail_send_script_with_sender_login(self):
        task = "gmail发送邮件，发件邮箱是12412639@mail.sustech.edu.cn，密码是8105432a，收件邮箱是alice@example.com，标题是“测试邮件”，内容是“测试邮件内容”"
        registry = SkillRegistry(library_dir="src/skill_library")
        registry.load_from_yaml()
        agent = AgentLoop(max_steps=3)

        skills = registry.search(query=task)
        selected = agent._select_best_skill(skills, task)
        detail = registry.get_detail(selected.id)
        assert detail is not None

        script = agent._build_skill_script(detail.source_code, task, selected.id)

        assert selected.id == "domain/gmail_send"
        assert 'run("alice@example.com", "测试邮件", "测试邮件内容", sender_email="12412639@mail.sustech.edu.cn", password="8105432a")' in script

    def test_registry_fallback_builds_gmail_send_script_with_che_sender_login(self):
        task = "gmail发送邮件，发件邮箱是che53438@gmail.com，密码是8105432a，收件邮箱是12412639@mail.sustech.edu.cn，标题是“测试邮件”，内容是“测试邮件内容”"
        registry = SkillRegistry(library_dir="src/skill_library")
        registry.load_from_yaml()
        agent = AgentLoop(max_steps=3)

        skills = registry.search(query=task)
        selected = agent._select_best_skill(skills, task)
        detail = registry.get_detail(selected.id)
        assert detail is not None

        script = agent._build_skill_script(detail.source_code, task, selected.id)

        assert selected.id == "domain/gmail_send"
        assert 'run("12412639@mail.sustech.edu.cn", "测试邮件", "测试邮件内容", sender_email="che53438@gmail.com", password="8105432a")' in script

    def test_build_xiaohongshu_publish_script_passes_style_and_schedule(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(content=None, **kwargs):\n    log(content)"

        script = agent._build_skill_script(
            source,
            "小红书发布短文，内容是“测试内容”，样式是弥散，定时发布 2026-07-01 11:17",
            "domain/xiaohongshu_publish",
        )

        assert 'mode="text_to_image"' in script
        assert 'cover_style="弥散"' in script
        assert "enable_schedule=True" in script
        assert 'schedule_time="2026-07-01 11:17"' in script

    def test_router_routes_xiaohongshu_comment_to_comment_script(self):
        router = SkillRouter(library_dir="src/skill_library")

        decision = router.route(
            "在小红书https://www.xiaohongshu.com/explore/698af8b4000000001b01c20b下发布评论，内容是“dwfebfer”"
        )

        assert decision.skill is not None
        assert decision.skill.id == "domain/xiaohongshu_comment"
        assert 'comment_text="dwfebfer"' in decision.script
        assert 'note_url="https://www.xiaohongshu.com/explore/698af8b4000000001b01c20b"' in decision.script

    def test_build_xiaohongshu_comment_script_passes_url_and_text(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(comment_text, note_url=None):\n    log(comment_text)"

        script = agent._build_skill_script(
            source,
            "在小红书https://www.xiaohongshu.com/explore/698af8b4000000001b01c20b?xsec_token=abc&xsec_source=pc_user下发布评论，内容是“dwfebfer”",
            "domain/xiaohongshu_comment",
        )

        assert 'run("dwfebfer", note_url=' in script
        assert "https://www.xiaohongshu.com/explore/698af8b4000000001b01c20b?xsec_token=abc&xsec_source=pc_user" in script

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

    def test_extract_bilibili_publish_fields(self):
        title, body = AgentLoop._extract_bilibili_publish_fields(
            "B站投稿，标题是测试标题，正文是第一段内容\n第二段内容"
        )

        assert title == "测试标题"
        assert body == "第一段内容\n第二段内容"

    def test_build_bilibili_publish_script_passes_phone_title_and_body(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(phone_number, title, body):\n    log(title)"

        script = agent._build_skill_script(
            source,
            "B站投稿，电话号码是13574133406，标题是测试标题，正文是测试正文",
            "domain/bilibili_publish",
        )

        assert 'run("13574133406", "测试标题", "测试正文")' in script

    def test_extract_bilibili_comment_example_fields(self):
        task = (
            "bilibili账号，电话号码是13574133406，在在视频"
            "https://www.bilibili.com/video/BV1oh7b6xE4R/"
            "?spm_id_from=333.1387.homepage.video_card.click"
            "&vd_source=6b653d6392c3b7bb0e204e07b9d93d96 下发布评论“test”。"
        )

        assert AgentLoop._extract_phone_number(task) == "13574133406"
        assert AgentLoop._extract_comment_text(task) == "test"
        assert AgentLoop._extract_video_url(task) == (
            "https://www.bilibili.com/video/BV1oh7b6xE4R/"
            "?spm_id_from=333.1387.homepage.video_card.click"
            "&vd_source=6b653d6392c3b7bb0e204e07b9d93d96"
        )

    def test_build_bilibili_comment_script_passes_phone_comment_and_url(self):
        agent = AgentLoop(max_steps=3)
        source = "def run(phone_number, comment_text, video_url=None):\n    log(comment_text)"

        script = agent._build_skill_script(
            source,
            (
                "bilibili账号，电话号码是13574133406，在视频"
                "https://www.bilibili.com/video/BV1oh7b6xE4R/ 下发布评论“test”。"
            ),
            "domain/bilibili_comment",
        )

        assert (
            'run("13574133406", "test", '
            'video_url="https://www.bilibili.com/video/BV1oh7b6xE4R/")'
        ) in script

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

    def test_select_gmail_login_beats_gmail_inbox_and_generic_login(self):
        from src.skill_library.skill_base import SkillMeta

        agent = AgentLoop(max_steps=3)
        skills = [
            SkillMeta(
                id="domain/gmail_inbox",
                name="Gmail 收件箱",
                type="domain",
                triggers=["gmail", "谷歌邮箱", "邮件", "收件箱"],
                url_patterns=["mail.google.com"],
            ),
            SkillMeta(
                id="domain/gmail_login",
                name="Gmail 登录",
                type="domain",
                triggers=["gmail", "谷歌邮箱", "登录", "账号", "邮箱", "密码", "验证码"],
                url_patterns=["mail.google.com", "accounts.google.com"],
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
            "Gmail登录，邮箱是che53438@gmail.com，密码是8105432a",
        )

        assert selected.id == "domain/gmail_login"

    def test_select_gmail_send_beats_gmail_login_and_inbox(self):
        from src.skill_library.skill_base import SkillMeta

        agent = AgentLoop(max_steps=3)
        skills = [
            SkillMeta(
                id="domain/gmail_inbox",
                name="Gmail 收件箱",
                type="domain",
                triggers=["gmail", "谷歌邮箱", "邮件", "收件箱"],
                url_patterns=["mail.google.com"],
            ),
            SkillMeta(
                id="domain/gmail_login",
                name="Gmail 登录",
                type="domain",
                triggers=["gmail", "谷歌邮箱", "登录", "账号", "邮箱", "密码", "验证码"],
                url_patterns=["mail.google.com", "accounts.google.com"],
            ),
            SkillMeta(
                id="domain/gmail_send",
                name="Gmail 发送邮件",
                type="domain",
                triggers=["gmail发送邮件", "gmail 发邮件", "发送邮件", "发邮件", "收件人", "send email"],
                url_patterns=["mail.google.com"],
            ),
        ]

        selected = agent._select_best_skill(
            skills,
            "Gmail发送邮件，收件人是alice@example.com，标题是测试标题，正文是测试正文",
        )

        assert selected.id == "domain/gmail_send"

    def test_select_bilibili_publish_beats_login_and_search(self):
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
                id="domain/bilibili_publish",
                name="Bilibili 文章投稿",
                type="domain",
                triggers=["bilibili", "B站", "投稿", "发布", "文章", "标题", "正文"],
                url_patterns=["bilibili.com", "*.bilibili.com", "member.bilibili.com"],
            ),
        ]

        selected = agent._select_best_skill(
            skills,
            "B站投稿，标题是测试标题，正文是测试正文",
        )

        assert selected.id == "domain/bilibili_publish"

    def test_select_bilibili_comment_beats_login_search_and_publish(self):
        from src.skill_library.skill_base import SkillMeta

        agent = AgentLoop(max_steps=3)
        skills = [
            SkillMeta(
                id="domain/bilibili_search",
                name="Bilibili 搜索",
                type="domain",
                triggers=["bilibili", "B站", "视频", "搜索"],
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
                id="domain/bilibili_publish",
                name="Bilibili 文章投稿",
                type="domain",
                triggers=["bilibili", "B站", "投稿", "文章", "标题", "正文"],
                url_patterns=["bilibili.com", "*.bilibili.com", "member.bilibili.com"],
            ),
            SkillMeta(
                id="domain/bilibili_comment",
                name="Bilibili 视频评论",
                type="domain",
                triggers=["bilibili", "B站", "评论", "发布评论", "视频评论"],
                url_patterns=["bilibili.com", "*.bilibili.com", "bilibili.com/video/"],
            ),
        ]

        selected = agent._select_best_skill(
            skills,
            "bilibili账号，电话号码是13574133406，在视频链接下发布评论“test”。",
        )

        assert selected.id == "domain/bilibili_comment"

    def test_select_xiaohongshu_publish_beats_login(self):
        from src.skill_library.skill_base import SkillMeta

        agent = AgentLoop(max_steps=3)
        skills = [
            SkillMeta(
                id="domain/xiaohongshu_login",
                name="小红书验证码登录",
                type="domain",
                triggers=["小红书", "xiaohongshu", "xhs", "rednote", "登录", "验证码"],
                url_patterns=["xiaohongshu.com", "*.xiaohongshu.com"],
            ),
            SkillMeta(
                id="domain/xiaohongshu_publish",
                name="小红书图文发布",
                type="domain",
                triggers=["小红书", "xiaohongshu", "xhs", "rednote", "发布", "图文", "内容", "生成图片"],
                url_patterns=["xiaohongshu.com", "*.xiaohongshu.com", "creator.xiaohongshu.com"],
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
            "小红书发布图文，电话号码是13574133406，内容是“今天的穿搭灵感”",
        )

        assert selected.id == "domain/xiaohongshu_publish"

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
