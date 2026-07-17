"""
配置管理器 —— 支持首次运行引导和本地配置持久化。

配置文件位置: ~/.agentic-playwright/config.yaml
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# 默认配置
DEFAULT_CONFIG = {
    "vision": {
        "provider": "mimo",
        "api_key": "",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "model": "mimo-v2.5",
    },
    "browser": {
        "engine": "cloakbrowser",  # "playwright" | "cloakbrowser" | "local_chrome"
        "headless": False,
        "local_chrome": {
            "executable_path": "",  # Chrome 可执行文件路径（留空自动检测）
            "debug_port": 9222,     # CDP 远程调试端口
            "user_data_dir": "",    # 用户数据目录（留空使用独立 profile）
            "auto_launch": True,    # 是否自动启动 Chrome
        },
    },
}

# 配置文件路径
CONFIG_DIR = Path.home() / ".agentic-playwright"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


class ConfigManager:
    """配置管理器。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._path = Path(config_path) if config_path else CONFIG_FILE
        self._config: dict = {}
        self._load()

    def _load(self) -> None:
        """加载配置文件。"""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}
            except (yaml.YAMLError, OSError):
                self._config = {}
        else:
            self._config = {}

    def _save(self) -> None:
        """保存配置文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持点号分隔的嵌套键）。"""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def set(self, key: str, value: Any) -> None:
        """设置配置值（支持点号分隔的嵌套键）。"""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        self._save()

    def is_configured(self) -> bool:
        """检查是否已完成初始配置。"""
        api_key = self.get("vision.api_key", "")
        return bool(api_key and api_key.strip())

    def get_vision_config(self) -> dict:
        """获取视觉模块配置。"""
        return {
            "provider": self.get("vision.provider", "mimo"),
            "api_key": self.get("vision.api_key", ""),
            "base_url": self.get("vision.base_url", ""),
            "model": self.get("vision.model", "mimo-v2.5"),
        }

    def get_browser_config(self) -> dict:
        """获取浏览器配置。"""
        return {
            "engine": self.get("browser.engine", "cloakbrowser"),
            "headless": self.get("browser.headless", False),
            "local_chrome": self.get_local_chrome_config(),
        }

    def get_local_chrome_config(self) -> dict:
        """获取本地 Chrome 浏览器配置。"""
        return {
            "executable_path": self.get("browser.local_chrome.executable_path", ""),
            "debug_port": self.get("browser.local_chrome.debug_port", 9222),
            "user_data_dir": self.get("browser.local_chrome.user_data_dir", ""),
            "auto_launch": self.get("browser.local_chrome.auto_launch", True),
        }

    def setup_interactive(self) -> bool:
        """交互式配置引导。

        Returns:
            是否成功完成配置。
        """
        print()
        print("=" * 50)
        print("  Agentic Playwright MCP - 首次配置")
        print("=" * 50)
        print()

        # 1. 选择视觉模型提供商
        print("选择视觉模型提供商:")
        print("  1. mimo (默认，国内访问)")
        print("  2. anthropic (Claude)")
        print("  3. openai (GPT-4V)")
        print("  4. 跳过（不使用视觉功能）")
        print()

        choice = input("请选择 [1-4]: ").strip() or "1"

        provider_map = {"1": "mimo", "2": "anthropic", "3": "openai", "4": "skip"}
        provider = provider_map.get(choice, "mimo")

        if provider == "skip":
            self.set("vision.provider", "mimo")
            self.set("vision.api_key", "")
            print(
                "\n已跳过视觉配置。后续可通过编辑 ~/.agentic-playwright/config.yaml 添加。"
            )
        else:
            # 2. 输入 API Key
            print()
            api_key = input(f"请输入 {provider} API Key: ").strip()
            if not api_key:
                print("未输入 API Key，视觉功能将不可用。")
                api_key = ""

            # 3. 输入 Base URL（可选）
            default_urls = {
                "mimo": "https://token-plan-cn.xiaomimimo.com/v1",
                "anthropic": "https://api.anthropic.com",
                "openai": "https://api.openai.com/v1",
            }
            default_url = default_urls.get(provider, "")
            print()
            base_url = (
                input(f"请输入 Base URL [{default_url}]: ").strip() or default_url
            )

            # 4. 输入模型名（可选）
            default_models = {
                "mimo": "mimo-v2.5",
                "anthropic": "claude-sonnet-4-20250514",
                "openai": "gpt-4o",
            }
            default_model = default_models.get(provider, "")
            print()
            model = input(f"请输入模型名 [{default_model}]: ").strip() or default_model

            # 保存
            self.set("vision.provider", provider)
            self.set("vision.api_key", api_key)
            self.set("vision.base_url", base_url)
            self.set("vision.model", model)

            print(f"\n视觉配置已保存到 {self._path}")

        # 5. 浏览器配置
        print()
        print("浏览器引擎:")
        print("  1. CloakBrowser (默认，反检测)")
        print("  2. Playwright (标准)")
        print()

        choice = input("请选择 [1-2]: ").strip() or "1"
        engine = "cloakbrowser" if choice == "1" else "playwright"
        self.set("browser.engine", engine)

        # 6. 无头模式
        print()
        headless = input("是否使用无头模式？(y/N): ").strip().lower() == "y"
        self.set("browser.headless", headless)

        print()
        print("=" * 50)
        print("  配置完成！")
        print("=" * 50)
        print()
        print(f"配置文件: {self._path}")
        print(f"视觉提供商: {self.get('vision.provider')}")
        print(f"浏览器引擎: {self.get('browser.engine')}")
        print(f"无头模式: {self.get('browser.headless')}")
        print()

        return True

    def apply_to_env(self) -> None:
        """将配置应用到环境变量。"""
        vision = self.get_vision_config()

        os.environ["VISION_PROVIDER"] = vision["provider"]
        os.environ["VISION_BASE_URL"] = vision["base_url"]
        os.environ["VISION_MODEL"] = vision["model"]
        if vision["api_key"]:
            if vision["provider"] == "anthropic":
                os.environ["ANTHROPIC_API_KEY"] = vision["api_key"]
            elif vision["provider"] == "openai":
                os.environ["OPENAI_API_KEY"] = vision["api_key"]
            else:
                os.environ["VISION_API_KEY"] = vision["api_key"]

        browser = self.get_browser_config()
        os.environ["USE_CLOAKBROWSER"] = (
            "true" if browser["engine"] == "cloakbrowser" else "false"
        )
        os.environ["BROWSER_HEADLESS"] = "true" if browser["headless"] else "false"

        # 本地 Chrome 配置
        os.environ["BROWSER_ENGINE"] = browser["engine"]
        local_chrome = browser["local_chrome"]
        os.environ["LOCAL_CHROME_PATH"] = local_chrome["executable_path"]
        os.environ["LOCAL_CHROME_DEBUG_PORT"] = str(local_chrome["debug_port"])
        os.environ["LOCAL_CHROME_USER_DATA"] = local_chrome["user_data_dir"]
        os.environ["LOCAL_CHROME_AUTO_LAUNCH"] = (
            "true" if local_chrome["auto_launch"] else "false"
        )


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: ConfigManager | None = None


def get_config_manager(config_path: str | Path | None = None) -> ConfigManager:
    global _instance
    if _instance is None:
        _instance = ConfigManager(config_path=config_path)
    return _instance


def reset_config_manager() -> None:
    global _instance
    _instance = None
