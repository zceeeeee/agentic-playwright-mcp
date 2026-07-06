"""Explore ref generator."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AriaNode


class RefGenerator:
    """Assign refs to interactive ARIA nodes."""

    INTERACTIVE_ROLES: set[str] = {
        "button",
        "link",
        "textbox",
        "searchbox",
        "checkbox",
        "radio",
        "combobox",
        "listbox",
        "menu",
        "menuitem",
        "tab",
        "switch",
        "slider",
        "spinbutton",
        "option",
        "treeitem",
    }

    def __init__(self) -> None:
        self._counter = 0

    def reset(self) -> None:
        self._counter = 0

    def generate(self, role: str) -> str | None:
        if role not in self.INTERACTIVE_ROLES:
            return None
        self._counter += 1
        return f"e{self._counter}"

    def assign_refs(self, nodes: list["AriaNode"]) -> None:
        for node in nodes:
            ref = self.generate(node.role)
            if ref:
                node.ref = ref
            if node.children:
                self.assign_refs(node.children)
