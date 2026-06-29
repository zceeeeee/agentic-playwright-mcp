"""Tests for skill_library.registry -- SkillRegistry, SkillFileMapping, SkillDetail, YAML loading."""

from __future__ import annotations

import pytest
import yaml

from src.skill_library.registry import (
    SkillDetail,
    SkillFileMapping,
    SkillRegistry,
    get_skill_registry,
    reset_skill_registry,
)
from src.skill_library.skill_base import SkillMeta

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_metas():
    return [
        SkillMeta(
            id="domain/baidu_search",
            name="百度搜索",
            type="domain",
            triggers=["百度", "baidu", "搜索", "search"],
            url_patterns=["baidu.com"],
            description="在百度搜索关键词",
            version="1.0.0",
        ),
        SkillMeta(
            id="interaction/login_flow",
            name="通用登录",
            type="interaction",
            triggers=["登录", "login", "sign in"],
            url_patterns=[],
            description="通用登录流程",
            version="1.0.0",
        ),
    ]


@pytest.fixture
def registry(sample_metas):
    reg = SkillRegistry()
    for meta in sample_metas:
        reg.register(meta)
    return reg


@pytest.fixture
def skills_yaml_content():
    return {
        "skills": [
            {
                "id": "domain/baidu_search",
                "name": "百度搜索",
                "type": "domain",
                "triggers": ["百度", "baidu", "搜索"],
                "url_patterns": ["baidu.com"],
                "description": "在百度搜索关键词",
                "version": "1.0.0",
            },
            {
                "id": "interaction/search_flow",
                "name": "通用搜索",
                "type": "interaction",
                "triggers": ["搜索", "search"],
                "url_patterns": [],
                "description": "通用搜索流程",
                "version": "1.0.0",
            },
        ],
        "sources": [
            {
                "id": "domain/baidu_search",
                "file": "search/baidu_search.py",
                "entry": "run",
            },
            {
                "id": "interaction/search_flow",
                "file": "search/search_flow.py",
            },
        ],
    }


@pytest.fixture
def registry_with_yaml(tmp_path, skills_yaml_content):
    """Create a SkillRegistry loaded from a temp skills.yaml with real file stubs."""
    # Create source files
    search_dir = tmp_path / "search"
    search_dir.mkdir()
    (search_dir / "baidu_search.py").write_text(
        "def run(keyword):\n    pass\n", encoding="utf-8"
    )

    (search_dir / "search_flow.py").write_text(
        "def run(url, keyword):\n    pass\n", encoding="utf-8"
    )

    # Create guide files
    guides_dir = tmp_path / "guides"
    guides_dir.mkdir()
    (guides_dir / "how_to_baidu_search.md").write_text(
        "# 百度搜索指南\n", encoding="utf-8"
    )

    # Write skills.yaml
    yaml_path = tmp_path / "skills.yaml"
    yaml_path.write_text(
        yaml.dump(skills_yaml_content, allow_unicode=True), encoding="utf-8"
    )

    reg = SkillRegistry(library_dir=tmp_path)
    reg.load_from_yaml(yaml_path)
    return reg, tmp_path


# ---------------------------------------------------------------------------
# SkillFileMapping
# ---------------------------------------------------------------------------


class TestSkillFileMapping:
    def test_construction(self):
        fm = SkillFileMapping(id="test/skill", file="path/to/skill.py", entry="run")
        assert fm.id == "test/skill"
        assert fm.file == "path/to/skill.py"
        assert fm.entry == "run"

    def test_default_entry(self):
        fm = SkillFileMapping(id="test/skill", file="skill.py")
        assert fm.entry == "run"


# ---------------------------------------------------------------------------
# SkillDetail
# ---------------------------------------------------------------------------


class TestSkillDetail:
    def test_construction_minimal(self):
        meta = SkillMeta(id="test/s", name="S", type="interaction")
        detail = SkillDetail(meta=meta)
        assert detail.meta.id == "test/s"
        assert detail.file_mapping is None
        assert detail.source_code == ""
        assert detail.guide == ""
        assert detail.instance is None


# ---------------------------------------------------------------------------
# SkillRegistry -- registration
# ---------------------------------------------------------------------------


