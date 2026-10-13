"""Sole gateway to language models via Mesh API (docs/05 §3.1)."""

from backend.mesh.mesh_client import MeshClient, MeshResult, ModelTier, redact_messages

__all__ = ["MeshClient", "MeshResult", "ModelTier", "redact_messages"]
