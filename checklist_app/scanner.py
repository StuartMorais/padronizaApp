from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
import re

from .storage import new_id

SCANNER_VERSION = 6
AUTO_APPLY_CONFIDENCE = 0.85

SECTION_RE = re.compile(r"^\s*(\d{1,2})\.\s+(.{4,})\s*$")
ITEM_RE = re.compile(r"(?:^|\s)(\d+(?:\.\d+)+)\.\s*(.+?)\s*$")
CODE_RE = re.compile(r"\bSIA[A-Z0-9]{3,}\b", re.IGNORECASE)
PROCESS_RE = re.compile(r"\b[A-Z]{2,8}-PRC-\d{4}/\d+\b|\b\d{1,8}/\d{4}\b", re.IGNORECASE)
NORMATIVE_RE = re.compile(
    r"\b(?:Lei|Decreto|Instrução\s+Normativa|IN|Resolução|Portaria|Acórdão|Art\.?|art\.?)\b[^.;\n]*",
    re.IGNORECASE,
)
DOCUMENT_WORD_RE = re.compile(
    r"\b(?:documento|informação|informacoes|comprovante|declaração|declaracao|certidão|certidao|termo|ata|estudo|justificativa|parecer|contrato|processo|relatório|relatorio|autorização|autorizacao)\b",
    re.IGNORECASE,
)

# Official SINGRA checklist table geometry. Values are ratios of A4 page width
# so the scanner remains stable when the PDF uses a slightly different MediaBox.
OFFICIAL_COLUMN_RATIOS = (0.0242, 0.3805, 0.4997, 0.6069, 0.7379, 0.8092, 0.9760)


@dataclass
class ScanIssue:
    severity: str
    code: str
    message: str
    page: int = 0
    item_number: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "page": self.page,
            "item_number": self.item_number,
        }


@dataclass
class ScanReport:
    scanner_version: int = SCANNER_VERSION
    source_kind: str = ""
    page_count: int = 0
    structure_kind: str = "unknown"
    sections: list[str] = field(default_factory=list)
    candidate_count: int = 0
    selected_count: int = 0
    review_count: int = 0
    table_header_pages: int = 0
    native_pdf_fields: int = 0
    warnings: list[str] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)
    extracted_metadata: dict[str, str] = field(default_factory=dict)

    @property
    def blocking_issue_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanner_version": self.scanner_version,
            "source_kind": self.source_kind,
            "page_count": self.page_count,
            "structure_kind": self.structure_kind,
            "sections": list(self.sections),
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "review_count": self.review_count,
            "table_header_pages": self.table_header_pages,
            "native_pdf_fields": self.native_pdf_fields,
            "warnings": list(self.warnings),
            "issues": [issue.as_dict() for issue in self.issues],
            "blocking_issue_count": self.blocking_issue_count,
            "extracted_metadata": dict(self.extracted_metadata),
        }


@dataclass(frozen=True)
class ScanResult:
    source_path: Path
    candidates: tuple[dict[str, Any], ...]
    report: ScanReport
    metadata: dict[str, str]

    def candidate_list(self) -> list[dict[str, Any]]:
        return [deepcopy(item) for item in self.candidates]


ProgressCallback = Callable[[int, int, str], None]