class TestSkillRegistryRegister:
    def test_register_single(self, registry):
        assert len(registry.list_all()) == 2

    def test_register_many(self):
        reg = SkillRegistry()
        metas = [
            SkillMeta(id="a/b", name="B", type="domain"),
            SkillMeta(id="c/d", name="D", type="interaction"),
        ]
        reg.register_many([(m, None) for m in metas])
        assert len(reg.list_all()) == 2

    def test_register_overwrites_same_id(self, registry):
        new_meta = SkillMeta(id="domain/baidu_search", name="百度搜索v2", type="domain")
        registry.register(new_meta)
        assert len(registry.list_all()) == 2  # no duplicate
        assert registry.get("domain/baidu_search").name == "百度搜索v2"  # overwritten

    def test_register_with_file_mapping(self):
        reg = SkillRegistry()
        meta = SkillMeta(id="test/skill", name="Test", type="interaction")
        fm = SkillFileMapping(id="test/skill", file="test.py", entry="run")
        reg.register(meta, file_mapping=fm)
        detail = reg.get_detail("test/skill")
        assert detail is not None
        assert detail.file_mapping is not None
        assert detail.file_mapping.file == "test.py"

    def test_register_without_file_mapping(self):
        reg = SkillRegistry()
        meta = SkillMeta(id="test/skill", name="Test", type="interaction")
        reg.register(meta)
        detail = reg.get_detail("test/skill")
        assert detail is not None
        assert detail.file_mapping is None


# ---------------------------------------------------------------------------
# SkillRegistry -- search by query
# ---------------------------------------------------------------------------


class TestSkillRegistrySearchQuery:
    def test_match_trigger(self, registry):
        results = registry.search(query="百度")
        assert len(results) == 1
        assert results[0].id == "domain/baidu_search"

    def test_match_trigger_case_insensitive(self, registry):
        results = registry.search(query="BAIDU")
        assert len(results) == 1
        assert results[0].id == "domain/baidu_search"

    def test_match_partial_trigger_in_query(self, registry):
        """Query '我想搜索一下' contains '搜索' which is a trigger."""
        results = registry.search(query="我想搜索一下")
        assert len(results) == 1
        assert results[0].id == "domain/baidu_search"

    def test_match_multiple_skills(self, registry):
        """Query '登录搜索' matches both skills (登录 -> login, 搜索 -> baidu)."""
        results = registry.search(query="登录搜索")
        ids = {r.id for r in results}
        assert "domain/baidu_search" in ids
        assert "interaction/login_flow" in ids

    def test_no_match(self, registry):
        results = registry.search(query="不存在的关键词")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# SkillRegistry -- search by URL
# ---------------------------------------------------------------------------


class TestSkillRegistrySearchUrl:
    def test_match_url_pattern(self, registry):
        results = registry.search(url="https://www.baidu.com/s?wd=test")
        assert len(results) == 1
        assert results[0].id == "domain/baidu_search"

    def test_match_url_substring(self, registry):
        results = registry.search(url="https://baidu.com")
        assert len(results) == 1

    def test_no_url_match(self, registry):
        results = registry.search(url="https://google.com")
        assert len(results) == 0

    def test_empty_url_patterns_never_match(self, registry):
        """login_flow has no url_patterns, so url search should not match it."""
        results = registry.search(url="https://example.com/login")
        # Only skills with url_patterns can match
        for r in results:
            assert r.id != "interaction/login_flow"


# ---------------------------------------------------------------------------
# SkillRegistry -- get by ID
# ---------------------------------------------------------------------------


class TestSkillRegistryGet:
    def test_get_existing(self, registry):
        meta = registry.get("domain/baidu_search")
        assert meta is not None
        assert meta.name == "百度搜索"

    def test_get_nonexistent(self, registry):
        assert registry.get("nonexistent") is None


# ---------------------------------------------------------------------------
# SkillRegistry -- list_all
# ---------------------------------------------------------------------------


class TestSkillRegistryListAll:
    def test_list_all(self, registry):
        all_skills = registry.list_all()
        assert len(all_skills) == 2
        ids = {s.id for s in all_skills}
        assert ids == {"domain/baidu_search", "interaction/login_flow"}

    def test_list_all_empty(self):
        reg = SkillRegistry()
        assert reg.list_all() == []


