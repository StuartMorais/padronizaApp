"""DOCX scanning, tag parsing and generation."""

from app.document.docx.generator import DocumentGenerationError, generate_docx
from app.document.docx.scanner import create_default_fields, scan_docx_fields
from app.document.docx.tags import TagDefinition, TagKind, parse_tag

__all__ = [
    "DocumentGenerationError",
    "TagDefinition",
    "TagKind",
    "create_default_fields",
    "generate_docx",
    "parse_tag",
    "scan_docx_fields",
]
