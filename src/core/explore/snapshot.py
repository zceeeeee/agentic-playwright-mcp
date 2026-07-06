"""ARIA snapshot generator for Explore mode."""

from __future__ import annotations

from typing import Any

from .models import AriaNode, FocusTarget, SnapshotMode, SnapshotResponse
from .ref_generator import RefGenerator


_ARIA_EXTRACTION_JS = r"""
(options) => {
  const maxElements = Math.max(1, Number(options?.maxElements || 50));
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
    while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 5) {
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
        if (sameTag.length > 1) part += `:nth-of-type(${sameTag.indexOf(current) + 1})`;
      }
      parts.unshift(part);
      current = parent;
    }
    return parts.join(' > ');
  };
  const implicitRole = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'combobox';
    if (tag === 'input') {
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'search') return 'searchbox';
      if (type === 'range') return 'slider';
      if (type === 'number') return 'spinbutton';
      return 'textbox';
    }
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'nav') return 'navigation';
    if (tag === 'main') return 'main';
    if (tag === 'header') return 'banner';
    if (tag === 'footer') return 'contentinfo';
    if (tag === 'article') return 'article';
    if (tag === 'section') return 'region';
    return 'generic';
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
  const accessibleName = (el) => {
    const ariaLabelledBy = el.getAttribute('aria-labelledby');
    if (ariaLabelledBy) {
      const labelled = ariaLabelledBy
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.innerText || document.getElementById(id)?.textContent || '')
        .join(' ');
      if (labelled.trim()) return truncate(labelled);
    }
    return truncate(
      el.getAttribute('aria-label') ||
      el.getAttribute('title') ||
      el.getAttribute('alt') ||
      el.getAttribute('placeholder') ||
      el.innerText ||
      el.textContent ||
      ''
    );
  };
  const focus = options?.focus || null;
  let root = document.body;
  if (focus && focus.type === 'role_name') {
    const [role, ...nameParts] = String(focus.value || '').split(':');
    const name = nameParts.join(':');
    const found = Array.from(document.querySelectorAll('*')).find((el) => {
      const elRole = el.getAttribute('role') || implicitRole(el);
      return elRole === role && accessibleName(el).includes(name);
    });
    if (found) root = found;
  }

  let interactiveSeen = 0;
  const walk = (el, depth = 0, context = '') => {
    if (!el || depth > 10 || !isVisible(el)) return null;
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || implicitRole(el);
    const name = accessibleName(el);
    const isInteractive = [
      'button', 'link', 'textbox', 'searchbox', 'checkbox', 'radio',
      'combobox', 'listbox', 'menu', 'menuitem', 'tab', 'switch',
      'slider', 'spinbutton', 'option', 'treeitem'
    ].includes(role);
    if (isInteractive) {
      interactiveSeen += 1;
      if (interactiveSeen > maxElements) return null;
    }
    const node = {
      role,
      name,
      tag,
      selector: cssPath(el),
      placeholder: el.getAttribute('placeholder') || null,
      disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
      level: role === 'heading' && /^h[1-6]$/.test(tag) ? Number(tag.slice(1)) : null,
      context,
      children: []
    };
    const nextContext = name || context;
    for (const child of Array.from(el.children || [])) {
      const childNode = walk(child, depth + 1, nextContext);
      if (childNode) node.children.push(childNode);
    }
    return node;
  };
  return walk(root);
}
"""


