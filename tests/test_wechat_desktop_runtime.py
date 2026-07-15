from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.agent_loop import AgentTaskResult
from src.desktop.database import DesktopDatabase
from src.desktop.events import DesktopEventHub
from src.desktop.task_service import (
    DesktopTaskService,
    TaskControl,
    _is_wechat_desktop_task,
)
from src.layer_2.controls import get_controls_exports


def test_only_wechat_ui_actions_are_desktop_only() -> None:
    assert _is_wechat_desktop_task("微信给张三发送你好")
    assert _is_wechat_desktop_task('微信给张三发送文件"D:\\tmp\\a.txt"')
    assert _is_wechat_desktop_task("微信关注火眼审阅公众号")
    assert not _is_wechat_desktop_task("微信聊天记录怎么恢复")
    assert not _is_wechat_desktop_task("微信查看张三最近的聊天记录")


def test_wechat_ui_task_does_not_launch_browser(tmp_path: Path) -> None:
    database = DesktopDatabase(tmp_path / "desktop.db")
    database.create_conversation("conversation-1", "微信任务")
    database.add_message(
        "user-1",
        "conversation-1",
        role="user",
        message_type="user",
        content="微信给张三发送你好",
        task_id="task-1",
    )
    database.create_task("task-1", "conversation-1", "user-1")
    service = DesktopTaskService(database, DesktopEventHub())
    control = TaskControl(task_id="task-1", conversation_id="conversation-1")
    browser = MagicMock()
    browser.is_alive.return_value = False
    agent = MagicMock()
    agent.run.return_value = AgentTaskResult(
        success=True,
        task="微信给张三发送你好",
        output="完成",
    )

    with (
        patch("src.desktop.task_service.get_browser_manager", return_value=browser),
        patch("src.desktop.task_service.AgentLoop", return_value=agent) as agent_class,
    ):
        service._run_task(control, "微信给张三发送你好")

    browser.launch.assert_not_called()
    assert agent_class.call_args.kwargs["desktop_only"] is True
    assert "wechat_send_contact_message" in get_controls_exports()
    assert "wechat_send_contact_file" in get_controls_exports()
    assert "wechat_read_contact_history" not in get_controls_exports()
    service.shutdown()
