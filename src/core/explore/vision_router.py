"""Budgeted visual fallback for Explore snapshots.

Visual model output is treated as untrusted perception data. It is normalized
to viewport-relative targets and never executed directly by this module.
"""

from __future__ import annotations

import os
from typing import Any

from src.logging import get_logger

from .models import (
    ExploreConfig,
    ScreenshotMeta,
    SnapshotResponse,
    SurfaceStats,
    VisualTarget,
)

logger = get_logger(__name__)


class VisionBudgetExceeded(RuntimeError):
    """Raised when a task or navigation-epoch vision budget is exhausted."""


class VisionRouter:
    """Inspect rendering surfaces and enrich weak ARIA snapshots with vision."""

    def __init__(self, config: ExploreConfig, llm_client: Any | None = None) -> None:
        self._config = config
        self._llm_client = llm_client
        self._task_calls = 0
        self._epoch_calls: dict[int, int] = {}

    def reset_task(self) -> None:
        self._task_calls = 0
        self._epoch_calls.clear()

    @property
    def available(self) -> bool:
        if not self._config.vision_enabled:
            return False
        if os.getenv("VISION_MODEL", "").strip():
            return True
        return bool(
            self._llm_client is not None
            and getattr(self._llm_client, "available", False)
            and getattr(self._llm_client, "supports_vision", False)
        )

    def inspect_surface(self, page: Any) -> SurfaceStats:
        """Collect cheap DOM rendering statistics without taking a screenshot."""
        try:
            data = page.evaluate(
                """() => {
                    const vw = Math.max(1, window.innerWidth || 1);
                    const vh = Math.max(1, window.innerHeight || 1);
                    let canvasArea = 0;
                    let webglCount = 0;
                    const canvases = Array.from(document.querySelectorAll('canvas'));
                    for (const canvas of canvases) {
                        const r = canvas.getBoundingClientRect();
                        const w = Math.max(0, Math.min(vw, r.right) - Math.max(0, r.left));
                        const h = Math.max(0, Math.min(vh, r.bottom) - Math.max(0, r.top));
                        canvasArea += w * h;
                        try {
                            if (canvas.getContext('webgl2') || canvas.getContext('webgl')) {
                                webglCount += 1;
                            }
                        } catch (_) {}
                    }
                    return {
                        viewport_width: vw,
                        viewport_height: vh,
                        canvas_count: canvases.length,
                        webgl_count: webglCount,
                        iframe_count: document.querySelectorAll('iframe').length,
                        visible_canvas_area_ratio: Math.min(1, canvasArea / (vw * vh)),
                    };
                }"""
            )
            return SurfaceStats.model_validate(data)
        except Exception:
            return SurfaceStats()

    def aria_quality(self, snapshot: SnapshotResponse) -> float:
        """Estimate whether the semantic snapshot is sufficient for planning."""
        if snapshot.interactive_count <= 0:
            return 0.0
        targets = [node for node in self._iter_nodes(snapshot.nodes) if node.ref]
        if not targets:
            return 0.0
        named = sum(1 for node in targets if node.name.strip())
        count_score = min(1.0, snapshot.interactive_count / 12.0)
        name_score = named / max(1, len(targets))
        return round((count_score * 0.6) + (name_score * 0.4), 3)

    def should_skip_deep_scan(self, snapshot: SnapshotResponse) -> bool:
        stats = snapshot.surface_stats
        return (
            stats.webgl_count > 0
            or stats.visible_canvas_area_ratio
            >= self._config.vision_strong_canvas_ratio
        )

    def should_enhance(self, snapshot: SnapshotResponse) -> bool:
        return self.available and (
            snapshot.deep_scanned or self.should_skip_deep_scan(snapshot)
        ) and snapshot.aria_quality < self._config.vision_quality_threshold

    def enhance(
        self,
        page: Any,
        snapshot: SnapshotResponse,
        task: str,
        navigation_epoch: int,
    ) -> SnapshotResponse:
        """Capture, analyze and attach normalized visual targets."""
        self._consume_budget(navigation_epoch)
        screenshot = page.screenshot(type="png", full_page=False)
        if len(screenshot) > self._config.vision_max_screenshot_bytes:
            raise RuntimeError("Explore screenshot exceeds configured byte limit")

        logger.info(
            "Explore Vision 增强: 截图大小=%d bytes, url=%s, epoch=%d",
            len(screenshot), snapshot.url, navigation_epoch,
        )

        stats = snapshot.surface_stats
        width = max(1, stats.viewport_width)
        height = max(1, stats.viewport_height)
        scroll = self._read_scroll(page)
        snapshot.screenshot_meta = ScreenshotMeta(
            url=snapshot.url,
            viewport_width=width,
            viewport_height=height,
            scroll_x=scroll[0],
            scroll_y=scroll[1],
            navigation_epoch=navigation_epoch,
        )

        # Import lazily so vision dependencies are not loaded while the feature
        # is disabled (the default rollout state).
        from src.core.vision import VisionModule

        analysis = self._make_vision_module(VisionModule).analyze_screenshot(
            screenshot,
            question=(
                f"用户任务：{task}。只标记完成任务所需且当前可见的交互目标；"
                "不要猜测被遮挡或截图外元素。"
            ),
        )
        targets: list[VisualTarget] = []
        for item in analysis.elements:
            if item.confidence < self._config.vision_min_confidence:
                continue
            if item.width <= 0 or item.height <= 0:
                continue
            left = max(0.0, min(1.0, item.x / width))
            top = max(0.0, min(1.0, item.y / height))
            normalized_width = max(0.0, min(1.0 - left, item.width / width))
            normalized_height = max(0.0, min(1.0 - top, item.height / height))
            if normalized_width <= 0 or normalized_height <= 0:
                continue
            targets.append(
                VisualTarget(
                    ref=f"v{len(targets) + 1}",
                    description=str(item.description)[:200],
                    role=str(item.role)[:40],
                    x=left,
                    y=top,
                    width=normalized_width,
                    height=normalized_height,
                    confidence=item.confidence,
                )
            )
            if len(targets) >= self._config.vision_max_elements:
                break

        snapshot.visual_summary = str(analysis.summary)[:1000]
        snapshot.visual_targets = targets
        snapshot.vision_enhanced = True

        # 记录视觉增强结果
        confidence_dist = [f"{t.confidence:.2f}" for t in targets]
        logger.info(
            "Explore Vision 增强完成: %d 个视觉目标, 置信度分布=[%s], summary=%s",
            len(targets), ", ".join(confidence_dist), snapshot.visual_summary[:200],
        )
        return snapshot

    # ── OCR Enhancement ──────────────────────────────────────────────

    @property
    def ocr_available(self) -> bool:
        """Check if Windows OCR is available (platform + config)."""
        if not self._config.ocr_enabled:
            return False
        try:
            from src.core.ocr import get_ocr_module
            module = get_ocr_module(language=self._config.ocr_language)
            if module is None:
                logger.debug("OCR module returned None (init failed or unsupported platform)")
            return module is not None
        except Exception as exc:
            logger.debug("OCR availability check failed: %s", exc)
            return False

    def ocr_enhance(
        self,
        page: Any,
        snapshot: SnapshotResponse,
        task: str,
        max_words: int | None = None,
    ) -> SnapshotResponse:
        """Enrich snapshot with OCR-detected text targets.

        Runs Windows OCR on the viewport screenshot and attaches matching
        text as ``ocr_targets`` with ``o``-prefix refs.
        """
        import asyncio

        from src.core.ocr import get_ocr_module

        ocr = get_ocr_module(language=self._config.ocr_language)
        if ocr is None:
            logger.warning("OCR module unavailable")
            return snapshot

        screenshot = page.screenshot(type="png", full_page=False)

        stats = snapshot.surface_stats
        vw = max(1, stats.viewport_width)
        vh = max(1, stats.viewport_height)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, ocr.recognize(screenshot, vw, vh))
                ocr_result = future.result(timeout=15)
        else:
            ocr_result = asyncio.run(ocr.recognize(screenshot, vw, vh))

        limit = max_words or self._config.ocr_max_words
        targets: list[VisualTarget] = []
        for word in ocr_result.words[:limit]:
            targets.append(
                VisualTarget(
                    ref=f"o{len(targets) + 1}",
                    description=word.text[:200],
                    role="text",
                    x=max(0.0, min(1.0, word.x)),
                    y=max(0.0, min(1.0, word.y)),
                    width=max(0.0, min(1.0 - word.x, word.width)),
                    height=max(0.0, min(1.0 - word.y, word.height)),
                    confidence=0.7,
                )
            )

        snapshot.ocr_targets = targets
        snapshot.ocr_summary = ocr_result.raw_text[:1000]
        snapshot.ocr_enhanced = True

        # Ensure screenshot_meta is set for coordinate conversion in executor
        if snapshot.screenshot_meta is None:
            scroll = self._read_scroll(page)
            snapshot.screenshot_meta = ScreenshotMeta(
                url=snapshot.url,
                viewport_width=vw,
                viewport_height=vh,
                scroll_x=scroll[0],
                scroll_y=scroll[1],
                navigation_epoch=0,
            )
        logger.info(
            "OCR enhanced: %d targets from %d words",
            len(targets),
            len(ocr_result.words),
        )
        for t in targets:
            logger.debug(
                "OCR target: ref=%s text=%r x=%.3f y=%.3f w=%.3f h=%.3f",
                t.ref, t.description, t.x, t.y, t.width, t.height,
            )
        return snapshot

    def _make_vision_module(self, module_type):
        timeout = self._config.vision_timeout_ms / 1000.0
        llm_config = getattr(self._llm_client, "_config", None)
        vision_model = os.getenv("VISION_MODEL", "").strip()
        vision_key = os.getenv("VISION_API_KEY", "").strip()
        if vision_model or vision_key:
            return module_type(
                provider=(
                    os.getenv("VISION_PROVIDER", "").strip()
                    or getattr(llm_config, "provider", None)
                ),
                api_key=vision_key or getattr(llm_config, "api_key", None),
                base_url=(
                    os.getenv("VISION_BASE_URL", "").strip()
                    or getattr(llm_config, "base_url", None)
                ),
                model=vision_model or getattr(llm_config, "model", None),
                timeout=timeout,
            )
        if llm_config is None:
            return module_type(timeout=timeout)
        return module_type(
            provider=llm_config.provider,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            model=llm_config.model,
            timeout=timeout,
        )

    def _consume_budget(self, epoch: int) -> None:
        epoch_calls = self._epoch_calls.get(epoch, 0)
        if self._task_calls >= self._config.vision_max_calls_per_task:
            raise VisionBudgetExceeded("Explore task vision budget exhausted")
        if epoch_calls >= self._config.vision_max_calls_per_page:
            raise VisionBudgetExceeded("Explore page vision budget exhausted")
        self._task_calls += 1
        self._epoch_calls[epoch] = epoch_calls + 1

    @staticmethod
    def _read_scroll(page: Any) -> tuple[float, float]:
        try:
            data = page.evaluate("() => [window.scrollX || 0, window.scrollY || 0]")
            return float(data[0]), float(data[1])
        except Exception:
            return 0.0, 0.0

    @classmethod
    def _iter_nodes(cls, nodes):
        for node in nodes:
            yield node
            yield from cls._iter_nodes(node.children)
