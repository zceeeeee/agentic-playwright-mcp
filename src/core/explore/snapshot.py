"""ARIA snapshot generator for Explore mode."""

from __future__ import annotations

import re
import time
from typing import Any

from src.logging import get_logger

from .models import AriaNode, FocusTarget, SnapshotMode, SnapshotResponse
from .ref_generator import RefGenerator

logger = get_logger(__name__)


_ARIA_EXTRACTION_JS_FALLBACK = r"""
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
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
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
    if (el.hasAttribute('contenteditable')) return 'textbox';
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'nav') return 'navigation';
    if (tag === 'main') return 'main';
    if (tag === 'header') return 'banner';
    if (tag === 'footer') return 'contentinfo';
    if (tag === 'article') return 'article';
    if (tag === 'section') return 'region';
    const cls = (el.className || '').toString().toLowerCase();
    if (/\bbtn\b/.test(cls) || /\bbutton\b/.test(cls)) return 'button';
    if (/\binput\b/.test(cls) && tag === 'div') return 'textbox';
    if (/\beditor\b/.test(cls) || /\bcomposer\b/.test(cls) || /\bchat-input\b/.test(cls)) return 'textbox';
    return 'generic';
  };
  const isVisible = (el) => {
    if (el.nodeType !== Node.ELEMENT_NODE) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    if (Number(style.opacity) === 0) return false;
    if (style.display === 'contents') return true;
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
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) return truncate(ariaLabel);
    const title = el.getAttribute('title');
    if (title) return truncate(title);
    const alt = el.getAttribute('alt');
    if (alt) return truncate(alt);
    if (el.id) {
      const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label) return truncate(label.innerText || label.textContent || '');
    }
    const parentLabel = el.closest('label');
    if (parentLabel) return truncate(parentLabel.innerText || parentLabel.textContent || '');
    const placeholder = el.getAttribute('placeholder');
    if (placeholder) return truncate(placeholder);
    if (el.tagName === 'INPUT') {
      const value = el.getAttribute('value');
      if (value) return truncate(value);
    }
    const svgTitle = el.querySelector('title');
    if (svgTitle) return truncate(svgTitle.textContent || '');
    return truncate(el.innerText || el.textContent || '');
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

    // Shadow DOM penetration
    if (el.shadowRoot) {
      for (const child of Array.from(el.shadowRoot.children)) {
        const childNode = walk(child, depth + 1, nextContext);
        if (childNode) node.children.push(childNode);
      }
    }

    for (const child of Array.from(el.children || [])) {
      const childNode = walk(child, depth + 1, nextContext);
      if (childNode) node.children.push(childNode);
    }
    return node;
  };
  return walk(root);
}
"""