def analyze_document(file_path: str | Path, *, progress: ProgressCallback | None = None) -> ScanResult:
    """Analyze a checklist source without mutating application data.

    The public scanner follows the same review-first contract used by Padroniza:
    verify -> extract structure -> detect rows -> classify evidence -> run
    invariants -> apply conservative selection policy.  A checklist is only
    created after the UI review step accepts the detected rows.
    """

    path = Path(file_path).expanduser().resolve()
    _progress(progress, 1, 6, "Verificando o arquivo")
    if not path.exists() or not path.is_file():
        raise ValueError("O arquivo selecionado não foi encontrado.")

    suffix = path.suffix.casefold()
    if suffix not in {".pdf", ".docx", ".docm"}:
        raise ValueError("Formato não suportado. Use PDF, DOCX ou DOCM.")

    if suffix == ".pdf":
        _progress(progress, 2, 6, "Extraindo estrutura e geometria do PDF")
        result = _analyze_pdf(path)
    else:
        _progress(progress, 2, 6, "Extraindo estrutura do documento Word")
        result = _analyze_word(path)

    _progress(progress, 4, 6, "Calculando evidências e confiança")
    prepared = apply_review_first_policy(result.candidate_list())
    result.report.candidate_count = len(prepared)
    result.report.selected_count = sum(bool(item.get("selected")) for item in prepared)
    result.report.review_count = len(prepared) - result.report.selected_count

    _progress(progress, 5, 6, "Executando verificações estruturais")
    result.report.issues.extend(_validate_candidates(prepared, result.report.sections))

    _progress(progress, 6, 6, "Análise concluída")
    return ScanResult(
        source_path=result.source_path,
        candidates=tuple(prepared),
        report=result.report,
        metadata=dict(result.metadata),
    )


def scan_document_to_template(file_path: str | Path) -> dict[str, Any]:
    """Compatibility helper: analyze and build from safely preselected rows."""

    result = analyze_document(file_path)
    accepted = [item for item in result.candidates if item.get("selected")]
    return build_template_from_scan(result, accepted)


