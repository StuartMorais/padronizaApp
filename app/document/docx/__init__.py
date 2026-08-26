"""DOCX scanning, tag parsing and generation.

Keep this package initializer deliberately lazy.  Importing eager scanner and
context-resolver symbols here used to create an order-dependent circular import
when callers imported the smart-template layer before the scanner directly.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "DocumentGenerationError",
    "TagDefinition",
    "TagKind",
    "create_default_fields",
    "generate_docx",
    "parse_tag",
    "scan_docx_fields",
]


def __getattr__(name: str) -> Any:
    if name in {"DocumentGenerationError", "generate_docx"}:
        from app.document.docx.generator import DocumentGenerationError, generate_docx

        return {
            "DocumentGenerationError": DocumentGenerationError,
            "generate_docx": generate_docx,
        }[name]
    if name in {"create_default_fields", "scan_docx_fields"}:
        from app.document.docx.scanner import create_default_fields, scan_docx_fields

        return {
            "create_default_fields": create_default_fields,
            "scan_docx_fields": scan_docx_fields,
        }[name]
    if name in {"TagDefinition", "TagKind", "parse_tag"}:
        from app.document.docx.tags import TagDefinition, TagKind, parse_tag

        return {
            "TagDefinition": TagDefinition,
            "TagKind": TagKind,
            "parse_tag": parse_tag,
        }[name]
    raise AttributeError(name)
