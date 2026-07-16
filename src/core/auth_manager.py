"""
认证管理器 —— 按站点持久化浏览器 cookie / localStorage。

使用 Playwright 的 storage_state 机制，每个 domain（对应 domains/*.yaml）
保存独立的 JSON 文件到 ~/.agentic-playwright/auth/ 目录。

使用方式:
    from src.core.auth_manager import get_auth_manager

    am = get_auth_manager()
    am.save_auth("baidu", context)       # 保存
    state = am.load_auth("baidu")        # 加载
    print(am.list_domains())             # 列出所有站点及 auth 状态
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 与 config_manager.py 共享同一基础目录
_AUTH_DIR = Path.home() / ".agentic-playwright" / "auth"

# domains 目录（项目根目录下的 domains/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DOMAINS_DIR = _PROJECT_ROOT / "domains"


class AuthManager:
    """按站点管理浏览器认证状态。"""

    def __init__(
        self,
        auth_dir: Path | str | None = None,
        domains_dir: Path | str | None = None,
    ) -> None:
        self._auth_dir = Path(auth_dir) if auth_dir else _AUTH_DIR
        self._domains_dir = Path(domains_dir) if domains_dir else _DOMAINS_DIR

    # ------------------------------------------------------------------
    # 路径工具
    # ------------------------------------------------------------------

    def _auth_path(self, domain: str) -> Path:
        """返回指定 domain 的 storage_state JSON 路径。"""
        return self._auth_dir / f"{domain}.json"

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_domains(self) -> List[Dict[str, Any]]:
        """扫描 domains/ 目录，返回所有站点及其 auth 状态。

        Returns:
            [{"domain": "baidu", "has_auth": True, "auth_path": "..."}, ...]
        """
        results: List[Dict[str, Any]] = []
        if not self._domains_dir.is_dir():
            return results

        for yaml_file in sorted(self._domains_dir.glob("*.yaml")):
            domain = yaml_file.stem
            auth_path = self._auth_path(domain)
            results.append(
                {
                    "domain": domain,
                    "has_auth": auth_path.is_file(),
                    "auth_path": str(auth_path),
                }
            )
        return results

    def has_auth(self, domain: str) -> bool:
        """检查指定 domain 是否已有保存的 auth。"""
        return self._auth_path(domain).is_file()

    def load_auth(self, domain: str) -> Optional[Dict[str, Any]]:
        """加载指定 domain 的 storage_state 数据。

        Returns:
            storage_state 字典，或 None（无文件时）。
        """
        path = self._auth_path(domain)
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load auth for %s: %s", domain, exc)
            return None

    # ------------------------------------------------------------------
    # 保存 / 删除
    # ------------------------------------------------------------------

    def save_auth(self, domain: str, context: Any) -> Path:
        """从 Playwright BrowserContext 保存 storage_state。

        Args:
            domain: 站点名（对应 domains/{domain}.yaml）。
            context: Playwright BrowserContext 实例。

        Returns:
            保存后的文件路径。
        """
        self._auth_dir.mkdir(parents=True, exist_ok=True)
        path = self._auth_path(domain)
        context.storage_state(path=str(path))
        logger.info("Auth saved for domain=%s -> %s", domain, path)
        return path

    def save_state(self, domain: str, state: Dict[str, Any]) -> Path:
        """Persist a previously captured Playwright storage-state snapshot."""
        self._auth_dir.mkdir(parents=True, exist_ok=True)
        path = self._auth_path(domain)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        with open(temporary_path, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(path)
        logger.info("Auth snapshot saved for domain=%s -> %s", domain, path)
        return path

    def delete_auth(self, domain: str) -> bool:
        """删除指定 domain 的 auth 文件。

        Returns:
            True 表示成功删除，False 表示文件不存在。
        """
        path = self._auth_path(domain)
        if path.is_file():
            path.unlink()
            logger.info("Auth deleted for domain=%s", domain)
            return True
        return False


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: AuthManager | None = None


def get_auth_manager() -> AuthManager:
    """获取全局单例 AuthManager 实例。"""
    global _instance
    if _instance is None:
        _instance = AuthManager()
    return _instance


def reset_auth_manager() -> None:
    """重置全局单例（用于测试）。"""
    global _instance
    _instance = None
