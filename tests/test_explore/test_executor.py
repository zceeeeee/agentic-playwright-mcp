"""Tests for Explore action executor."""

from src.core.explore.executor import ExploreExecutor
from src.core.explore.models import (
    Action,
    ActionBatch,
    AriaNode,
    ErrorCode,
    SnapshotMode,
    SnapshotResponse,
    WaitCondition,
)


class FakeMouse:
    def __init__(self, calls):
        self.calls = calls

    def wheel(self, x, y):
        self.calls.append(("wheel", x, y))


class FakeLocator:
    def __init__(self, page, ref):
        self.page = page
        self.ref = ref

    def click(self, **_kwargs):
        if self.ref in self.page.fail_refs:
            raise RuntimeError("click failed")
        self.page.calls.append(("click", self.ref))

    def fill(self, value, **_kwargs):
        self.page.calls.append(("fill", self.ref, value))

    def hover(self, **_kwargs):
        self.page.calls.append(("hover", self.ref))

    def select_option(self, value, **_kwargs):
        self.page.calls.append(("select", self.ref, value))

    def check(self, **_kwargs):
        self.page.calls.append(("check", self.ref))

    def uncheck(self, **_kwargs):
        self.page.calls.append(("uncheck", self.ref))

    def wait_for(self, **kwargs):
        self.page.calls.append(("wait_for", self.ref, kwargs.get("state")))

    def evaluate(self, _script):
        return f'[data-explore-ref="{self.ref}"]'


class FakePage:
    def __init__(self):
        self.calls = []
        self.fail_refs = set()
        self.mouse = FakeMouse(self.calls)

    def locator(self, selector):
        ref = selector.split('"')[1]
        return FakeLocator(self, ref)

    def goto(self, url, wait_until=None):
        self.calls.append(("goto", url, wait_until))

    def go_back(self):
        self.calls.append(("back",))

    def go_forward(self):
        self.calls.append(("forward",))

    def wait_for_load_state(self, state, timeout=None):
        self.calls.append(("load_state", state, timeout))

    def wait_for_timeout(self, timeout):
        self.calls.append(("timeout", timeout))

    def get_by_text(self, text):
        self.calls.append(("get_by_text", text))
        return FakeLocator(self, f"text:{text}")

    def screenshot(self, path=None):
        self.calls.append(("screenshot", path))


class FakePanelManager:
    def __init__(self):
        self.calls = []

    def set_title(self, page, title):
        self.calls.append(("title", page, title))

    def log(self, page, message):
        self.calls.append(("log", page, message))

    def toggle(self, page, visible):
        self.calls.append(("toggle", page, visible))

    def prompt(self, page, question):
        self.calls.append(("prompt", page, question))
        return "continue"

    def set_fields(self, page, fields):
        self.calls.append(("fields", page, fields))


def _snapshot(version="snapshot_v1"):
    return SnapshotResponse(
        version=version,
        mode=SnapshotMode.COMPACT,
        nodes=[
            AriaNode(role="button", name="Go", ref="e1"),
            AriaNode(role="textbox", name="Keyword", ref="e2"),
        ],
        interactive_count=2,
    )


def _executor(page=None):
    page = page or FakePage()
    executor = ExploreExecutor(page)
    executor.update_snapshot(_snapshot())
    return executor, page


def test_validate_batch_missing_action():
    executor, _page = _executor()

    result = executor.execute({"actions": [{}]})

    assert result.success is False
    assert result.error_code == ErrorCode.INVALID_FORMAT


def test_validate_batch_missing_ref():
    executor, _page = _executor()

    result = executor.execute(ActionBatch(actions=[Action(action="click")]))

    assert result.success is False
    assert result.error_code == ErrorCode.INVALID_FORMAT


def test_validate_version_mismatch():
    executor, _page = _executor()

    result = executor.execute(
        ActionBatch(actions=[Action(action="click", ref="e1", snapshot_v="old")])
    )

    assert result.success is False
    assert result.error_code == ErrorCode.SNAPSHOT_STALE