# Deep scan JS — 更激进的元素检测，用于标准快照交互元素过少时的 fallback
_ARIA_DEEP_SCAN_JS = r"""
(options) => {
  const maxElements = Math.max(1, Number(options?.maxElements || 150));
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
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
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
    if (el.hasAttribute('contenteditable')) return 'textbox';
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'nav') return 'navigation';
    if (tag === 'main') return 'main';
    if (tag === 'header') return 'banner';
    if (tag === 'footer') return 'contentinfo';
    if (tag === 'article') return 'article';
    if (tag === 'section') return 'region';
    const cls = (el.className || '').toString().toLowerCase();
    if (/\bbtn\b/.test(cls) || /\bbutton\b/.test(cls)) return 'button';
    if (/\binput\b/.test(cls) && tag === 'div') return 'textbox';
    if (/\beditor\b/.test(cls) || /\bcomposer\b/.test(cls) || /\bchat-input\b/.test(cls)) return 'textbox';
    // Deep scan: 检测更多非标准交互元素
    if (tag === 'div' || tag === 'span') {
      // 检测可聚焦元素
      const tabindex = el.getAttribute('tabindex');
      if (tabindex && tabindex !== '-1') return 'button';
      // 检测带事件处理器的元素
      if (el.hasAttribute('onclick') || el.hasAttribute('onmousedown') || el.hasAttribute('onkeydown')) return 'button';
      // 检测常见输入类名
      if (/\bsearch\b/.test(cls) || /\bquery\b/.test(cls)) return 'searchbox';
      if (/\bchat\b/.test(cls) || /\bmessage\b/.test(cls) || /\btextarea\b/.test(cls)) return 'textbox';
      if (/\bdropdown\b/.test(cls) || /\bselect\b/.test(cls)) return 'combobox';
      if (/\btab\b/.test(cls)) return 'tab';
      if (/\bmenu\b/.test(cls)) return 'menu';
      if (/\bcheckbox\b/.test(cls)) return 'checkbox';
      if (/\bswitch\b/.test(cls) || /\btoggle\b/.test(cls)) return 'switch';
      // 检测 contenteditable 的父容器中包含的可编辑区域
      if (el.getAttribute('contenteditable') === 'true' || el.getAttribute('contenteditable') === '') return 'textbox';
      // 检测常见的聊天/编辑器容器
      if (/\bql-editor\b/.test(cls) || /\bProseMirror\b/.test(cls) || /\bDraftjs\b/.test(cls)) return 'textbox';
    }
    return 'generic';
  };
  const isVisible = (el) => {
    if (el.nodeType !== Node.ELEMENT_NODE) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    if (Number(style.opacity) === 0) return false;
    if (style.display === 'contents') return true;
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
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) return truncate(ariaLabel);
    const title = el.getAttribute('title');
    if (title) return truncate(title);
    const alt = el.getAttribute('alt');
    if (alt) return truncate(alt);
    if (el.id) {
      const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label) return truncate(label.innerText || label.textContent || '');
    }
    const parentLabel = el.closest('label');
    if (parentLabel) return truncate(parentLabel.innerText || parentLabel.textContent || '');
    const placeholder = el.getAttribute('placeholder');
    if (placeholder) return truncate(placeholder);
    if (el.tagName === 'INPUT') {
      const value = el.getAttribute('value');
      if (value) return truncate(value);
    }
    const svgTitle = el.querySelector('title');
    if (svgTitle) return truncate(svgTitle.textContent || '');
    return truncate(el.innerText || el.textContent || '');
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

  // Deep scan: 使用更宽松的 walk 函数，通过改进的 implicitRole 检测更多交互元素
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

    // Shadow DOM penetration
    if (el.shadowRoot) {
      for (const child of Array.from(el.shadowRoot.children)) {
        const childNode = walk(child, depth + 1, nextContext);
        if (childNode) node.children.push(childNode);
      }
    }

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
        self._ref_gen = RefGenerator()  # kept for fallback
        self._version_counter = 0
        # native aria_snapshot API 不提供 CSS selector，导致 ref 无法同步到 DOM
        # 暂时使用 custom JS 方法，它会生成正确的 selector 并添加 data-explore-ref 属性
        self._use_native = False
        self._min_interactive_threshold = getattr(config, "min_interactive_threshold", 5)
        self._deep_scan_max_elements = getattr(config, "deep_scan_max_elements", 150)

    def snapshot(
        self,
        page: Any,
        mode: SnapshotMode = SnapshotMode.COMPACT,
        focus: FocusTarget | None = None,
    ) -> SnapshotResponse:
        start = time.time()
        self._version_counter += 1
        version = f"snapshot_v{self._version_counter}"

        raw_tree = self._extract_aria_tree(page, focus)
        nodes = self._build_nodes(raw_tree, mode)

        # If native API didn't produce refs (fallback case), use RefGenerator
        if not self._has_any_ref(nodes):
            self._ref_gen.reset()
            self._ref_gen.assign_refs(nodes)

        self._sync_refs_to_dom(page, nodes)
        interactive_count = self._count_interactive(nodes)
        state = self._detect_page_state(page)

        duration_ms = int((time.time() - start) * 1000)
        url = str(getattr(page, "url", "") or "")
        logger.debug(
            "Explore 快照生成完成: version=%s url=%s interactive_count=%d mode=%s (耗时 %dms)",
            version, url, interactive_count, mode.value, duration_ms,
        )

        return SnapshotResponse(
            version=version,
            mode=mode,
            url=url,
            title=self._page_title(page),
            nodes=nodes,
            interactive_count=interactive_count,
            has_modal=state.get("has_modal", False),
        )

    def _extract_aria_tree(self, page: Any, focus: FocusTarget | None = None) -> dict:
        if self._use_native:
            try:
                result = self._extract_via_native(page, focus)
                if result:
                    return result
                # Empty result from native API — try fallback
            except (AttributeError, TypeError, Exception) as exc:
                import logging

                logging.getLogger(__name__).warning(
                    "aria_snapshot() failed, falling back: %s", exc
                )
        return self._extract_via_custom_js(page, focus)

    def _extract_via_native(self, page: Any, focus: FocusTarget | None = None) -> dict:
        """Use Playwright native aria_snapshot to extract semantic tree."""
        locator = page.locator("body")

        # Handle focus targeting
        if focus:
            if focus.type == "ref":
                locator = page.locator(f'[data-explore-ref="{focus.value}"]')
            elif focus.type == "role_name":
                role, name = focus.value.split(":", 1)
                locator = page.get_by_role(role, name=name)

        yaml_text = locator.aria_snapshot(mode="full", boxes=True)
        tree = self._parse_aria_yaml(yaml_text)
        # If native API returned no children, signal empty so fallback can try
        if not tree.get("children"):
            return {}
        return tree

    def _extract_via_custom_js(self, page: Any, focus: FocusTarget | None = None) -> dict:
        """Fallback: use custom JS for ARIA extraction."""
        options = {
            "maxElements": getattr(self._config, "snapshot_max_elements", 50),
            "focus": focus.model_dump() if focus else None,
        }
        try:
            raw = page.evaluate(_ARIA_EXTRACTION_JS_FALLBACK, options)
        except TypeError:
            raw = page.evaluate(_ARIA_EXTRACTION_JS_FALLBACK)
        except Exception:
            raw = {}
        return raw if isinstance(raw, dict) else {}

    def _deep_scan(self, page: Any, mode: SnapshotMode, focus: FocusTarget | None = None) -> list[AriaNode]:
        """当标准快照交互元素过少时，使用更激进的 JS 扫描提取更多可交互元素。"""
        raw_tree = self._extract_via_deep_js(page, focus)
        nodes = self._build_nodes(raw_tree, mode)
        if not self._has_any_ref(nodes):
            self._ref_gen.reset()
            self._ref_gen.assign_refs(nodes)
        return nodes

    def force_deep_scan(
        self,
        page: Any,
        mode: SnapshotMode = SnapshotMode.COMPACT,
        focus: FocusTarget | None = None,
    ) -> SnapshotResponse:
        """强制执行深度扫描，忽略交互元素阈值。供 request_deep_scan 动作调用。"""
        start = time.time()
        self._version_counter += 1
        version = f"snapshot_v{self._version_counter}"

        raw_tree = self._extract_via_deep_js(page, focus)
        nodes = self._build_nodes(raw_tree, mode)

        if not self._has_any_ref(nodes):
            self._ref_gen.reset()
            self._ref_gen.assign_refs(nodes)

        self._sync_refs_to_dom(page, nodes)
        interactive_count = self._count_interactive(nodes)
        state = self._detect_page_state(page)

        duration_ms = int((time.time() - start) * 1000)
        url = str(getattr(page, "url", "") or "")
        logger.info(
            "Explore 深度扫描完成: version=%s url=%s interactive_count=%d (耗时 %dms)",
            version, url, interactive_count, duration_ms,
        )

        return SnapshotResponse(
            version=version,
            mode=mode,
            url=url,
            title=self._page_title(page),
            nodes=nodes,
            interactive_count=interactive_count,
            has_modal=state.get("has_modal", False),
            deep_scanned=True,
        )

    def _extract_via_deep_js(self, page: Any, focus: FocusTarget | None = None) -> dict:
        """深度扫描：使用更激进的 JS 提取更多可交互元素。"""
        options = {
            "maxElements": self._deep_scan_max_elements,
            "focus": focus.model_dump() if focus else None,
        }
        try:
            raw = page.evaluate(_ARIA_DEEP_SCAN_JS, options)
        except TypeError:
            raw = page.evaluate(_ARIA_DEEP_SCAN_JS)
        except Exception:
            raw = {}
        return raw if isinstance(raw, dict) else {}

    # ------------------------------------------------------------------
    # YAML parser for Playwright native aria_snapshot output
    # ------------------------------------------------------------------

    # Regex patterns for YAML line parsing
    _YAML_LINE_RE = re.compile(
        r"^(\s*)- "  # indentation + list marker
        r"(?:(\w[\w\s]*?)(?:\s+\"([^\"]*)\")?(?:\s+\[([^\]]*)\])?\s*(:?\s*$))"  # role "name" [attrs]
        r"|"
        r"^(\s*)- (text):\s*(.*)"  # - text: content
        r"|"
        r"^(\s*)- (/(\w+)):\s*(.*)"  # - /url: value
    )

    _YAML_NODE_RE = re.compile(
        r"^(\s*)- "
        r"(\w[\w\s]*?)"  # role
        r"(?:\s+\"([^\"]*)\")?"  # optional quoted name
        r"(\s+\[[^\]]*\])*"  # zero or more [attr] blocks
        r"\s*:?\s*$"
    )

    _YAML_TEXT_RE = re.compile(r"^(\s*)- text:\s*(.*)")
    _YAML_PROP_RE = re.compile(r"^(\s*)- /(\w+):\s*(.*)")

    @classmethod
    def _parse_aria_yaml(cls, yaml_text: str) -> dict:
        """Parse Playwright aria_snapshot YAML into an AriaNode-compatible dict tree."""
        lines = yaml_text.strip().split("\n")
        if not lines:
            return {"role": "generic", "name": "", "children": []}

        # Root node
        root: dict[str, Any] = {
            "role": "generic",
            "name": "",
            "tag": None,
            "selector": None,
            "placeholder": None,
            "disabled": False,
            "level": None,
            "context": "",
            "children": [],
        }

        # Stack of (indent_level, node_dict)
        stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

        for line in lines:
            if not line.strip():
                continue

            # Calculate indent level (2 spaces per level)
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            # Try text node: - text: content
            text_match = cls._YAML_TEXT_RE.match(line)
            if text_match:
                text_content = text_match.group(2).strip()
                # Find parent based on indent
                while len(stack) > 1 and stack[-1][0] >= indent:
                    stack.pop()
                if stack:
                    parent = stack[-1][1]
                    # Append text to parent's name
                    existing = parent.get("name", "")
                    if existing:
                        parent["name"] = f"{existing} {text_content}"
                    else:
                        parent["name"] = text_content
                continue

            # Try property node: - /url: value
            prop_match = cls._YAML_PROP_RE.match(line)
            if prop_match:
                prop_name = prop_match.group(2)
                prop_value = prop_match.group(3).strip().strip('"')
                while len(stack) > 1 and stack[-1][0] >= indent:
                    stack.pop()
                if stack:
                    parent = stack[-1][1]
                    # Store as a child dict with special role
                    parent["children"].append({
                        "role": f"__{prop_name}",
                        "name": prop_value,
                        "tag": None,
                        "selector": None,
                        "placeholder": None,
                        "disabled": False,
                        "level": None,
                        "context": "",
                        "children": [],
                    })
                continue

            # Try regular node: - role "name" [attrs]
            node_match = cls._YAML_NODE_RE.match(line)
            if node_match:
                role = node_match.group(2).strip() if node_match.group(2) else "generic"
                name = node_match.group(3) or ""

                # Parse attributes from [bracketed] blocks in the line
                attrs = cls._parse_attrs_from_line(line)
                ref = attrs.get("ref")
                disabled = bool(attrs.get("disabled"))
                level = None
                if "level" in attrs:
                    try:
                        level = int(attrs["level"])
                    except (ValueError, TypeError):
                        pass
                checked = bool(attrs.get("checked"))

                node: dict[str, Any] = {
                    "role": role,
                    "name": name,
                    "ref": ref,
                    "tag": None,
                    "selector": None,
                    "placeholder": None,
                    "disabled": disabled,
                    "level": level,
                    "context": "",
                    "children": [],
                }
                if checked:
                    node["checked"] = True

                # Pop stack until we find the parent (indent less than current)
                while len(stack) > 1 and stack[-1][0] >= indent:
                    stack.pop()

                # Add as child of current top of stack
                stack[-1][1]["children"].append(node)
                stack.append((indent, node))
                continue

        return root

    @staticmethod
    def _parse_attrs_from_line(line: str) -> dict[str, Any]:
        """Extract attributes from all [attr] blocks in a YAML line."""
        attrs: dict[str, Any] = {}
        for match in re.finditer(r"\[([^\]]+)\]", line):
            attr = match.group(1).strip()
            if "=" in attr:
                key, val = attr.split("=", 1)
                attrs[key.strip()] = val.strip()
            else:
                attrs[attr] = True
        return attrs

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

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
            ref=raw.get("ref"),
            tag=raw.get("tag"),
            selector=raw.get("selector"),
            placeholder=raw.get("placeholder"),
            disabled=bool(raw.get("disabled", False)),
            level=raw.get("level"),
            context=raw.get("context"),
            children=children,
        )

    def _has_any_ref(self, nodes: list[AriaNode]) -> bool:
        """Check if any node in the tree has a ref assigned."""
        for node in nodes:
            if node.ref:
                return True
            if self._has_any_ref(node.children):
                return True
        return False

    def _filter_compact(self, nodes: list[AriaNode]) -> list[AriaNode]:
        result = []
        for node in nodes:
            filtered_children = self._filter_compact(node.children)
            if node.role in self.COMPACT_INTERACTIVE_ROLES or filtered_children:
                result.append(
                    AriaNode(
                        role=node.role,
                        name=node.name,
                        ref=node.ref,
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
