"""Shared helpers for converting ToolSpecs to the OAI tool-calling wire format
and extracting citations from tool observations. Used by both `graph.py`'s
main execute loop and `subagents.py`'s per-subagent loop (A.6/A.7) -- kept
here, not duplicated in each, and not in either module, to avoid a circular
import between them (graph.py calls into subagents.py to delegate; subagents.py
must not import graph.py back)."""

import re
from typing import Dict, List

from app.agent.tools.base import ToolSpec

_CITATION_LINE_RE = re.compile(r"^\d+\.\s*(?P<title>.*?)\s+—\s+(?P<url>https?://\S+)\s+—", re.MULTILINE)


def to_oai_tool(spec: ToolSpec) -> dict:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def extract_citations(name: str, args: dict, observation: str) -> List[Dict[str, str]]:
    if observation.startswith("TOOL_ERROR"):
        return []
    if name == "web_search":
        return [
            {"url": m.group("url"), "title": m.group("title").strip() or m.group("url")}
            for m in _CITATION_LINE_RE.finditer(observation)
        ]
    if name == "fetch_url":
        url = args.get("url", "")
        return [{"url": url, "title": url}] if url else []
    return []
