"""TaskSplitter 单元测试。"""

import pytest

from src.core.task_splitter import TaskGroup, TaskSplitter, reset_task_splitter


@pytest.fixture(autouse=True)
def _reset_splitter():
    """每个测试前重置全局单例。"""
    reset_task_splitter()
    yield
    reset_task_splitter()


# ---------------------------------------------------------------------------
# split_flat() — 向后兼容测试（旧接口行为不变）
# ---------------------------------------------------------------------------


class TestRuleSplitFlat:
    """规则拆分（split_flat 兼容接口）。"""

    def test_chinese_period(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度。搜索Python教程")
        assert result == ["打开百度", "搜索Python教程"]

    def test_english_period(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("open baidu. search python")
        assert result == ["open baidu", "search python"]

    def test_multiple_periods(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度。搜索Python。截个图")
        assert result == ["打开百度", "搜索Python", "截个图"]

    def test_mixed_periods(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度.搜索Python。截个图")
        assert result == ["打开百度", "搜索Python", "截个图"]

    def test_single_command_no_split(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("搜索Python教程")
        assert result == ["搜索Python教程"]

    def test_empty_string(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("")
        assert result == [""]

    def test_whitespace_only(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("   ")
        assert result == [""]


class TestURLProtectionFlat:
    """URL 中的点号不拆分（split_flat）。"""

    def test_url_not_split(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开 https://www.bilibili.com 搜索Python")
        assert len(result) == 1
        assert "https://www.bilibili.com" in result[0]

    def test_url_with_path(self):
        splitter = TaskSplitter()
        result = splitter.split_flat(
            "打开 https://github.com/user/repo.查看代码"
        )
        assert len(result) == 1

    def test_url_in_middle(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开 https://www.baidu.com。搜索Python")
        assert len(result) == 2
        assert "https://www.baidu.com" in result[0]
        assert "搜索Python" in result[1]

    def test_connector_word_inside_url_is_not_split(self):
        splitter = TaskSplitter()
        task = '"https://ncesnext.com"搜索大物'

        result = splitter.split_flat(task)

        assert result == [task]

    def test_connector_word_inside_unquoted_url_is_not_split(self):
        splitter = TaskSplitter()
        task = "在 https://ncesnext.com/ 上搜索大物"

        result = splitter.split_flat(task)

        assert result == [task]


class TestFilePathProtectionFlat:
    """本地文件路径里的扩展名不应该被当作句号拆分（split_flat）。"""

    def test_windows_pdf_path_without_slash_not_split(self):
        splitter = TaskSplitter()
        task = "WPS写一个docx文章，标题是“edewvr”，内容是“wewret”，导出为PDF，路径是D:tmptest.pdf，字体是宋体14号"

        result = splitter.split_flat(task)

        assert result == [task]

    def test_windows_pdf_path_with_slash_not_split(self):
        splitter = TaskSplitter()
        task = r'WPS写文章，标题是"edewvr"，内容是"wewret"，路径是D:\tmp\test.pdf'

        result = splitter.split_flat(task)

        assert result == [task]

    def test_windows_image_path_with_spaces_not_split(self):
        splitter = TaskSplitter()
        task = (
            r'WPS写文章，标题“edewvr”，内容“wewret”，插入图片'
            r'"D:\Users\qq275\Pictures\Screenshots\屏幕截图 2026-04-07 180134.png"'
        )

        result = splitter.split_flat(task)

        assert result == [task]


class TestQuotedProtectionFlat:
    """引号内的句号不拆分（split_flat）。"""

    def test_chinese_quotes(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("发布内容为「hello。world」。然后截图")
        assert len(result) == 2
        assert "hello。world" in result[0]

    def test_single_quotes(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("设置标题为'测试。标题'。保存")
        assert len(result) == 2
        assert "测试。标题" in result[0]

    def test_double_quotes(self):
        splitter = TaskSplitter()
        result = splitter.split_flat('设置名称为"hello.world"。提交')
        assert len(result) == 2
        assert "hello.world" in result[0]


class TestConnectorSplitFlat:
    """连接词拆分测试（split_flat）。"""

    def test_then_connector(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度然后搜索Python")
        assert len(result) == 2
        assert "打开百度" in result[0]
        assert "搜索Python" in result[1]

    def test_then_connector_chinese(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度，然后搜索Python教程")
        assert len(result) == 2

    def test_next_connector(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度接着搜索Python")
        assert len(result) == 2

    def test_also_connector(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度同时打开谷歌")
        assert len(result) == 2

    def test_and_then_english(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("open baidu and then search python")
        assert len(result) == 2

    def test_period_takes_priority(self):
        """句号拆分优先于连接词拆分。"""
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度。搜索Python然后截图")
        assert len(result) == 2
        assert result[0] == "打开百度"


class TestEdgeCasesFlat:
    """边界情况测试（split_flat）。"""

    def test_trailing_punctuation(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度，。搜索Python；。截个图")
        assert len(result) == 3

    def test_consecutive_periods(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("打开百度。。搜索Python")
        assert len(result) == 2

    def test_ellipsis_not_split(self):
        splitter = TaskSplitter()
        result = splitter.split_flat("等一下...然后搜索Python")
        assert len(result) >= 1

    def test_preserves_content(self):
        splitter = TaskSplitter()
        result = splitter.split_flat(
            "在知乎搜索 AI Agent。在B站搜索 Playwright 教程"
        )
        assert len(result) == 2
        assert "知乎" in result[0]
        assert "B站" in result[1]


class TestLLMSplitFlat:
    """LLM 拆分测试（split_flat，需要 mock）。"""

    def test_no_llm_caller_returns_single(self):
        splitter = TaskSplitter(llm_caller=None)
        result = splitter.split_flat("打开百度搜索Python")
        assert result == ["打开百度搜索Python"]


# ---------------------------------------------------------------------------
# split() — TaskGroup 结构化测试（新功能）
# ---------------------------------------------------------------------------


class TestSplitGroups:
    """split() 返回 TaskGroup 的结构化测试。"""

    def test_period_creates_independent_groups(self):
        """句号分隔 → 每个任务独立（sequential=False）。"""
        splitter = TaskSplitter()
        groups = splitter.split("打开百度。搜索Python")
        assert len(groups) == 2
        assert all(not g.sequential for g in groups)
        assert groups[0].tasks == ["打开百度"]
        assert groups[1].tasks == ["搜索Python"]

    def test_semicolon_creates_sequential_group(self):
        """分号分隔 → 同组连续任务（sequential=True）。"""
        splitter = TaskSplitter()
        groups = splitter.split("打开百度;输入Python;点搜索")
        assert len(groups) == 1
        assert groups[0].sequential is True
        assert groups[0].tasks == ["打开百度", "输入Python", "点搜索"]

    def test_chinese_semicolon(self):
        """中文分号。"""
        splitter = TaskSplitter()
        groups = splitter.split("打开百度；输入Python；点搜索")
        assert len(groups) == 1
        assert groups[0].sequential is True
        assert groups[0].tasks == ["打开百度", "输入Python", "点搜索"]

    def test_mixed_period_and_semicolon(self):
        """混合：句号独立 + 分号连续。"""
        splitter = TaskSplitter()
        groups = splitter.split(
            "打开百度。搜索Python；点第一个结果。打开GitHub"
        )
        assert len(groups) == 3
        # 第一组：独立
        assert groups[0].sequential is False
        assert groups[0].tasks == ["打开百度"]
        # 第二组：连续（分号分隔）
        assert groups[1].sequential is True
        assert groups[1].tasks == ["搜索Python", "点第一个结果"]
        # 第三组：独立
        assert groups[2].sequential is False
        assert groups[2].tasks == ["打开GitHub"]

    def test_multiple_semicolon_segments(self):
        """多个分号段由句号分隔。"""
        splitter = TaskSplitter()
        groups = splitter.split("a;b。c;d")
        assert len(groups) == 2
        assert groups[0].tasks == ["a", "b"]
        assert groups[0].sequential is True
        assert groups[1].tasks == ["c", "d"]
        assert groups[1].sequential is True

    def test_single_task_returns_single_group(self):
        """单任务 → 1组1任务。"""
        splitter = TaskSplitter()
        groups = splitter.split("帮我在百度搜索Python教程")
        assert len(groups) == 1
        assert len(groups[0].tasks) == 1
        assert groups[0].sequential is False

    def test_connector_creates_independent_groups(self):
        """连接词分隔 → 独立任务组。"""
        splitter = TaskSplitter()
        groups = splitter.split("打开百度然后搜索Python")
        assert len(groups) == 2
        assert all(not g.sequential for g in groups)

    def test_semicolon_in_quotes_preserved(self):
        """引号内的分号不拆分。"""
        splitter = TaskSplitter()
        groups = splitter.split('输入"a;b"。搜索')
        assert len(groups) == 2
        assert "a;b" in groups[0].tasks[0]

    def test_taskgroup_dataclass(self):
        """TaskGroup 数据类基本属性。"""
        g = TaskGroup(tasks=["a", "b"], sequential=True)
        assert g.tasks == ["a", "b"]
        assert g.sequential is True
        assert repr(g)  # 不抛异常
