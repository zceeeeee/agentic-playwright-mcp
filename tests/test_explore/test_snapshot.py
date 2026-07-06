"""Tests for Explore ARIA snapshots."""

from src.core.dom_explorer import summarize_page_aria
from src.core.explore.models import SnapshotMode
from src.core.explore.ref_generator import RefGenerator
from src.core.explore.snapshot import SnapshotGenerator


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def evaluate(self, _script, ref=None):
        self.page.synced_refs[self.selector] = ref


class FakePage:
    url = "https://example.com/search"

    def __init__(self):
        self.synced_refs = {}

    def title(self):
        return "Example"

    def evaluate(self, script, *_args):
        if "has_modal" in script:
            return {"has_modal": True}
        return {
            "role": "generic",
            "name": "root",
            "tag": "body",
            "selector": "body",
            "children": [
                {
                    "role": "heading",
                    "name": "Welcome",
                    "tag": "h1",
                    "selector": "h1",
                    "children": [],
                },
                {
                    "role": "button",
                    "name": "Search",
                    "tag": "button",
                    "selector": "#search",
                    "children": [],
                },
                {
                    "role": "textbox",
                    "name": "",
                    "tag": "input",
                    "selector": "#kw",
                    "placeholder": "Keyword",
                    "children": [],
                },
            ],
        }

    def locator(self, selector):
        return FakeLocator(self, selector)


def _refs(nodes):
    result = []
    for node in nodes:
        if node.ref:
            result.append(node.ref)
        result.extend(_refs(node.children))
    return result


def test_ref_assignment_only_interactive_roles():
    gen = RefGenerator()
    assert gen.generate("heading") is None
    assert gen.generate("button") == "e1"
    assert gen.generate("textbox") == "e2"


def test_compact_mode_filters_non_interactive_leaf():
    page = FakePage()
    snapshot = SnapshotGenerator().snapshot(page, mode=SnapshotMode.COMPACT)

    assert snapshot.version == "snapshot_v1"
    assert snapshot.mode == SnapshotMode.COMPACT
    assert snapshot.interactive_count == 2
    assert _refs(snapshot.nodes) == ["e1", "e2"]
    assert "#search" in page.synced_refs
    assert "h1" not in page.synced_refs


def test_version_increment():
    page = FakePage()
    gen = SnapshotGenerator()

    first = gen.snapshot(page)
    second = gen.snapshot(page)

    assert first.version == "snapshot_v1"
    assert second.version == "snapshot_v2"


def test_dom_explorer_aria_summary_returns_dict():
    summary = summarize_page_aria(FakePage())

    assert summary["version"] == "snapshot_v1"
    assert summary["interactive_count"] == 2
