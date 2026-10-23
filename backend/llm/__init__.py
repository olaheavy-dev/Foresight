"""Sole gateway to language models, which calls OpenAI (docs/05 §3.1)."""

from backend.llm.client import ModelClient, ModelResult, ModelTier, redact_messages

__all__ = ["ModelClient", "ModelResult", "ModelTier", "redact_messages"]
