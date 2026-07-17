"""Tests for config_manager — configuration management."""

from __future__ import annotations

import pytest

from src.config_manager import ConfigManager, get_config_manager, reset_config_manager


@pytest.fixture
def config(tmp_path):
    return ConfigManager(config_path=tmp_path / "config.yaml")


# ---------------------------------------------------------------------------
# Basic operations
# ---------------------------------------------------------------------------


class TestBasicOperations:
    def test_get_default(self, config):
        assert config.get("vision.api_key", "") == ""

    def test_set_and_get(self, config):
        config.set("vision.api_key", "test-key")
        assert config.get("vision.api_key") == "test-key"

    def test_nested_set(self, config):
        config.set("vision.provider", "anthropic")
        config.set("vision.api_key", "sk-xxx")
        assert config.get("vision.provider") == "anthropic"
        assert config.get("vision.api_key") == "sk-xxx"

    def test_persistence(self, tmp_path):
        path = tmp_path / "config.yaml"
        c1 = ConfigManager(config_path=path)
        c1.set("vision.api_key", "test-key")

        c2 = ConfigManager(config_path=path)
        assert c2.get("vision.api_key") == "test-key"


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------


class TestIsConfigured:
    def test_not_configured(self, config):
        assert config.is_configured() is False

    def test_configured(self, config):
        config.set("vision.api_key", "test-key")
        assert config.is_configured() is True


# ---------------------------------------------------------------------------
# Getters
# ---------------------------------------------------------------------------


class TestGetters:
    def test_get_vision_config(self, config):
        config.set("vision.provider", "mimo")
        config.set("vision.api_key", "test-key")
        config.set("vision.base_url", "https://example.com/v1")
        config.set("vision.model", "mimo-v2.5")

        vision = config.get_vision_config()
        assert vision["provider"] == "mimo"
        assert vision["api_key"] == "test-key"
        assert vision["base_url"] == "https://example.com/v1"
        assert vision["model"] == "mimo-v2.5"

    def test_get_browser_config(self, config):
        config.set("browser.engine", "playwright")
        config.set("browser.headless", True)

        browser = config.get_browser_config()
        assert browser["engine"] == "playwright"
        assert browser["headless"] is True

    def test_defaults(self, config):
        vision = config.get_vision_config()
        assert vision["provider"] == "mimo"
        assert vision["model"] == "mimo-v2.5"

        browser = config.get_browser_config()
        assert browser["engine"] == "cloakbrowser"
        assert browser["headless"] is False


# ---------------------------------------------------------------------------
# apply_to_env
# ---------------------------------------------------------------------------


class TestApplyToEnv:
    def test_apply_anthropic(self, config):
        config.set("vision.provider", "anthropic")
        config.set("vision.api_key", "sk-xxx")
        config.set("browser.engine", "playwright")

        config.apply_to_env()
        import os

        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-xxx"
        assert os.environ.get("USE_CLOAKBROWSER") == "false"

    def test_apply_mimo(self, config):
        config.set("vision.provider", "mimo")
        config.set("vision.api_key", "tp-xxx")
        config.set("browser.engine", "cloakbrowser")

        config.apply_to_env()
        import os

        assert os.environ.get("VISION_API_KEY") == "tp-xxx"
        assert os.environ.get("USE_CLOAKBROWSER") == "true"

    def test_apply_local_chrome(self, config):
        config.set("browser.engine", "local_chrome")
        config.set("browser.local_chrome.debug_port", 9333)
        config.set("browser.local_chrome.user_data_dir", "D:/feather-profile")

        config.apply_to_env()

        assert os.environ.get("BROWSER_ENGINE") == "local_chrome"
        assert os.environ.get("USE_CLOAKBROWSER") == "false"
        assert os.environ.get("LOCAL_CHROME_DEBUG_PORT") == "9333"
        assert os.environ.get("LOCAL_CHROME_USER_DATA") == "D:/feather-profile"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def teardown_method(self):
        reset_config_manager()

    def test_singleton(self, tmp_path):
        c1 = get_config_manager(config_path=tmp_path / "config.yaml")
        c2 = get_config_manager()
        assert c1 is c2

    def test_reset(self, tmp_path):
        c1 = get_config_manager(config_path=tmp_path / "config.yaml")
        reset_config_manager()
        c2 = get_config_manager(config_path=tmp_path / "config.yaml")
        assert c1 is not c2