# ---------------------------------------------------------------------------
# SkillRegistry -- YAML loading
# ---------------------------------------------------------------------------


class TestSkillRegistryYamlLoading:
    def test_load_from_yaml(self, registry_with_yaml):
        reg, _ = registry_with_yaml
        assert len(reg.list_all()) == 2
        assert reg.get("domain/baidu_search") is not None
        assert reg.get("interaction/search_flow") is not None

    def test_load_from_yaml_with_sources(self, registry_with_yaml):
        reg, _ = registry_with_yaml
        detail = reg.get_detail("domain/baidu_search")
        assert detail is not None
        assert detail.file_mapping is not None
        assert detail.file_mapping.file == "search/baidu_search.py"
        assert detail.file_mapping.entry == "run"

    def test_load_from_yaml_source_default_entry(self, registry_with_yaml):
        """search_flow source has no explicit 'entry', should default to 'run'."""
        reg, _ = registry_with_yaml
        detail = reg.get_detail("interaction/search_flow")
        assert detail is not None
        assert detail.file_mapping.entry == "run"

    def test_load_from_yaml_missing_file(self, tmp_path):
        reg = SkillRegistry(library_dir=tmp_path)
        reg.load_from_yaml(tmp_path / "nonexistent.yaml")
        assert len(reg.list_all()) == 0

    def test_load_from_yaml_auto_path(self, tmp_path, skills_yaml_content):
        """When yaml_path is None, should look for skills.yaml in library_dir."""
        yaml_path = tmp_path / "skills.yaml"
        yaml_path.write_text(
            yaml.dump(skills_yaml_content, allow_unicode=True), encoding="utf-8"
        )
        reg = SkillRegistry(library_dir=tmp_path)
        reg.load_from_yaml()  # auto-discover
        assert len(reg.list_all()) == 2

    def test_load_from_yaml_no_library_dir(self):
        """When library_dir is None and yaml_path is None, should be a no-op."""
        reg = SkillRegistry()
        reg.load_from_yaml()
        assert len(reg.list_all()) == 0

    def test_load_from_yaml_empty_file(self, tmp_path):
        yaml_path = tmp_path / "skills.yaml"
        yaml_path.write_text("", encoding="utf-8")
        reg = SkillRegistry(library_dir=tmp_path)
        reg.load_from_yaml(yaml_path)
        assert len(reg.list_all()) == 0


# ---------------------------------------------------------------------------
# SkillRegistry -- get_detail
# ---------------------------------------------------------------------------


class TestSkillRegistryGetDetail:
    def test_detail_with_source_and_guide(self, registry_with_yaml):
        reg, _ = registry_with_yaml
        detail = reg.get_detail("domain/baidu_search")
        assert detail is not None
        assert detail.meta.id == "domain/baidu_search"
        assert "def run" in detail.source_code
        assert "百度搜索指南" in detail.guide

    def test_detail_without_guide(self, registry_with_yaml):
        """search_flow has no guide file."""
        reg, _ = registry_with_yaml
        detail = reg.get_detail("interaction/search_flow")
        assert detail is not None
        assert detail.guide == ""

    def test_detail_not_found(self, registry_with_yaml):
        reg, _ = registry_with_yaml
        assert reg.get_detail("nonexistent") is None

    def test_detail_without_library_dir(self, registry):
        """Without library_dir, detail should have meta but no source/guide."""
        detail = registry.get_detail("domain/baidu_search")
        assert detail is not None
        assert detail.source_code == ""
        assert detail.guide == ""
        assert detail.file_mapping is None

    def test_detail_source_file_missing_on_disk(self, tmp_path):
        """Source file listed in yaml but missing from disk."""
        skills_data = {
            "skills": [
                {
                    "id": "test/missing",
                    "name": "Missing",
                    "type": "interaction",
                    "triggers": [],
                    "url_patterns": [],
                }
            ],
            "sources": [
                {"id": "test/missing", "file": "nonexistent.py", "entry": "run"}
            ],
        }
        yaml_path = tmp_path / "skills.yaml"
        yaml_path.write_text(
            yaml.dump(skills_data, allow_unicode=True), encoding="utf-8"
        )
        reg = SkillRegistry(library_dir=tmp_path)
        reg.load_from_yaml(yaml_path)
        detail = reg.get_detail("test/missing")
        assert detail is not None
        assert detail.source_code == ""  # file not on disk


