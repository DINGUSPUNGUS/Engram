"""Provider adapters: one small file per assistant, translation only (ADR-0020)."""

from engram_assistants.adapters.chatgpt import ChatGPTAdapter
from engram_assistants.adapters.claude import ClaudeAdapter
from engram_assistants.adapters.gemini import GeminiAdapter

__all__ = ["ChatGPTAdapter", "ClaudeAdapter", "GeminiAdapter"]
