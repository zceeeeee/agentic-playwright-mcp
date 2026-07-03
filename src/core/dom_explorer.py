"""Lightweight DOM explorer for text-first browser observation.

The explorer intentionally avoids screenshots and multimodal calls. It extracts a
small summary of visible interactive elements so planning can prefer rules, DOM,
and accessibility-like signals before any vision fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_DOM_EXPLORER_JS = r"""
(maxElements) => {
  const truncate = (value, limit = 80) => {
    value = (value || '').replace(/\s+/g, ' ').trim();
    return value.length > limit ? value.slice(0, limit - 1) + '…' : value;
  };

  const safeCssEscape = (value) => {
    if (window.CSS && typeof window.CSS.escape === 'function') {
      return window.CSS.escape(value);
    }
    return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  };

  const cssPath = (el) => {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return '';
    if (el.id) return `#${safeCssEscape(el.id)}`;

    const parts = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 4) {
      let part = current.tagName.toLowerCase();
      const testId = current.getAttribute('data-testid') || current.getAttribute('data-test-id');
      if (testId) {
        part += `[data-testid="${testId.replace(/"/g, '\\"')}"]`;
        parts.unshift(part);
        break;
      }
      const classes = Array.from(current.classList || [])
        .filter(Boolean)
        .slice(0, 2)
        .map((name) => `.${safeCssEscape(name)}`)
        .join('');
      if (classes) part += classes;

      const parent = current.parentElement;
      if (parent) {
        const sameTag = Array.from(parent.children).filter(
          (child) => child.tagName === current.tagName
        );
        if (sameTag.length > 1) {
          part += `:nth-of-type(${sameTag.indexOf(current) + 1})`;
        }
      }
      parts.unshift(part);
      current = parent;
    }
    return parts.join(' > ');
  };

  const isVisible = (el) => {
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    if (Number(style.opacity) === 0) return false;
    const rect = el.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return false;
    if (rect.bottom < 0 || rect.right < 0) return false;
    if (rect.top > window.innerHeight || rect.left > window.innerWidth) return false;
    return true;
  };

  const interactiveSelector = [
    'a[href]',
    'button',
    'input',
    'textarea',
    'select',
    'summary',
    'details',
    '[role]',
    '[tabindex]',
    '[contenteditable="true"]'
  ].join(',');

  const elements = [];
  const counts = {};
  const seen = new Set();
  const nodes = Array.from(document.querySelectorAll(interactiveSelector));

  for (const el of nodes) {
    if (elements.length >= maxElements) break;
    if (seen.has(el) || !isVisible(el)) continue;
    seen.add(el);

    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    const type = el.getAttribute('type') || '';
    const aria = el.getAttribute('aria-label') || '';
    const placeholder = el.getAttribute('placeholder') || '';
    const title = el.getAttribute('title') || '';
    const value = ['input', 'textarea'].includes(tag) ? el.value : '';
    const text = truncate(el.innerText || el.textContent || value || aria || placeholder || title);
    const disabled = Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true');
    if (disabled) continue;

    const kind = role || (type ? `${tag}:${type}` : tag);
    counts[kind] = (counts[kind] || 0) + 1;

    const rect = el.getBoundingClientRect();
    elements.push({
      tag,
      role,
      type,
      text,
      aria_label: truncate(aria),
      placeholder: truncate(placeholder),
      title: truncate(title),
      selector: cssPath(el),
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height)
    });
  }

  const hasModal = Boolean(document.querySelector('[aria-modal="true"], [role="dialog"], .modal, .Modal'));
  const hasDrawer = Boolean(document.querySelector('[class*="drawer" i], [class*="sheet" i]'));
  const hasDropdown = Boolean(document.querySelector('[role="menu"], [role="listbox"], [class*="dropdown" i]'));
  const canvasCount = document.querySelectorAll('canvas').length;
  const svgCount = document.querySelectorAll('svg').length;

  return {
    elements,
    counts,
    state: { hasModal, hasDrawer, hasDropdown, canvasCount, svgCount }
  };
}
"""


@dataclass
class InteractiveElement:
    """Small, serializable description of an interactive DOM element."""

    tag: str = ""
    role: str = ""
    type: str = ""
    text: str = ""
    aria_label: str = ""
    placeholder: str = ""
    title: str = ""
    selector: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    @property
    def label(self) -> str:
        return self.text or self.aria_label or self.placeholder or self.title

    @property
    def kind(self) -> str:
        if self.role:
            return self.role
        if self.type:
            return f"{self.tag}:{self.type}"
        return self.tag


@dataclass
class DomPageSummary:
    """Program-generated page summary used before LLM or vision analysis."""

    url: str = ""
    title: str = ""
    elements: list[InteractiveElement] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    has_modal: bool = False
    has_drawer: bool = False
    has_dropdown: bool = False
    canvas_count: int = 0
    svg_count: int = 0

    @property
    def interactive_count(self) -> int:
        return len(self.elements)

    def to_text(self, max_elements: int = 12) -> str:
        lines = [
            f"页面标题: {self.title or '(无标题)'}",
            f"当前 URL: {self.url or '(未知)'}",
            f"可交互元素: {self.interactive_count}",
        ]

        if self.counts:
            counts = ", ".join(
                f"{key}={value}" for key, value in sorted(self.counts.items())
            )
            lines[-1] += f" ({counts})"

        state_flags = []
        if self.has_modal:
            state_flags.append("Modal")
        if self.has_drawer:
            state_flags.append("Drawer")
        if self.has_dropdown:
            state_flags.append("Dropdown")
        if self.canvas_count:
            state_flags.append(f"Canvas={self.canvas_count}")
        if self.svg_count:
            state_flags.append(f"SVG={self.svg_count}")
        if state_flags:
            lines.append("页面状态: " + ", ".join(state_flags))

        if self.elements:
            lines.append("候选元素:")
            for index, element in enumerate(self.elements[:max_elements], start=1):
                label = element.label or "(无文本)"
                selector = f" selector={element.selector}" if element.selector else ""
                lines.append(f"{index}. {element.kind} text={label!r}{selector}")

        return "\n".join(lines)


def summarize_page(page: Any, max_elements: int = 30) -> DomPageSummary:
    """Return a compact DOM summary for a Playwright page-like object."""

    summary = DomPageSummary()
    try:
        summary.url = str(getattr(page, "url", "") or "")
    except Exception:
        summary.url = ""

    try:
        summary.title = str(page.title() or "")
    except Exception:
        summary.title = ""

    try:
        raw = page.evaluate(_DOM_EXPLORER_JS, max_elements)
    except Exception:
        raw = {}

    if not isinstance(raw, dict):
        return summary

    raw_elements = raw.get("elements", [])
    if not isinstance(raw_elements, list):
        raw_elements = []

    for item in raw_elements:
        if not isinstance(item, dict):
            continue
        summary.elements.append(
            InteractiveElement(
                tag=str(item.get("tag", "") or ""),
                role=str(item.get("role", "") or ""),
                type=str(item.get("type", "") or ""),
                text=str(item.get("text", "") or ""),
                aria_label=str(item.get("aria_label", "") or ""),
                placeholder=str(item.get("placeholder", "") or ""),
                title=str(item.get("title", "") or ""),
                selector=str(item.get("selector", "") or ""),
                x=_to_int(item.get("x")),
                y=_to_int(item.get("y")),
                width=_to_int(item.get("width")),
                height=_to_int(item.get("height")),
            )
        )

    counts = raw.get("counts", {})
    if isinstance(counts, dict):
        summary.counts = {
            str(key): _to_int(value)
            for key, value in counts.items()
            if _to_int(value) > 0
        }

    state = raw.get("state", {})
    if isinstance(state, dict):
        summary.has_modal = bool(state.get("hasModal"))
        summary.has_drawer = bool(state.get("hasDrawer"))
        summary.has_dropdown = bool(state.get("hasDropdown"))
        summary.canvas_count = _to_int(state.get("canvasCount"))
        summary.svg_count = _to_int(state.get("svgCount"))

    return summary


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
