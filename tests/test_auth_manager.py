"""Tests for core.auth_manager — per-domain cookie persistence."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.core.auth_manager import AuthManager, get_auth_manager, reset_auth_manager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_auth_dir(tmp_path):
    """Return a temporary auth directory (pre-created)."""
    d = tmp_path / "auth"
    d.mkdir()
    return d


@pytest.fixture
def tmp_domains_dir(tmp_path):
    """Return a temporary domains directory with sample YAML files."""
    domains = tmp_path / "domains"
    domains.mkdir()
    # Create sample domain YAML files
    (domains / "baidu.yaml").write_text(
        "name: baidu\nbase_url: https://www.baidu.com\nlocators:\n  search_input:\n    css: ['#kw']\n",
        encoding="utf-8",
    )
    (domains / "github.yaml").write_text(
        "name: github\nbase_url: https://github.com\nlocators:\n  login:\n    css: ['#login']\n",
        encoding="utf-8",
    )
    return domains


@pytest.fixture
def auth_manager(tmp_auth_dir, tmp_domains_dir):
    """Return an AuthManager with temp directories."""
    return AuthManager(auth_dir=tmp_auth_dir, domains_dir=tmp_domains_dir)


# ---------------------------------------------------------------------------
# list_domains
# ---------------------------------------------------------------------------


class TestListDomains:
    """Tests for AuthManager.list_domains()."""

    def test_returns_all_domains(self, auth_manager):
        """Should list all YAML files in domains/."""
        domains = auth_manager.list_domains()
        names = [d["domain"] for d in domains]
        assert "baidu" in names
        assert "github" in names

    def test_has_auth_false_initially(self, auth_manager):
        """All domains should have has_auth=False when no auth saved."""
        domains = auth_manager.list_domains()
        for d in domains:
            assert d["has_auth"] is False

    def test_has_auth_true_after_save(self, auth_manager):
        """Domain should show has_auth=True after saving."""
        mock_context = MagicMock()

        def fake_storage_state(path):
            with open(path, "w") as f:
                json.dump({"cookies": [], "origins": []}, f)

        mock_context.storage_state.side_effect = fake_storage_state
        auth_manager.save_auth("baidu", mock_context)

        domains = auth_manager.list_domains()
        baidu = next(d for d in domains if d["domain"] == "baidu")
        assert baidu["has_auth"] is True

    def test_empty_domains_dir(self, tmp_auth_dir, tmp_path):
        """Should return empty list when domains/ is empty."""
        empty_dir = tmp_path / "empty_domains"
        empty_dir.mkdir()
        am = AuthManager(auth_dir=tmp_auth_dir, domains_dir=empty_dir)
        assert am.list_domains() == []

    def test_nonexistent_domains_dir(self, tmp_auth_dir, tmp_path):
        """Should return empty list when domains/ doesn't exist."""
        am = AuthManager(auth_dir=tmp_auth_dir, domains_dir=tmp_path / "nope")
        assert am.list_domains() == []


# ---------------------------------------------------------------------------
# has_auth / load_auth
# ---------------------------------------------------------------------------


class TestHasAndLoadAuth:
    """Tests for has_auth() and load_auth()."""

    def test_has_auth_false_when_missing(self, auth_manager):
        assert auth_manager.has_auth("baidu") is False

    def test_has_auth_true_when_exists(self, auth_manager, tmp_auth_dir):
        # Manually create the auth file
        auth_file = tmp_auth_dir / "baidu.json"
        auth_file.write_text("{}", encoding="utf-8")
        assert auth_manager.has_auth("baidu") is True

    def test_load_auth_returns_none_when_missing(self, auth_manager):
        assert auth_manager.load_auth("baidu") is None

    def test_load_auth_returns_data_when_exists(self, auth_manager, tmp_auth_dir):
        """Should return the storage_state dict from the JSON file."""
        sample_data = {
            "cookies": [{"name": "token", "value": "abc123"}],
            "origins": [],
        }
        auth_file = tmp_auth_dir / "baidu.json"
        auth_file.write_text(json.dumps(sample_data), encoding="utf-8")

        result = auth_manager.load_auth("baidu")
        assert result == sample_data

    def test_load_auth_handles_corrupt_json(self, auth_manager, tmp_auth_dir):
        """Should return None for corrupt JSON files."""
        auth_file = tmp_auth_dir / "baidu.json"
        auth_file.write_text("not valid json {{{", encoding="utf-8")

        result = auth_manager.load_auth("baidu")
        assert result is None


# ---------------------------------------------------------------------------
# save_auth
# ---------------------------------------------------------------------------


class TestSaveAuth:
    """Tests for save_auth()."""

    def test_creates_auth_file(self, auth_manager, tmp_auth_dir):
        """Should create a JSON file via context.storage_state()."""
        mock_context = MagicMock()

        # Simulate storage_state writing a file
        def fake_storage_state(path):
            with open(path, "w") as f:
                json.dump({"cookies": [], "origins": []}, f)

        mock_context.storage_state.side_effect = fake_storage_state

        result_path = auth_manager.save_auth("baidu", mock_context)
        assert result_path.exists()
        assert result_path.name == "baidu.json"

    def test_creates_auth_dir_if_missing(self, tmp_path, tmp_domains_dir):
        """Should create auth dir if it doesn't exist."""
        auth_dir = tmp_path / "new_auth_dir"
        am = AuthManager(auth_dir=auth_dir, domains_dir=tmp_domains_dir)

        mock_context = MagicMock()

        def fake_storage_state(path):
            with open(path, "w") as f:
                json.dump({"cookies": []}, f)

        mock_context.storage_state.side_effect = fake_storage_state

        am.save_auth("baidu", mock_context)
        assert auth_dir.is_dir()


# ---------------------------------------------------------------------------
# delete_auth
# ---------------------------------------------------------------------------


class TestDeleteAuth:
    """Tests for delete_auth()."""

    def test_deletes_existing_file(self, auth_manager, tmp_auth_dir):
        auth_file = tmp_auth_dir / "baidu.json"
        auth_file.write_text("{}", encoding="utf-8")

        assert auth_manager.delete_auth("baidu") is True
        assert not auth_file.exists()

    def test_returns_false_when_missing(self, auth_manager):
        assert auth_manager.delete_auth("nonexistent") is False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """Tests for get_auth_manager / reset_auth_manager."""

    def teardown_method(self):
        reset_auth_manager()

    def test_returns_same_instance(self):
        a = get_auth_manager()
        b = get_auth_manager()
        assert a is b

    def test_reset_creates_new_instance(self):
        a = get_auth_manager()
        reset_auth_manager()
        b = get_auth_manager()
        assert a is not b
