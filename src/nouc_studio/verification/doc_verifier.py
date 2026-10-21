"""Zero-Blind-Trust Live Symbol Introspection and DeepWiki / Agent-Plugin Grounding."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

import httpx
from pydantic import BaseModel, Field


class SymbolVerificationResult(BaseModel):
    """Result of verifying a Python module, class, or callable in the live runtime environment."""

    module_name: str
    symbol_path: str
    exists: bool
    kind: str = "unknown"
    signature: str | None = None
    typed_dict_keys: list[str] = Field(default_factory=list)
    docstring_preview: str = ""
    error: str | None = None


def verify_live_python_symbol(module_name: str, symbol_path: str = "") -> SymbolVerificationResult:
    """Introspect the live installed Python environment to verify a module or symbol before code generation.

    Eliminates LLM hallucination of non-existent methods, parameters, or deprecated signatures.
    """
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:
        return SymbolVerificationResult(
            module_name=module_name,
            symbol_path=symbol_path,
            exists=False,
            error=f"ImportError: {exc}",
        )

    target: Any = mod
    if symbol_path:
        for attr in symbol_path.split("."):
            if not hasattr(target, attr):
                return SymbolVerificationResult(
                    module_name=module_name,
                    symbol_path=symbol_path,
                    exists=False,
                    error=f"Attribute '{attr}' does not exist on '{module_name}' (available: {[a for a in dir(target) if not a.startswith('_')][:25]})",
                )
            target = getattr(target, attr)

    doc = (inspect.getdoc(target) or "")[:400]

    # Check if TypedDict (where inspect.signature raises ValueError on builtin dict)
    if isinstance(target, type) and issubclass(target, dict) and hasattr(target, "__annotations__"):
        return SymbolVerificationResult(
            module_name=module_name,
            symbol_path=symbol_path,
            exists=True,
            kind="TypedDict",
            typed_dict_keys=list(target.__annotations__.keys()),
            docstring_preview=doc,
        )

    sig_str: str | None = None
    try:
        sig_str = str(inspect.signature(target))
    except (ValueError, TypeError):
        sig_str = None

    kind = "module" if inspect.ismodule(target) else ("class" if inspect.isclass(target) else ("callable" if callable(target) else type(target).__name__))
    return SymbolVerificationResult(
        module_name=module_name,
        symbol_path=symbol_path,
        exists=True,
        kind=kind,
        signature=sig_str,
        docstring_preview=doc,
    )


def load_installed_marimo_studio_skill_reference(reference_name: str | None = None) -> str:
    """Read live packaged agent skill instructions directly from the installed `marimo-studio` package."""
    try:
        import marimo_studio

        skill = marimo_studio.agent.skill()
        if reference_name is None:
            return str(skill.file("SKILL.md").read_text(encoding="utf-8"))
        ref_path = reference_name if reference_name.startswith("references/") else f"references/{reference_name}"
        return str(skill.file(ref_path).read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Unable to load marimo_studio skill reference '{reference_name}': {exc}"


class DeepWikiClient:
    """Client for querying DeepWiki MCP (https://mcp.deepwiki.com/mcp) to ground agents in live GitHub docs."""

    def __init__(self, mcp_url: str = "https://mcp.deepwiki.com/mcp", timeout_secs: float = 10.0) -> None:
        self.mcp_url = mcp_url
        self.timeout_secs = timeout_secs

    def ask_repo_question(self, repo: str, question: str) -> dict[str, Any]:
        """Query DeepWiki MCP `ask_question` tool over Streamable HTTP JSON-RPC, with graceful offline fallback."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ask_question",
                "arguments": {
                    "repoName": repo,
                    "question": question,
                },
            },
        }
        try:
            with httpx.Client(timeout=self.timeout_secs, follow_redirects=True) as client:
                resp = client.post(
                    self.mcp_url,
                    json=payload,
                    headers={"Accept": "application/json, text/event-stream"},
                )
                if resp.status_code == 200:
                    return {"repo": repo, "status": "ok", "response": resp.text[:2000]}
                return {
                    "repo": repo,
                    "status": f"http_{resp.status_code}",
                    "fallback": load_installed_marimo_studio_skill_reference() if "marimo" in repo else "",
                }
        except Exception as exc:
            return {
                "repo": repo,
                "status": "offline_fallback",
                "error": str(exc),
                "fallback": load_installed_marimo_studio_skill_reference() if "marimo" in repo else "",
            }
