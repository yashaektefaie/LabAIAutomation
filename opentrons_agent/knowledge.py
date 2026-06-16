"""
Load Opentrons documentation from the cloned opentrons-ai-server storage
and format it for use as cached context in Claude API calls.
"""

from __future__ import annotations

from pathlib import Path

from .settings import Settings


def load_knowledge_docs(settings: Settings) -> str:
    """
    Read all markdown files from the opentrons-ai-server docs directory
    and wrap them in XML tags for structured context injection.

    This mirrors the approach in the official opentrons-ai-server
    (AnthropicPredict.get_docs), loading each doc as a tagged block.
    """
    docs_dir = settings.knowledge_dir
    if not docs_dir.exists():
        return "<system_documentation>\n<!-- No documentation found -->\n</system_documentation>"

    xml_parts = ["<system_documentation>"]

    for file_path in sorted(docs_dir.iterdir()):
        if file_path.is_dir():
            continue
        if file_path.suffix not in (".md", ".txt"):
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            xml_parts.extend([
                "<system_doc>",
                f"  <title>{file_path.name}</title>",
                "  <type>reference</type>",
                "  <content>",
                f"    {content}",
                "  </content>",
                "</system_doc>",
            ])
        except Exception:
            continue

    xml_parts.append("</system_documentation>")
    return "\n".join(xml_parts)