def build_template_from_scan(
    result: ScanResult,
    reviewed_candidates: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    accepted = [
        deepcopy(item)
        for item in reviewed_candidates
        if bool(item.get("accepted_by_user", item.get("selected", False)))
    ]
    metadata = dict(result.metadata)
    title = metadata.get("title") or result.source_path.stem
    subtitle = metadata.get("subtitle") or f"Importado por Scanner V{SCANNER_VERSION}"

    template: dict[str, Any] = {
        "id": new_id("checklist"),
        "title": title,
        "subtitle": subtitle,
        "baseLegal": metadata.get("baseLegal", ""),
        "description": f"Checklist criado a partir de: {result.source_path.name}",
        "sections": [],
        "sourceMetadata": {
            **metadata,
            "sourceFile": result.source_path.name,
            "sourcePath": str(result.source_path),
            "scannerVersion": str(SCANNER_VERSION),
        },
        "scanReport": result.report.as_dict(),
        "scanCandidates": [deepcopy(item) for item in reviewed_candidates],
    }

    section_map: dict[str, dict[str, Any]] = {}
    section_order: list[str] = []
    for candidate in accepted:
        section_number = str(candidate.get("section_number") or "1")
        section_title = str(candidate.get("section_title") or "DOCUMENTOS / ITENS IDENTIFICADOS")
        if section_number not in section_map:
            section = make_section(section_number, section_title)
            section_map[section_number] = section
            section_order.append(section_number)

        item = make_item(
            number=str(candidate.get("number") or ""),
            text=str(candidate.get("documento") or ""),
            confidence=str(candidate.get("confidence_band") or "reviewed"),
            evidence="; ".join(str(x) for x in candidate.get("evidence", []) if str(x)),
        )
        item.update(
            {
                "normativo": str(candidate.get("normativo") or ""),
                "situacao": str(candidate.get("situacao") or ""),
                "folha": str(candidate.get("folha") or ""),
                "observacao": str(candidate.get("observacao") or ""),
                "scanCandidateId": str(candidate.get("candidate_id") or ""),
                "scanSource": str(candidate.get("source") or ""),
                "scanPage": int(candidate.get("source_page") or 0),
                "scanRect": list(candidate.get("source_rect") or []),
                "scanConfidenceValue": float(candidate.get("confidence", 0.0) or 0.0),
                "scanDimensions": dict(candidate.get("confidence_dimensions") or {}),
                "scanReviewed": bool(candidate.get("reviewed_by_user", False)),
            }
        )
        section_map[section_number]["items"].append(item)

    template["sections"] = [section_map[number] for number in section_order]
    if not template["sections"]:
        template["sections"] = [make_section("1", "DOCUMENTOS / ITENS IDENTIFICADOS")]
    return template


def apply_review_first_policy(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for raw in candidates:
        candidate = deepcopy(raw)
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
        dimensions = dict(candidate.get("confidence_dimensions") or {})
        reasons: list[str] = []
        if confidence < AUTO_APPLY_CONFIDENCE:
            reasons.append(f"Confiança {confidence:.0%} abaixo do limite de {AUTO_APPLY_CONFIDENCE:.0%}.")
        if float(dimensions.get("structure", 0.0) or 0.0) < 0.70:
            reasons.append("Estrutura insuficiente para aplicação automática.")
        if not str(candidate.get("number") or "").strip():
            reasons.append("Número do item não confirmado.")
        if str(candidate.get("source") or "") == "text_fallback":
            reasons.append("Item inferido apenas pelo texto; confirme antes de usar.")

        candidate["pipeline_version"] = SCANNER_VERSION
        candidate["auto_apply_eligible"] = not reasons
        candidate["auto_apply_reasons"] = reasons
        candidate["selected"] = not reasons
        candidate["confidence_band"] = confidence_band(confidence)
        prepared.append(candidate)
    return prepared


def confidence_band(value: float) -> str:
    if value >= 0.90:
        return "Identificado"
    if value >= 0.70:
        return "Confira"
    return "Possível item"


# ---------------------------------------------------------------------------
# PDF structure scanner


def _analyze_pdf(path: Path) -> ScanResult:
    try:
        import fitz
    except ImportError as error:
        raise RuntimeError("Instale PyMuPDF para usar o scanner estrutural de PDF.") from error

    document = fitz.open(str(path))
    if document.needs_pass:
        document.close()
        raise ValueError("O PDF está protegido por senha e não pode ser analisado.")

    report = ScanReport(source_kind="PDF", page_count=document.page_count)
    metadata = _extract_pdf_metadata(document, path)
    candidates: list[dict[str, Any]] = []
    section_events: list[tuple[int, float, str, str]] = []
    row_events: list[dict[str, Any]] = []
    geometry_pages = 0

    for page_index, page in enumerate(document):
        page_number = page_index + 1
        header_detected = _has_official_table_header(page)
        if header_detected:
            report.table_header_pages += 1

        sections = _extract_section_bars(page, page_number)
        section_events.extend(sections)
        rows = _extract_official_rows(page, page_number)
        if rows:
            geometry_pages += 1
            row_events.extend(rows)

    if row_events and geometry_pages >= max(1, document.page_count // 2):
        report.structure_kind = "official_singra_checklist"
        candidates = _assign_sections_to_rows(row_events, section_events)
    else:
        report.structure_kind = "text_fallback"
        report.warnings.append(
            "A grade oficial não foi reconhecida com confiança suficiente; o scanner usou leitura textual conservadora."
        )
        lines: list[str] = []
        for page in document:
            lines.extend(clean_text(line) for line in (page.get_text("text") or "").splitlines() if clean_text(line))
        candidates, fallback_sections = _candidates_from_lines(lines)
        report.sections = fallback_sections

    document.close()

    if not report.sections:
        report.sections = _ordered_section_labels(candidates)
    report.extracted_metadata = dict(metadata)
    if not candidates:
        report.issues.append(ScanIssue("error", "no_items", "Nenhum item de checklist foi identificado."))
    if report.table_header_pages == 0 and report.structure_kind != "text_fallback":
        report.warnings.append("O cabeçalho da tabela de verificação não foi identificado.")
    return ScanResult(path, tuple(candidates), report, metadata)


def _has_official_table_header(page: Any) -> bool:
    text = normalize_text(page.get_text("text") or "")
    required = (
        "documentos/ informacoes constantes do processo",
        "codigo plataforma",
        "normativos",
        "nao aplicavel",
        "observacao",
    )
    return sum(token in text for token in required) >= 4


def _table_x(page_width: float) -> tuple[float, ...]:
    return tuple(page_width * ratio for ratio in OFFICIAL_COLUMN_RATIOS)


def _extract_left_column_boundaries(page: Any) -> list[float]:
    page_width = float(page.rect.width)
    target_x0 = page_width * OFFICIAL_COLUMN_RATIOS[0]
    target_width = page_width * (OFFICIAL_COLUMN_RATIOS[1] - OFFICIAL_COLUMN_RATIOS[0])
    values: list[float] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if not item or item[0] != "re":
                continue
            rect = item[1]
            if (
                abs(float(rect.x0) - target_x0) <= 2.0
                and abs(float(rect.width) - target_width) <= 4.0
                and float(rect.height) <= 1.5
            ):
                values.append((float(rect.y0) + float(rect.y1)) / 2.0)
    return _unique_sorted(values, tolerance=1.0)


def _extract_section_bars(page: Any, page_number: int) -> list[tuple[int, float, str, str]]:
    page_width = float(page.rect.width)
    target_x0 = page_width * OFFICIAL_COLUMN_RATIOS[0]
    bars: list[tuple[int, float, str, str]] = []
    seen: set[tuple[str, int]] = set()
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if not item or item[0] != "re":
                continue
            rect = item[1]
            if not (
                abs(float(rect.x0) - target_x0) <= 2.0
                and float(rect.width) >= page_width * 0.90
                and 14.0 <= float(rect.height) <= 45.0
            ):
                continue
            text = _text_in_rect(page, rect)
            match = re.search(r"(?:^|\s)(\d{1,2})\.\s+(.+)", clean_text(text))
            if not match:
                continue
            title = clean_text(match.group(2))
            if not looks_like_section_title(title):
                continue
            key = (match.group(1), int(float(rect.y0)))
            if key in seen:
                continue
            seen.add(key)
            bars.append((page_number, float(rect.y0), match.group(1), title.upper()))
    return sorted(bars, key=lambda item: item[1])


def _extract_official_rows(page: Any, page_number: int) -> list[dict[str, Any]]:
    boundaries = _extract_left_column_boundaries(page)
    if len(boundaries) < 3:
        return []

    x = _table_x(float(page.rect.width))
    section_ranges = [(bar[1], bar[1] + 46.0) for bar in _extract_section_bars(page, page_number)]
    rows: list[dict[str, Any]] = []
    for top, bottom in zip(boundaries, boundaries[1:]):
        if bottom - top < 20.0:
            continue
        center_y = (top + bottom) / 2.0
        if any(start - 2.0 <= center_y <= end for start, end in section_ranges):
            continue

        left_text = _column_text(page, top, bottom, x[0], x[1], use_blocks=True)
        left_normalized = normalize_text(left_text)
        if "documentos/ informacoes constantes do processo" in left_normalized:
            continue

        # Remove visual blank-field markers that may precede the row number.
        cleaned_left = re.sub(r"^\s*(?:_+\s*)+", "", clean_text(left_text)).strip()
        number_match = re.search(r"(?:^|\s)(\d+(?:\.\d+)+)\.\s*", cleaned_left)
        if not number_match:
            continue

        number = number_match.group(1)
        document_text = cleaned_left[number_match.end():].strip()
        document_text = re.sub(r"\s+_+\s*$", "", document_text).strip()

        # The source PDF still contains a SIAGOV code column.  We keep its
        # geometry as a boundary so the neighboring columns remain stable, but
        # the checklist application no longer imports or stores that value.
        normative = _column_text(page, top, bottom, x[2], x[3])
        normative = _clean_column_placeholder(normative)
        status_raw = _column_text(page, top, bottom, x[3], x[4])
        folha = _clean_column_placeholder(_column_text(page, top, bottom, x[4], x[5]))
        observation = _clean_column_placeholder(_column_text(page, top, bottom, x[5], x[6]))
        situacao = _normalize_status(status_raw)

        evidence = [
            "Linha delimitada pela grade oficial do checklist.",
            f"Numeração {number} identificada na coluna Documento/Informações.",
            "Colunas associadas pela geometria do PDF, não pela ordem do texto extraído.",
        ]
        if normative:
            evidence.append("Referência normativa localizada na coluna Normativos.")
        if "escolha o item" in normalize_text(status_raw):
            evidence.append("Controle S/N/NA visual reconhecido como ainda não preenchido.")

        dimensions = {
            "structure": 1.0,
            "label": 0.98,
            "columns": 0.96,
            "metadata": 0.90 if normative else 0.78,
        }
        confidence = 0.97 if document_text else 0.82
        source_rect = [round(x[0], 2), round(top, 2), round(x[6], 2), round(bottom, 2)]
        rows.append(
            {
                "candidate_id": new_id("scan"),
                "number": number,
                "documento": document_text,
                "normativo": normative,
                "situacao": situacao,
                "folha": folha,
                "observacao": observation,
                "source": "pdf_table_geometry",
                "source_page": page_number,
                "source_rect": source_rect,
                "source_context": clean_text(left_text)[:700],
                "confidence": confidence,
                "confidence_dimensions": dimensions,
                "evidence": evidence,
                "row_top": top,
                "row_bottom": bottom,
            }
        )
    return rows


def _assign_sections_to_rows(
    rows: list[dict[str, Any]],
    section_events: list[tuple[int, float, str, str]],
) -> list[dict[str, Any]]:
    events: list[tuple[int, float, int, Any]] = []
    for page, y, number, title in section_events:
        events.append((page, y, 0, (number, title)))
    for row in rows:
        events.append((int(row.get("source_page") or 0), float(row.get("row_top") or 0.0), 1, row))
    events.sort(key=lambda value: (value[0], value[1], value[2]))

    current_number = "1"
    current_title = "DOCUMENTOS / ITENS IDENTIFICADOS"
    prepared: list[dict[str, Any]] = []
    for _page, _y, kind, payload in events:
        if kind == 0:
            current_number, current_title = payload
            continue
        row = payload
        row["section_number"] = current_number
        row["section_title"] = current_title
        row.pop("row_top", None)
        row.pop("row_bottom", None)
        prepared.append(row)
    return prepared


def _column_text(
    page: Any,
    top: float,
    bottom: float,
    left: float,
    right: float,
    *,
    use_blocks: bool = False,
) -> str:
    if use_blocks:
        parts: list[tuple[float, float, str]] = []
        for block in page.get_text("blocks") or []:
            x0, y0, x1, y1, text = block[:5]
            cx = (float(x0) + float(x1)) / 2.0
            cy = (float(y0) + float(y1)) / 2.0
            if top - 1.0 <= cy <= bottom + 1.0 and left - 3.0 <= cx <= right + 3.0:
                value = clean_text(text)
                if value:
                    parts.append((float(y0), float(x0), value))
        parts.sort(key=lambda item: (item[0], item[1]))
        return clean_text(" ".join(item[2] for item in parts))

    words: list[tuple[float, float, str]] = []
    for raw in page.get_text("words") or []:
        x0, y0, x1, y1, text = raw[:5]
        cx = (float(x0) + float(x1)) / 2.0
        cy = (float(y0) + float(y1)) / 2.0
        if top - 1.0 <= cy <= bottom + 1.0 and left <= cx <= right:
            words.append((float(y0), float(x0), str(text)))
    words.sort(key=lambda item: (round(item[0] / 3.0), item[1]))
    return clean_text(" ".join(item[2] for item in words))


def _text_in_rect(page: Any, rect: Any) -> str:
    words = []
    for raw in page.get_text("words") or []:
        x0, y0, x1, y1, text = raw[:5]
        cx = (float(x0) + float(x1)) / 2.0
        cy = (float(y0) + float(y1)) / 2.0
        if float(rect.x0) <= cx <= float(rect.x1) and float(rect.y0) <= cy <= float(rect.y1):
            words.append((float(y0), float(x0), str(text)))
    words.sort(key=lambda item: (round(item[0] / 3.0), item[1]))
    return clean_text(" ".join(item[2] for item in words))


def _extract_pdf_metadata(document: Any, path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {"title": path.stem}
    if document.page_count == 0:
        return metadata
    page = document[0]
    blocks = [
        (float(b[0]), float(b[1]), float(b[2]), float(b[3]), clean_text(b[4]))
        for b in (page.get_text("blocks") or [])
        if clean_text(b[4])
    ]
    full = "\n".join(value for *_coords, value in blocks)

    checklist = next((value for *_coords, value in blocks if re.search(r"\bCHECKLIST\s+[IVX0-9]+\b", value, re.I)), "")
    subject = next((value for *_coords, value in blocks if "ADESÃO À ATA DE REGISTRO DE PREÇOS" in value.upper()), "")
    legal = next((value for *_coords, value in blocks if re.search(r"LEI\s+N?[º°]?\s*14\.133/21", value, re.I)), "")
    process_match = re.search(r"\b[A-Z]{2,8}-PRC-\d{4}/\d+\b", full, re.I)
    object_block = next((value for x0, y0, _x1, _y1, value in blocks if 70 <= x0 <= 100 and 195 <= y0 <= 250 and len(value) > 20), "")
    if checklist or subject:
        metadata["title"] = clean_text(" - ".join(part for part in (checklist, subject) if part))
        metadata["subtitle"] = subject or checklist
    if legal:
        metadata["baseLegal"] = legal
    if process_match:
        metadata["processoPbdoc"] = process_match.group(0).upper()
    if object_block:
        metadata["objeto"] = object_block
    return metadata


# ---------------------------------------------------------------------------
# Word / text fallback


def _analyze_word(path: Path) -> ScanResult:
    lines = extract_docx_lines(path)
    candidates, sections = _candidates_from_lines(lines)
    report = ScanReport(
        source_kind=path.suffix.upper().lstrip("."),
        page_count=0,
        structure_kind="word_text",
        sections=sections,
        warnings=["DOCX/DOCM usa o detector textual do Checklist; o detector geométrico completo é aplicado aos PDFs oficiais."],
    )
    metadata = {"title": path.stem, "subtitle": f"Importado de {path.suffix.upper().lstrip('.')}"}
    return ScanResult(path, tuple(candidates), report, metadata)


def extract_docx_lines(path: Path) -> list[str]:
    try:
        from docx import Document
        from docx.document import Document as DocxDocument
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as error:
        raise RuntimeError("Instale python-docx para escanear DOCX/DOCM.") from error

    try:
        document = Document(str(path))
    except Exception as error:
        if path.suffix.casefold() == ".docm":
            raise RuntimeError("Este DOCM não pôde ser lido diretamente. Salve uma cópia DOCX segura para escanear.") from error
        raise

    lines: list[str] = []

    def iter_blocks(parent: DocxDocument):
        for child in parent.element.body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    for block in iter_blocks(document):
        if isinstance(block, Paragraph):
            text = clean_text(block.text)
            if text:
                lines.append(text)
        else:
            for row in block.rows:
                cells = [clean_text(cell.text) for cell in row.cells]
                cells = [cell for cell in cells if cell]
                if cells:
                    lines.append(" | ".join(cells))
    return lines


def extract_pdf_lines(path: Path) -> list[str]:
    """Public compatibility helper using PyMuPDF, not pypdf ordering."""
    try:
        import fitz
    except ImportError as error:
        raise RuntimeError("Instale PyMuPDF para escanear PDF.") from error
    document = fitz.open(str(path))
    lines: list[str] = []
    for page in document:
        for raw_line in (page.get_text("text") or "").splitlines():
            line = clean_text(raw_line)
            if line:
                lines.append(line)
    document.close()
    return lines


def _candidates_from_lines(lines: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    sections: list[str] = []
    current_section_number = "1"
    current_section_title = "DOCUMENTOS / ITENS IDENTIFICADOS"
    current_candidate: dict[str, Any] | None = None

    for raw in lines:
        line = clean_text(raw)
        if not line or is_noise_line(line):
            continue
        section_match = SECTION_RE.match(line)
        if section_match and looks_like_section_title(section_match.group(2)):
            current_section_number = section_match.group(1)
            current_section_title = section_match.group(2).upper()
            sections.append(f"{current_section_number}. {current_section_title}")
            current_candidate = None
            continue

        cleaned = re.sub(r"^\s*(?:_+\s*)+", "", line)
        item_match = ITEM_RE.search(cleaned)
        if item_match:
            text = item_match.group(2)
            current_candidate = _text_candidate(
                item_match.group(1),
                text,
                current_section_number,
                current_section_title,
            )
            candidates.append(current_candidate)
            continue
        if current_candidate and should_attach_to_previous_item(line):
            current_candidate["documento"] = clean_text(f"{current_candidate['documento']} {remove_codes_from_text(line)}")
            current_candidate["normativo"] = join_unique_lines(str(current_candidate.get("normativo") or ""), extract_normatives(line))

    return candidates, sections or _ordered_section_labels(candidates)


def _text_candidate(number: str, text: str, section_number: str, section_title: str) -> dict[str, Any]:
    return {
        "candidate_id": new_id("scan"),
        "number": clean_text(number),
        "documento": remove_codes_from_text(text),
        "normativo": extract_normatives(text),
        "situacao": "",
        "folha": "",
        "observacao": "",
        "section_number": section_number,
        "section_title": section_title,
        "source": "text_fallback",
        "source_page": 0,
        "source_rect": [],
        "source_context": clean_text(text),
        "confidence": 0.78,
        "confidence_dimensions": {"structure": 0.62, "label": 0.90, "columns": 0.20, "metadata": 0.55},
        "evidence": ["Numeração de item identificada por leitura textual."],
    }


# ---------------------------------------------------------------------------
# Invariants / helpers


def _validate_candidates(candidates: list[dict[str, Any]], sections: list[str]) -> list[ScanIssue]:
    issues: list[ScanIssue] = []
    if not candidates:
        return [ScanIssue("error", "no_candidates", "Nenhum item foi localizado no documento.")]
    if not sections and not any(str(item.get("section_title") or "").strip() for item in candidates):
        issues.append(ScanIssue("warning", "no_sections", "Nenhuma seção estrutural foi identificada."))

    seen: dict[str, int] = {}
    for candidate in candidates:
        number = str(candidate.get("number") or "").strip()
        page = int(candidate.get("source_page") or 0)
        if not number:
            issues.append(ScanIssue("error", "missing_number", "Item sem numeração confirmada.", page=page))
            continue
        if number in seen:
            issues.append(
                ScanIssue(
                    "error",
                    "duplicate_number",
                    f"O item {number} foi detectado mais de uma vez.",
                    page=page,
                    item_number=number,
                )
            )
        seen[number] = seen.get(number, 0) + 1
        if not str(candidate.get("documento") or "").strip():
            issues.append(ScanIssue("warning", "empty_document", f"O item {number} não possui descrição.", page=page, item_number=number))
        if str(candidate.get("source") or "") == "pdf_table_geometry" and page <= 0:
            issues.append(ScanIssue("error", "missing_page", f"O item {number} perdeu a página de origem.", item_number=number))
    return issues


def make_section(number: str, title: str) -> dict[str, Any]:
    return {"id": new_id("section"), "number": clean_text(number), "title": clean_text(title).upper(), "items": []}


def make_item(number: str, text: str, confidence: str, evidence: str) -> dict[str, Any]:
    return {
        "id": new_id("item"),
        "number": clean_text(number),
        "documento": clean_text(text),
        "normativo": "",
        "situacao": "",
        "folha": "",
        "observacao": "",
        "description": "",
        "requiredDocuments": [],
        "notes": [],
        "scanConfidence": confidence,
        "scanEvidence": [evidence] if evidence else [],
    }


def extract_codes(text: str) -> str:
    matches = [clean_text(match.group(0)).upper() for match in CODE_RE.finditer(text)]
    return "\n".join(dict.fromkeys(matches))


def remove_codes_from_text(text: str) -> str:
    return clean_text(CODE_RE.sub("", text).replace("  ", " "))


def join_unique_lines(existing: str, added: str) -> str:
    values: list[str] = []
    for value in f"{existing}\n{added}".splitlines():
        value = clean_text(value)
        if value and value not in values:
            values.append(value)
    return "\n".join(values)


def extract_normatives(text: str) -> str:
    matches = [clean_text(match.group(0)) for match in NORMATIVE_RE.finditer(text)]
    seen: set[str] = set()
    unique: list[str] = []
    for match in matches:
        key = match.lower()
        if key not in seen:
            seen.add(key)
            unique.append(match)
    return "\n".join(unique)


def looks_like_section_title(text: str) -> bool:
    value = clean_text(text)
    letters = [char for char in value if char.isalpha()]
    if not letters:
        return False
    uppercase_ratio = sum(char.isupper() for char in letters) / len(letters)
    keywords = ("FORMALIDADE", "PLANEJAMENTO", "ESTIMATIVA", "PREÇO", "ADEQUAÇÃO", "ORÇAMENT", "HABILITAÇÃO", "TRAMITES", "TRÂMITES")
    return uppercase_ratio >= 0.55 or any(keyword in value.upper() for keyword in keywords)


def should_attach_to_previous_item(line: str) -> bool:
    if len(line) < 8 or SECTION_RE.match(line) or ITEM_RE.search(line):
        return False
    return not (line.isupper() and len(line.split()) <= 8)


def is_noise_line(line: str) -> bool:
    value = clean_text(line)
    if not value or re.fullmatch(r"\d+", value):
        return True
    if re.fullmatch(r"p[aá]gina\s+\d+(?:\s+de\s+\d+)?", value, flags=re.IGNORECASE):
        return True
    return False


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def normalize_text(value: object) -> str:
    text = clean_text(value).casefold()
    replacements = str.maketrans("áàâãéêíóôõúç", "aaaaeeiooouc")
    return text.translate(replacements)


def _normalize_status(value: str) -> str:
    text = normalize_text(value)
    if not text or "escolha o item" in text:
        return ""
    if "nao aplicavel" in text or re.search(r"\bna\b", text):
        return "Não Aplicável"
    if re.search(r"\bnao\b", text):
        return "Não"
    if re.search(r"\bsim\b", text):
        return "Sim"
    return ""


def _clean_column_placeholder(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"^(?:_+|—+|-+)$", "", text).strip()
    return text


def _unique_sorted(values: list[float], *, tolerance: float) -> list[float]:
    result: list[float] = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) > tolerance:
            result.append(value)
        else:
            result[-1] = (result[-1] + value) / 2.0
    return result


def _ordered_section_labels(candidates: Iterable[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        number = str(candidate.get("section_number") or "").strip()
        title = str(candidate.get("section_title") or "").strip()
        label = f"{number}. {title}".strip(". ")
        if label and label not in seen:
            seen.add(label)
            result.append(label)
    return result


def _progress(callback: ProgressCallback | None, current: int, total: int, message: str) -> None:
    if callback is not None:
        callback(current, total, message)
