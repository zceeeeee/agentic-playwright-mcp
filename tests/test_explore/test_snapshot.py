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

    def aria_snapshot(self, mode=None, boxes=None):
        return self.page._native_yaml


class FakePage:
    url = "https://example.com/search"

    def __init__(self):
        self.synced_refs = {}
        self._native_yaml = ""

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

    def get_by_role(self, role, name=None):
        return FakeLocator(self, f'[role="{role}"]')


def _refs(nodes):
    result = []
    for node in nodes:
        if node.ref:
            result.append(node.ref)
        result.extend(_refs(node.children))
    return result


def _roles(nodes):
    result = []
    for node in nodes:
        result.append(node.role)
        result.extend(_roles(node.children))
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


def test_snapshot_traverses_display_contents_container():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 800, "height": 600})
        page.set_content(
            """
            <main>
              <div style="display: contents">
                <input type="search" placeholder="Filter by name">
              </div>
            </main>
            """
        )
        generator = SnapshotGenerator()

        snapshot = generator.snapshot(page, mode=SnapshotMode.COMPACT)
        deep_snapshot = generator.force_deep_scan(
            page,
            mode=SnapshotMode.COMPACT,
        )
        browser.close()

    assert snapshot.interactive_count == 1
    assert deep_snapshot.interactive_count == 1
    assert "searchbox" in _roles(snapshot.nodes)


# ---------------------------------------------------------------------------
# Tests for Playwright native aria_snapshot integration
# ---------------------------------------------------------------------------


class TestNativeAriaSnapshot:
    """Test Playwright native aria_snapshot integration."""

    def test_parse_simple_yaml(self):
        """Parse simple YAML snapshot."""
        yaml_text = """
- button "Submit" [ref=e1]
- textbox "Email" [ref=e2]
"""
        result = SnapshotGenerator._parse_aria_yaml(yaml_text)
        assert result["role"] == "generic"  # root
        assert len(result["children"]) == 2
        assert result["children"][0]["role"] == "button"
        assert result["children"][0]["name"] == "Submit"
        assert result["children"][0]["ref"] == "e1"
        assert result["children"][1]["role"] == "textbox"
        assert result["children"][1]["name"] == "Email"
        assert result["children"][1]["ref"] == "e2"

    def test_parse_nested_yaml(self):
        """Parse nested YAML with indented children."""
        yaml_text = """
- navigation "Main Nav":
  - link "Home" [ref=e1]
  - link "About" [ref=e2]
- main "Content":
  - button "Click me" [ref=e3]
"""
        result = SnapshotGenerator._parse_aria_yaml(yaml_text)
        assert len(result["children"]) == 2
        nav = result["children"][0]
        assert nav["role"] == "navigation"
        assert nav["name"] == "Main Nav"
        assert len(nav["children"]) == 2
        assert nav["children"][0]["role"] == "link"
        assert nav["children"][0]["ref"] == "e1"
        main = result["children"][1]
        assert main["role"] == "main"
        assert len(main["children"]) == 1
        assert main["children"][0]["ref"] == "e3"

    def test_parse_yaml_with_attributes(self):
        """Parse YAML with checked, level, disabled attributes."""
        yaml_text = """
- checkbox [checked] [ref=e1]
- heading "Title" [level=2]
- textbox "Name" [disabled] [ref=e2]
"""
        result = SnapshotGenerator._parse_aria_yaml(yaml_text)
        assert result["children"][0]["ref"] == "e1"
        assert result["children"][0].get("checked") is True
        assert result["children"][1]["level"] == 2
        assert result["children"][2]["disabled"] is True

    def test_parse_yaml_with_text_node(self):
        """Parse pure text nodes - content merges into parent name."""
        yaml_text = """
- paragraph:
  - text: Hello world
"""
        result = SnapshotGenerator._parse_aria_yaml(yaml_text)
        assert len(result["children"]) == 1
        para = result["children"][0]
        assert para["role"] == "paragraph"
        assert "Hello world" in para["name"]

    def test_parse_yaml_with_url_property(self):
        """Parse link href property node."""
        yaml_text = """
- link "Home" [ref=e1]:
  - /url: "https://example.com"
"""
        result = SnapshotGenerator._parse_aria_yaml(yaml_text)
        link = result["children"][0]
        assert link["role"] == "link"
        assert link["ref"] == "e1"
        # URL is stored as a special child
        assert len(link["children"]) == 1
        assert link["children"][0]["role"] == "__url"

    def test_native_api_returns_refs(self):
        """Native API refs map directly to AriaNode.ref."""
        page = FakePage()
        page._native_yaml = """
- button "OK" [ref=e1]
- textbox "Name" [ref=e2]
"""
        gen = SnapshotGenerator()
        snapshot = gen.snapshot(page, mode=SnapshotMode.FULL)

        assert snapshot.interactive_count == 2
        refs = _refs(snapshot.nodes)
        assert "e1" in refs
        assert "e2" in refs

    def test_fallback_to_custom_js(self):
        """When aria_snapshot raises AttributeError, fall back to custom JS."""
        page = FakePage()
        # Make aria_snapshot raise AttributeError
        original_locator = page.locator

        def broken_locator(selector):
            loc = original_locator(selector)
            loc.aria_snapshot = lambda **kwargs: (_ for _ in ()).throw(
                AttributeError("aria_snapshot not available")
            )
            return loc

        page.locator = broken_locator
        gen = SnapshotGenerator()
        snapshot = gen.snapshot(page, mode=SnapshotMode.COMPACT)

        # Should still get results via fallback JS
        assert snapshot.version == "snapshot_v1"
        assert snapshot.interactive_count == 2

    def test_compact_mode_with_native_refs(self):
        """Compact mode filters correctly when native refs are present."""
        page = FakePage()
        page._native_yaml = """
- heading "Welcome" [ref=e0]
- button "Submit" [ref=e1]
- textbox "Email" [ref=e2]
- paragraph "Footer text"
"""
        gen = SnapshotGenerator()
        snapshot = gen.snapshot(page, mode=SnapshotMode.COMPACT)

        # heading and paragraph should be filtered out in compact mode
        refs = _refs(snapshot.nodes)
        assert "e1" in refs
        assert "e2" in refs
        assert "e0" not in refs  # heading filtered

    def test_fallback_ref_generator_used_when_no_native_refs(self):
        """RefGenerator assigns refs when native API produces no refs."""
        page = FakePage()
        # Native YAML without any ref attributes
        page._native_yaml = """
- button "Submit"
- textbox "Email"
"""
        gen = SnapshotGenerator()
        snapshot = gen.snapshot(page, mode=SnapshotMode.FULL)

        # RefGenerator should have assigned refs
        refs = _refs(snapshot.nodes)
        assert len(refs) == 2
        assert refs[0] == "e1"
        assert refs[1] == "e2"
