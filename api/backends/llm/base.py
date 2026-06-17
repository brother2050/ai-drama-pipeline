"""LLM 后端抽象基类 — 定义所有 LLM 后端必须实现的接口契约"""
from __future__ import annotations

from abc import ABC, abstractmethod

__all__ = ["BaseLLM"]


class BaseLLM(ABC):
    """LLM 后端统一抽象接口。

    所有 LLM 后端（Ollama、OpenAI 兼容、自定义等）都必须实现此接口。
    子类通过 Mixin 组合获得 HTTP 重试、错误学习、配置解析等通用能力。
    """

    # ── 必须实现的接口 ──

    @property
    @abstractmethod
    def name(self) -> str:
        """后端唯一标识名（如 'ollama' / 'openai'）"""
        ...

    @property
    @abstractmethod
    def context_length(self) -> int:
        """模型上下文窗口长度（配置值 > API 探测 > 注册表静态配置 > 默认值）"""
        ...

    @abstractmethod
    def chat(self, prompt: str, system: str = "", **kwargs) -> str:
        """发送对话请求并返回模型回复文本。

        Args:
            prompt: 用户 prompt
            system: 系统提示（可选）
            **kwargs: 后端特定参数（max_tokens, temperature, top_p, stream 等）

        Returns:
            模型生成的文本内容

        Raises:
            ValueError: API 返回错误
            httpx.HTTPError: 网络异常
        """
        ...

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """健康检查。返回 (是否可用, 原因描述)。"""
        ...

    # ── 可选接口（提供默认实现） ──

    def shutdown(self) -> None:
        """释放资源。默认空操作，子类可按需覆盖。"""
