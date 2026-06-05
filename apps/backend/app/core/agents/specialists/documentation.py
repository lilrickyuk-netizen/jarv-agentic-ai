"""
JARV Backend - DocumentationAgent

Drafts technical documentation.

This agent does NOT write any file to the repo: the draft it produces is
returned in the result only, never persisted. When an LLM provider is
configured it drafts the requested documentation via the model router. It may
also build a REAL outline from provided existing files by reading them (via the
shared helpers) and extracting markdown headings and Python function/class
definitions. There are no fabricated word counts, no fake quality scores, and
no false "documentation created" / files-written claims.
"""
from typing import Dict, Any, List, Optional, Type
import re
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class DocumentationAgentInput(BaseModel):
    """DocumentationAgent input"""
    doc_type: str = Field(..., description="Type: API, user guide, architecture, tutorial")
    target: str = Field(..., description="What to document")
    existing_files: list[str] = Field(default_factory=list)
    format: str = Field(default="markdown", description="Output format")


class DocumentationAgentOutput(BaseModel):
    """DocumentationAgent output (honest; draft only, not written to repo)."""
    doc_type: str = ""
    target: str = ""
    written_to_repo: bool = False
    draft: str = ""
    outline: List[str] = Field(default_factory=list)
    source_files_read: List[str] = Field(default_factory=list)
    provider_used: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class DocumentationAgent(AgentBase):
    """
    DocumentationAgent - Creates and maintains technical documentation
    """

    @property
    def name(self) -> str:
        return "documentation"

    @property
    def role(self) -> str:
        return "Creates and maintains technical documentation"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return DocumentationAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return DocumentationAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def default_tools(self) -> list[str]:
        return ['file_read', 'file_write', 'file_search', 'analyze_code']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            doc_type = input_data.get("doc_type", "user_guide")
            target = (input_data.get("target") or "").strip()
            existing_files = list(input_data.get("existing_files", []) or [])

            self.logger.info(f"Drafting {doc_type} documentation for {target or '(unspecified)'}")

            limitations: List[str] = [
                "Draft only; NOT written to the repo. This agent returns "
                "documentation text in its result and does not create or modify "
                "any file.",
            ]

            # ---- Real outline extracted from provided existing files --------
            existing, missing = helpers.resolve_files(existing_files, context)
            for m in missing:
                limitations.append(f"Existing file not found, skipped: {m}")

            source_files_read: List[str] = []
            outline: List[str] = []
            source_snippets: List[str] = []
            for path in existing:
                text = helpers.read_file_safe(path)
                if text is None:
                    limitations.append(f"File could not be read: {path}")
                    continue
                source_files_read.append(path)
                extracted = self._extract_outline(path, text)
                outline.extend(extracted)
                source_snippets.append(f"{path}:\n" + "\n".join(extracted[:40]))

            # ---- Model-backed draft when a provider is configured -----------
            draft = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            if helpers.provider_configured():
                src_block = (
                    "Existing source structure to document:\n"
                    + "\n\n".join(source_snippets) + "\n\n"
                ) if source_snippets else ""
                prompt = (
                    f"Draft {doc_type} documentation for: {target or '(unspecified target)'}. "
                    f"Output format: {input_data.get('format', 'markdown')}.\n\n"
                    + src_block
                    + "Write a complete documentation draft. Do not invent APIs "
                    "or behaviour you cannot infer from the provided structure; "
                    "where unknown, say so explicitly."
                )
                llm = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system="You draft technical documentation. You do not write "
                           "files. Never invent functions, endpoints, or metrics "
                           "you cannot support from the provided sources.",
                    temperature=self.config.temperature,
                    max_tokens=1600,
                )
                if llm is not None:
                    draft = llm["text"]
                    provider_used = llm["provider_used"]
                    tokens = llm["tokens"]
                    limitations.append(
                        "Draft is model-generated and unverified; review for "
                        "accuracy before publishing."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; "
                        "returned the source-derived outline only (no prose draft)."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())

            if not draft and not outline:
                outline = [
                    "Provide existing_files to derive a real outline, and/or "
                    "configure an LLM provider to generate a documentation draft.",
                ]

            output_text = (
                f"Documentation[{doc_type}] for '{target or 'unspecified'}': "
                f"draft only (written_to_repo=False); "
                f"read {len(source_files_read)} source file(s); "
                f"{len(outline)} outline item(s); provider={provider_used or 'none'}."
            )

            return self.create_result(
                success=True,
                result_data={
                    "doc_type": doc_type,
                    "target": target,
                    "written_to_repo": False,
                    "draft": draft,
                    "outline": outline,
                    "source_files_read": source_files_read,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(
                    (["file_read"] if source_files_read else [])
                    + (["model_router"] if provider_used else [])
                ),
                tokens_used=tokens or {},
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"documentation task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )

    @staticmethod
    def _extract_outline(path: str, text: str) -> List[str]:
        """Extract REAL markdown headings or Python def/class names from a file."""
        items: List[str] = []
        lower = path.lower()
        if lower.endswith((".md", ".markdown", ".rst")):
            for line in text.splitlines():
                if re.match(r"^#{1,6}\s+\S", line.strip()):
                    items.append(line.strip())
        elif lower.endswith(".py"):
            for line in text.splitlines():
                m = re.match(r"^\s*(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)", line)
                if m:
                    items.append(f"{m.group(1)} {m.group(2)}")
        else:
            # Generic: capture markdown-style headings if any.
            for line in text.splitlines():
                if re.match(r"^#{1,6}\s+\S", line.strip()):
                    items.append(line.strip())
        return items
