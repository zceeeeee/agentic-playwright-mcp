"""
LLM 客户端 —— 统一的 AI 模型调用接口。

两个核心方法:
  - chat()      自由文本对话（返回 str）
  - chat_json() 结构化 JSON 输出（返回 dict）

支持 OpenAI 兼容 API（含 Azure、本地模型等）和 Anthropic API。
通过环境变量或构造函数参数配置。

用法::

    from src.core.llm_client import get_llm_client

    client = get_llm_client()

    # 自由文本
    reply = client.chat("用一句话解释什么是 Playwright")

    # 结构化 JSON
    result = client.chat_json(
        "把这句话解析为 JSON: {name, age}",
        system_prompt="你是一个 JSON 提取器",
    )
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class LLMConfig:
    """LLM 客户端配置。"""

    provider: str = "openai"  # "openai" | "anthropic"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0
    max_tokens: int = 1024
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        """从环境变量加载配置。"""
        provider = os.getenv("LLM_PROVIDER", "openai").lower()

        if provider == "anthropic":
            return cls(
                provider="anthropic",
                api_key=os.getenv("ANTHROPIC_API_KEY", ""),
                base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
                temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
                timeout=float(os.getenv("LLM_TIMEOUT", "30")),
            )

        return cls(
            provider="openai",
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip(
                "/"
            ),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
            timeout=float(os.getenv("LLM_TIMEOUT", "30")),
        )


# ---------------------------------------------------------------------------
# LLM 客户端
# ---------------------------------------------------------------------------


class LLMClient:
    """统一的 AI 模型调用客户端。

    提供两个核心方法:
      - chat(prompt)      → str   自由文本回复
      - chat_json(prompt) → dict  结构化 JSON 输出
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        self._config = config or LLMConfig.from_env()

    @property
    def available(self) -> bool:
        """API Key 是否已配置。"""
        return bool(self._config.api_key)

    @property
    def model(self) -> str:
        """当前使用的模型名称。"""
        return self._config.model

    # -------------------------------------------------------------------
    # 接口 1: 自由文本对话
    # -------------------------------------------------------------------

    def chat(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """自由文本对话，返回 LLM 的文本回复。

        Args:
            prompt: 用户消息。
            system_prompt: 系统提示（可选）。
            temperature: 覆盖默认温度。
            max_tokens: 覆盖最大 token 数。

        Returns:
            LLM 的文本回复。

        Raises:
            RuntimeError: API 调用失败。
            ValueError: API Key 未配置。
        """
        self._check_available()

        cfg = self._config
        temp = temperature if temperature is not None else cfg.temperature
        tokens = max_tokens if max_tokens is not None else cfg.max_tokens

        if cfg.provider == "anthropic":
            return self._call_anthropic(prompt, system_prompt, temp, tokens)
        return self._call_openai(prompt, system_prompt, temp, tokens)

    # -------------------------------------------------------------------
    # 接口 2: 结构化 JSON 输出
    # -------------------------------------------------------------------

    def chat_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        schema: Dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Dict[str, Any]:
        """结构化 JSON 输出，返回解析后的字典。

        在 prompt 末尾自动追加 JSON 格式要求。
        如果 LLM 返回的不是合法 JSON，会尝试提取 ```json ``` 块。

        Args:
            prompt: 用户消息。
            system_prompt: 系统提示（可选）。若未提供，自动添加 JSON 输出指令。
            schema: JSON Schema 描述（可选，会追加到 system_prompt 中）。
            temperature: 覆盖默认温度。
            max_tokens: 覆盖最大 token 数。

        Returns:
            解析后的字典。

        Raises:
            RuntimeError: API 调用失败或 JSON 解析失败。
            ValueError: API Key 未配置。
        """
        self._check_available()

        # 自动构造 system_prompt
        json_instruction = "只返回合法 JSON，不要包含其他文字、注释或 markdown 标记。"
        if schema:
            schema_text = json.dumps(schema, ensure_ascii=False, indent=2)
            json_instruction += f"\n\n输出必须符合以下 JSON Schema:\n{schema_text}"

        if system_prompt:
            full_system = f"{system_prompt}\n\n{json_instruction}"
        else:
            full_system = json_instruction

        # 在 prompt 末尾追加格式要求
        full_prompt = f"{prompt}\n\n请以 JSON 格式回复。"

        raw = self.chat(
            full_prompt,
            system_prompt=full_system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        data = self._parse_json(raw)
        self._log_json_response(data)
        return data

    # -------------------------------------------------------------------
    # OpenAI 兼容 API
    # -------------------------------------------------------------------

    def _call_openai(
        self, prompt: str, system_prompt: str | None, temperature: float, max_tokens: int
    ) -> str:
        """调用 OpenAI 兼容 API（含 Azure、本地模型等）。"""
        import httpx

        cfg = self._config
        url = f"{cfg.base_url}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": cfg.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                url, headers=headers, json=payload, timeout=cfg.timeout
            )
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            content_text = message.get("content") or ""
            reasoning_text = message.get("reasoning_content") or ""
            # Prefer content. If it contains JSON, use it directly.
            # If content is empty, try reasoning_content.
            # The caller (chat_json / chat_json_with_retry) handles
            # extracting JSON from mixed reasoning+JSON text.
            return content_text or reasoning_text
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"OpenAI API error {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"OpenAI API call failed: {exc}") from exc

    def _call_with_response_format(
        self, prompt: str, system_prompt: str | None, temperature: float, max_tokens: int
    ) -> str:
        """Call with response_format=json_object for structured output."""
        import httpx

        cfg = self._config

        if cfg.provider == "anthropic":
            return self._call_anthropic(prompt, system_prompt, temperature, max_tokens)

        url = f"{cfg.base_url}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": cfg.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
        }

        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                url, headers=headers, json=payload, timeout=cfg.timeout
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"OpenAI API error {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"OpenAI API call failed: {exc}") from exc

    # -------------------------------------------------------------------
    # Anthropic API
    # -------------------------------------------------------------------

    def _call_anthropic(
        self, prompt: str, system_prompt: str | None, temperature: float, max_tokens: int
    ) -> str:
        """调用 Anthropic Claude API。"""
        import httpx

        cfg = self._config
        url = f"{cfg.base_url.rstrip('/')}/v1/messages"

        payload: Dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        headers = {
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                url, headers=headers, json=payload, timeout=cfg.timeout
            )
            response.raise_for_status()
            data = response.json()
            # Anthropic 返回格式: {"content": [{"type": "text", "text": "..."}]}
            return data["content"][0]["text"]
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Anthropic API error {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Anthropic API call failed: {exc}") from exc

    # -------------------------------------------------------------------
    # 工具方法
    # -------------------------------------------------------------------

    def _check_available(self) -> None:
        """检查 API Key 是否可用。"""
        if not self.available:
            raise ValueError(
                f"LLM API key not configured for provider '{self._config.provider}'. "
                f"Set the appropriate environment variable."
            )

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        """从 LLM 回复中提取 JSON。

        Handles responses that contain chain-of-thought reasoning mixed
        with a JSON object (common with reasoning models like MiMo).
        """
        text = raw.strip()

        # 1. Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. Try extracting ```json ``` block
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > 0:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass

        # 3. Try extracting the LAST complete { ... } block
        #    (reasoning models often put reasoning first, JSON last)
        last_start = text.rfind("{")
        if last_start != -1:
            depth = 0
            for i in range(last_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[last_start : i + 1])
                        except json.JSONDecodeError:
                            break

        # 4. Try extracting the FIRST complete { ... } block
        start = text.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break

        # 5. Try array format [ ... ]
        start = text.find("[")
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "[":
                    depth += 1
                elif text[i] == "]":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break

        raise RuntimeError(f"Failed to parse JSON from LLM response: {raw[:200]}")

    def _log_json_response(self, data: Dict[str, Any]) -> None:
        """Print structured AI JSON responses to the backend CLI log."""
        formatted = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        logger.info(
            "AI API JSON response (%s/%s):\n%s",
            self._config.provider,
            self._config.model,
            formatted,
            extra={
                "llm_provider": self._config.provider,
                "llm_model": self._config.model,
                "llm_json_response": data,
            },
        )


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_client: LLMClient | None = None


def get_llm_client(config: LLMConfig | None = None) -> LLMClient:
    """获取全局单例 LLMClient。

    Args:
        config: 可选的配置。首次调用后忽略（使用缓存实例）。
    """
    global _client
    if _client is None:
        _client = LLMClient(config=config)
    return _client


def reset_llm_client() -> None:
    """重置全局单例（用于测试）。"""
    global _client
    _client = None
