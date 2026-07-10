"""Compatibility API for desktop-owned user interaction.

No UI is injected into browser pages. Existing ``panel_*`` script helpers are
routed to the desktop chat and confirmation broker.
"""

from src.panel.panel_manager import PanelManager, get_panel_manager

__all__ = ["PanelManager", "get_panel_manager"]
