"""Conversational chat surface over the existing SEO adapters + agents.

Public surface:
    * :class:`ChatRouter` — one turn of the chat, streamed as SSE.
    * :data:`TOOL_SCHEMAS` / :data:`TOOL_HANDLERS` — the registry the
      router hands the LLM and dispatches on.

The chat module is **stateless** server-side. The frontend keeps the
conversation history in ``localStorage`` and POSTs the full transcript
each turn, so we don't introduce new Django models for chat — only the
existing :class:`SEORun` machinery is reused when the chat invokes a
full grading run.
"""
from .router import ChatRouter
from .tools import TOOL_HANDLERS, TOOL_SCHEMAS

__all__ = ["ChatRouter", "TOOL_HANDLERS", "TOOL_SCHEMAS"]