class SnapshotGenerator:
    """Generate compact or full ARIA snapshots from a Playwright page."""

    COMPACT_INTERACTIVE_ROLES: set[str] = {
        "button",
        "link",
        "textbox",
        "searchbox",
        "checkbox",
        "radio",
        "combobox",
        "listbox",
        "menuitem",
        "tab",
        "slider",
        "spinbutton",
    }

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._ref_gen = RefGenerator()
        self._version_counter = 0

    def snapshot(
        self,
        page: Any,
        mode: SnapshotMode = SnapshotMode.COMPACT,
        focus: FocusTarget | None = None,
    ) -> SnapshotResponse:
        self._version_counter += 1
        version = f"snapshot_v{self._version_counter}"
        self._ref_gen.reset()

        raw_tree = self._extract_aria_tree(page, focus)
        nodes = self._build_nodes(raw_tree, mode)
        self._ref_gen.assign_refs(nodes)
        self._sync_refs_to_dom(page, nodes)
        interactive_count = self._count_interactive(nodes)
        state = self._detect_page_state(page)

        return SnapshotResponse(
            version=version,
            mode=mode,
            url=str(getattr(page, "url", "") or ""),
            title=self._page_title(page),
            nodes=nodes,
            interactive_count=interactive_count,
            has_modal=state.get("has_modal", False),
        )

    def _extract_aria_tree(self, page: Any, focus: FocusTarget | None = None) -> dict:
        options = {
            "maxElements": getattr(self._config, "snapshot_max_elements", 50),
            "focus": focus.model_dump() if focus else None,
        }
        try:
            raw = page.evaluate(_ARIA_EXTRACTION_JS, options)
        except TypeError:
            raw = page.evaluate(_ARIA_EXTRACTION_JS)
        except Exception:
            raw = {}
        return raw if isinstance(raw, dict) else {}

    def _build_nodes(self, raw_tree: dict, mode: SnapshotMode) -> list[AriaNode]:
        if not raw_tree:
            return []
        node = self._raw_to_node(raw_tree)
        if not node:
            return []
        if mode == SnapshotMode.COMPACT:
            return self._filter_compact([node])
        return [node]

    def _raw_to_node(self, raw: dict) -> AriaNode | None:
        if not raw or not isinstance(raw, dict):
            return None
        children = []
        for child in raw.get("children", []):
            child_node = self._raw_to_node(child)
            if child_node:
                children.append(child_node)
        return AriaNode(
            role=str(raw.get("role") or "generic"),
            name=str(raw.get("name") or ""),
            tag=raw.get("tag"),
            selector=raw.get("selector"),
            placeholder=raw.get("placeholder"),
            disabled=bool(raw.get("disabled", False)),
            level=raw.get("level"),
            context=raw.get("context"),
            children=children,
        )

    def _filter_compact(self, nodes: list[AriaNode]) -> list[AriaNode]:
        result = []
        for node in nodes:
            filtered_children = self._filter_compact(node.children)
            if node.role in self.COMPACT_INTERACTIVE_ROLES or filtered_children:
                result.append(
                    AriaNode(
                        role=node.role,
                        name=node.name,
                        tag=node.tag,
                        selector=node.selector,
                        placeholder=node.placeholder,
                        disabled=node.disabled,
                        level=node.level,
                        context=node.context,
                        children=filtered_children,
                    )
                )
        return result

    def _count_interactive(self, nodes: list[AriaNode]) -> int:
        count = 0
        for node in nodes:
            if node.ref:
                count += 1
            count += self._count_interactive(node.children)
        return count

    def _detect_page_state(self, page: Any) -> dict[str, bool]:
        js = """
        () => ({
          has_modal: Boolean(document.querySelector('[aria-modal="true"], [role="dialog"], .modal, .Modal'))
        })
        """
        try:
            state = page.evaluate(js)
        except Exception:
            state = {}
        return state if isinstance(state, dict) else {}

    def _sync_refs_to_dom(self, page: Any, nodes: list[AriaNode]) -> None:
        for node in self._iter_nodes(nodes):
            if not node.ref or not node.selector:
                continue
            try:
                page.locator(node.selector).first.evaluate(
                    "(el, ref) => el.setAttribute('data-explore-ref', ref)",
                    node.ref,
                )
            except Exception:
                continue

    def _iter_nodes(self, nodes: list[AriaNode]):
        for node in nodes:
            yield node
            yield from self._iter_nodes(node.children)

    @staticmethod
    def _page_title(page: Any) -> str:
        try:
            return str(page.title() or "")
        except Exception:
            return ""