# ---------------------------------------------------------------------------
# SkillRegistry -- _matches_query (static method)
# ---------------------------------------------------------------------------


class TestMatchesQuery:
    def test_trigger_substring_match(self):
        meta = SkillMeta(id="test", name="Test", type="interaction", triggers=["搜索"])
        assert SkillRegistry._matches_query(meta, "帮我搜索一下") is True

    def test_trigger_case_insensitive(self):
        meta = SkillMeta(id="test", name="Test", type="interaction", triggers=["LOGIN"])
        assert SkillRegistry._matches_query(meta, "please login") is True

    def test_no_trigger_match(self):
        meta = SkillMeta(id="test", name="Test", type="interaction", triggers=["搜索"])
        assert SkillRegistry._matches_query(meta, "打开网页") is False

    def test_empty_triggers(self):
        meta = SkillMeta(id="test", name="Test", type="interaction", triggers=[])
        assert SkillRegistry._matches_query(meta, "anything") is False


# ---------------------------------------------------------------------------
# SkillRegistry -- _matches_url (static method)
# ---------------------------------------------------------------------------


class TestMatchesUrl:
    def test_wildcard_pattern(self):
        meta = SkillMeta(
            id="test",
            name="Test",
            type="domain",
            url_patterns=["*.baidu.com"],
        )
        assert SkillRegistry._matches_url(meta, "https://www.baidu.com/s") is True

    def test_plain_substring(self):
        meta = SkillMeta(
            id="test", name="Test", type="domain", url_patterns=["baidu.com"]
        )
        assert SkillRegistry._matches_url(meta, "https://baidu.com") is True

    def test_no_match(self):
        meta = SkillMeta(
            id="test", name="Test", type="domain", url_patterns=["*.baidu.com"]
        )
        assert SkillRegistry._matches_url(meta, "https://google.com") is False

    def test_empty_patterns(self):
        meta = SkillMeta(id="test", name="Test", type="domain", url_patterns=[])
        assert SkillRegistry._matches_url(meta, "https://example.com") is False

    def test_case_insensitive(self):
        meta = SkillMeta(
            id="test", name="Test", type="domain", url_patterns=["*.GitHub.COM"]
        )
        # Pattern '*.GitHub.COM' strips to '.github.com' which is a substring of the url
        assert SkillRegistry._matches_url(meta, "https://www.github.com/login") is True


# ---------------------------------------------------------------------------
# SkillRegistry -- _infer_guide_path
# ---------------------------------------------------------------------------


class TestInferGuidePath:
    def test_infers_correctly(self, tmp_path):
        reg = SkillRegistry(library_dir=tmp_path)
        fm = SkillFileMapping(id="test", file="search/baidu_search.py")
        guide_path = reg._infer_guide_path(fm)
        assert guide_path == tmp_path / "guides" / "how_to_baidu_search.md"

    def test_no_library_dir(self):
        reg = SkillRegistry()
        fm = SkillFileMapping(id="test", file="search/baidu_search.py")
        assert reg._infer_guide_path(fm) is None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def teardown_method(self):
        reset_skill_registry()

    def test_singleton_returns_same_instance(self):
        r1 = get_skill_registry()
        r2 = get_skill_registry()
        assert r1 is r2

    def test_reset_creates_new_instance(self):
        r1 = get_skill_registry()
        reset_skill_registry()
        r2 = get_skill_registry()
        assert r1 is not r2

    def test_singleton_with_library_dir(self, tmp_path):
        yaml_path = tmp_path / "skills.yaml"
        yaml_path.write_text(
            yaml.dump(
                {
                    "skills": [
                        {
                            "id": "test/s",
                            "name": "S",
                            "type": "interaction",
                            "triggers": [],
                            "url_patterns": [],
                        }
                    ]
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        reg = get_skill_registry(library_dir=tmp_path)
        assert len(reg.list_all()) == 1
