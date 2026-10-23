"""Sole gateway to language models, which calls OpenAI (docs/05 §3.1)."""

from backend.mesh.mesh_client import MeshClient, MeshResult, ModelTier, redact_messages

__all__ = ["MeshClient", "MeshResult", "ModelTier", "redact_messages"]