def test_validate_ref_expired():
    executor, _page = _executor()

    result = executor.execute(ActionBatch(actions=[Action(action="click", ref="e99")]))

    assert result.success is False
    assert result.error_code == ErrorCode.REF_EXPIRED


def test_navigation_terminator_stops_after_load_wait():
    executor, page = _executor()

    result = executor.execute(
        ActionBatch(
            actions=[
                Action(action="click", ref="e1"),
                Action(action="wait", condition=WaitCondition.LOAD),
                Action(action="fill", ref="e2", value="should not run"),
            ]
        )
    )

    assert result.success is True
    assert result.status == "navigation_occurred"
    assert result.need_snapshot is True
    assert [call[0] for call in page.calls] == ["click", "load_state"]


def test_rollback_on_failure_stops_following_actions():
    page = FakePage()
    page.fail_refs.add("e1")
    executor, page = _executor(page)

    result = executor.execute(
        ActionBatch(
            actions=[
                Action(action="click", ref="e1"),
                Action(action="wait", condition=WaitCondition.LOAD),
            ]
        )
    )

    assert result.success is False
    assert [call[0] for call in page.calls] == []


def test_sequential_execution():
    executor, page = _executor()

    result = executor.execute(
        ActionBatch(
            actions=[
                Action(action="fill", ref="e2", value="python"),
                Action(action="click", ref="e1"),
            ]
        )
    )

    assert result.success is True
    assert page.calls == [("fill", "e2", "python"), ("click", "e1")]


def test_login_popup_waits_for_cookie_then_requests_new_snapshot():
    class FakeContext:
        def __init__(self):
            self.logged_in = False

        def storage_state(self):
            if not self.logged_in:
                return {"cookies": [], "origins": []}
            return {
                "cookies": [
                    {
                        "name": "session",
                        "value": "abc123",
                        "domain": "example.com",
                    }
                ],
                "origins": [],
            }

    class LoginPage(FakePage):
        def __init__(self, context):
            super().__init__()
            self.context = context
            self.url = "https://example.com"
            self.login_required = False

        def goto(self, url, wait_until=None):
            self.url = url
            self.login_required = True
            super().goto(url, wait_until=wait_until)

        def evaluate(self, code):
            if "GENERIC_LOGIN_PROMPT_DETECTOR" in code:
                return {
                    "success": True,
                    "login_required": self.login_required,
                    "url": self.url,
                }
            return None

        def wait_for_timeout(self, timeout):
            super().wait_for_timeout(timeout)
            self.login_required = False
            self.context.logged_in = True

    class FakeBrowserManager:
        def __init__(self):
            self._context = FakeContext()
            self.page = LoginPage(self._context)
            self.current_domain = None
            self.saved_domains = []

        def save_auth(self, domain=None):
            self.saved_domains.append(domain)
            return True

    bm = FakeBrowserManager()
    executor = ExploreExecutor(bm.page, browser_manager=bm)
    executor.update_snapshot(_snapshot())

    result = executor.execute(
        ActionBatch(
            actions=[
                Action(action="goto", url="https://example.com/protected"),
                Action(action="fill", ref="e2", value="python"),
            ]
        )
    )

    assert result.success is True
    assert result.status == "login_completed"
    assert result.need_snapshot is True
    assert bm.saved_domains == ["example"]
    assert bm.page.calls == [
        ("goto", "https://example.com/protected", "load"),
        ("timeout", 1000),
    ]


def test_panel_prompt_is_terminator_and_skips_following_actions():
    executor, page = _executor()
    panel = FakePanelManager()
    executor._get_panel_manager = lambda: panel

    result = executor.execute(
        ActionBatch(
            actions=[
                Action(action="panel_show", title="Help", value="Need user input"),
                Action(
                    action="panel_prompt",
                    title="Help",
                    value="Continue? [yes] [no]",
                ),
                Action(action="click", ref="e1"),
            ]
        )
    )

    assert result.success is True
    assert result.status == "user_input_received"
    assert result.need_snapshot is True
    assert result.results[-1].value == "continue"
    assert [call[0] for call in panel.calls] == [
        "title",
        "log",
        "toggle",
        "title",
        "toggle",
        "prompt",
    ]
    assert page.calls == []
