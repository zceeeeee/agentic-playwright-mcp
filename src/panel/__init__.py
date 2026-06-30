"""
Layer 0: Interactive Panel — 浏览器内用户交互面板。

通过 BrowserContext.addInitScript 注入 Shadow DOM 面板，
提供输入框、按钮、日志区等交互元素，供用户与自动化程序通信。
"""

from src.panel.panel_manager import PanelManager, get_panel_manager

__all__ = ["PanelManager", "get_panel_manager"]
