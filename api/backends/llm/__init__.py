"""LLM 后端包 — 懒加载注册

OllamaLLM:     Ollama 本地 NDJSON 协议
OpenAISdkLLM:  openai SDK（推荐，兼容所有 OpenAI 格式 API）
"""
from __future__ import annotations

from .base import BaseLLM
from .mixins import ConfigMixin, ErrorLearningMixin, HttpRetryMixin
from .ollama import OllamaLLM
from .openai_sdk import OpenAISdkLLM

__all__ = [
    "BaseLLM",
    "ConfigMixin",
    "ErrorLearningMixin",
    "HttpRetryMixin",
    "OllamaLLM",
    "OpenAISdkLLM",
]
