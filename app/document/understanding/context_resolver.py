from __future__ import annotations

"""Shared contextual fallbacks for incomplete DOCX/PDF field metadata.

Detector V3 uses this module whenever a field/control is missing information.
Explicit tags and native metadata always win. Context only fills blanks and
records why each inferred value was chosen.
"""

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable, Mapping

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.document.docx.controls import (
    classify_native_control,
    get_control_identifier,
    iter_unique_story_roots,
    normalize_control_id,
    read_dropdown_options,
)


_SECTION_RE = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+\S")
_FILL_RE = re.compile(
    r"^(?:_+|X{3,}|x{3,}|0{2,}(?:[.\-/]0+)*|R\$\s*[Xx0_.\-,]+|"
    r"(?:escolher|selecione|selecionar)\s+(?:um|uma)\s+(?:item|op[cç][aã]o)\.?)$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_RE = re.compile(r"^\(?\d{2}\)?\s*\d{4,5}[-\s]?\d{4}$")
_CPF_RE = re.compile(r"^(?:\d{3}|[Xx0]{3})\.(?:\d{3}|[Xx0]{3})\.(?:\d{3}|[Xx0]{3})-(?:\d{2}|[Xx0]{2})$")
_CNPJ_RE = re.compile(r"^(?:\d{2}|[Xx0]{2})\.(?:\d{3}|[Xx0]{3})\.(?:\d{3}|[Xx0]{3})/(?:\d{4}|[Xx0]{4})-(?:\d{2}|[Xx0]{2})$")
_DATE_RE = re.compile(r"^(?:_\s*[/.-]\s*){2}_+$|^\d{2}/\d{2}/\d{4}$")
_CURRENCY_RE = re.compile(r"^R\$\s*(?:[Xx0_.]+(?:[,\.]?[Xx0_]{2})?|_+(?:,__)?|[\d.]+,\d{2})$")
_GENERIC_LABELS = {
    "campo", "field", "opcao", "opção", "valor", "data", "nome", "tipo",
    "responsavel", "responsável", "descricao", "descrição", "item",
    "sim", "nao", "não", "n a", "conforme", "parcial",
}


@dataclass(frozen=True)
class ResolvedValue:
    value: str
    source: str
    confidence: float
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source,
            "confidence": round(float(self.confidence), 3),
            "description": self.description,
        }


@dataclass(frozen=True)
class WordControlPreparation:
    path: Path
    changed: bool
    auto_tagged: int
    fallback_ids: int
    field_hints: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]


def normalize_context_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = text.replace("&", " e ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify_context(value: Any) -> str:
    normalized = normalize_context_text(value)
    slug = re.sub(r"\s+", "_", normalized).strip("_")
    if not slug:
        return ""
    if slug[0].isdigit():
        slug = "campo_" + slug
    return slug[:72].rstrip("_")


def infer_contextual_type(
    *,
    label: Any = "",
    field_id: Any = "",
    placeholder: Any = "",
    default_value: Any = "",
    options: Iterable[Any] | None = None,
    current_type: Any = "",
) -> ResolvedValue | None:
    """Infer a field type from multiple weak signals.

    Existing specialized/native types are authoritative and therefore return
    ``None`` here; callers should keep them unchanged.
    """

    current = str(current_type or "").strip().casefold()
    if current and current not in {"text", "string", "input", "auto"}:
        return None

    option_values = [str(value).strip() for value in (options or []) if str(value).strip()]
    if option_values:
        return ResolvedValue("dropdown", "options", 1.0, "O controle possui opções configuradas.")

    samples = [
        str(placeholder or "").strip(),
        str(default_value or "").strip(),
    ]
    for sample in samples:
        if not sample:
            continue
        if _CPF_RE.match(sample):
            return ResolvedValue("cpf", "mask", 0.99, "Máscara/valor possui formato de CPF.")
        if _CNPJ_RE.match(sample):
            return ResolvedValue("cnpj", "mask", 0.99, "Máscara/valor possui formato de CNPJ.")
        if _EMAIL_RE.match(sample):
            return ResolvedValue("email", "example_value", 0.98, "Valor existente possui formato de e-mail.")
        if _PHONE_RE.match(sample):
            return ResolvedValue("phone", "example_value", 0.97, "Valor existente possui formato de telefone.")
        if _DATE_RE.match(sample):
            return ResolvedValue("date", "mask", 0.98, "Máscara/valor possui formato de data.")
        if _CURRENCY_RE.match(sample):
            return ResolvedValue("currency", "mask", 0.98, "Máscara/valor possui formato monetário.")

    context = f" {normalize_context_text(label)} {normalize_context_text(field_id)} "
    rules: tuple[tuple[str, tuple[str, ...], float], ...] = (
        ("cnpj", (" cnpj ",), 0.99),
        ("cpf", (" cpf ",), 0.99),
        ("email", (" email ", " e mail "), 0.98),
        ("phone", (" telefone ", " celular ", " whatsapp "), 0.97),
        ("cep", (" cep ", " codigo postal "), 0.97),
        ("date", (" data ", " vencimento ", " prazo final ", " proxima revisao "), 0.90),
        ("currency", (" valor ", " preco ", " montante ", " custo ", " orcamento "), 0.92),
        ("percentage", (" percentual ", " porcentagem ", " aliquota "), 0.94),
        ("integer", (" quantidade ", " numero de unidades ", " qtd "), 0.88),
        (
            "multiline",
            (" justificativa ", " descricao detalhada ", " observacao ", " fundamentacao ", " providencia "),
            0.88,
        ),
    )
    for field_type, needles, confidence in rules:
        if any(needle in context for needle in needles):
            return ResolvedValue(field_type, "semantic_label", confidence, "Tipo inferido pelo rótulo/identificador contextual.")
    return None


def resolve_field_metadata(
    field: Mapping[str, Any],
    *,
    used_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Fill missing field metadata conservatively and attach evidence.

    The function never replaces explicit/manual metadata. It only fills values
    that are absent or clearly generic automatically-derived text metadata.
    """

    result = dict(field)
    evidence = dict(result.get("context_evidence", {}) or {})
    used = used_ids if used_ids is not None else set()

    label = str(result.get("label", "") or "").strip()
    if not label:
        for key, source, confidence in (
            ("choice_group_label", "choice_group", 0.98),
            ("layout_group_label", "layout_group", 0.94),
            ("layout_row_label", "row_label", 0.92),
            ("layout_column", "column_header", 0.82),
            ("profile_key", "profile_key", 0.72),
        ):
            candidate = _clean_label(result.get(key, ""))
            if candidate:
                label = candidate
                result["label"] = label
                result.setdefault("label_source", "context_resolver")
                evidence["label"] = ResolvedValue(label, source, confidence, "Rótulo preenchido a partir do contexto estrutural disponível.").as_dict()
                break

    field_id = str(result.get("id", "") or "").strip()
    section = str(result.get("section", "") or "").strip()
    if not field_id and label:
        resolved_id = stable_context_id(label, section=section, field_type=result.get("type", "text"), used_ids=used)
        result["id"] = resolved_id
        result["id_source"] = "context_resolver"
        evidence["id"] = ResolvedValue(resolved_id, "label_and_section", 0.93, "Identificador estável criado a partir do rótulo e da seção.").as_dict()
        field_id = resolved_id
    elif field_id:
        used.add(field_id)

    type_resolution = infer_contextual_type(
        label=label,
        field_id=field_id,
        placeholder=result.get("placeholder", ""),
        default_value=result.get("default_value", result.get("example", "")),
        options=result.get("options", []),
        current_type=result.get("type", ""),
    )
    type_source = str(result.get("type_source", "") or "").strip().casefold()
    if type_resolution is not None and type_source not in {
        "manual",
        "explicit",
        "native_control",
        "native_pdf",
        "automatic_detection",
    }:
        current_type = str(result.get("type", "") or "").strip().casefold()
        if not current_type or current_type in {"text", "string", "input", "auto"}:
            result["type"] = type_resolution.value
            result["type_source"] = "context_resolver"
            evidence["type"] = type_resolution.as_dict()

    if label and not result.get("profile_identity"):
        identity = semantic_profile_identity(label=label, section=section, field_type=result.get("type", "text"))
        if identity:
            result["profile_identity"] = identity
            evidence["profile_identity"] = ResolvedValue(identity, "semantic_identity", 0.90, "Identidade portátil derivada de seção, rótulo e tipo.").as_dict()

    if evidence:
        result["context_evidence"] = evidence
        confidences = [float(item.get("confidence", 0.0)) for item in evidence.values() if isinstance(item, Mapping)]
        if confidences:
            result["context_confidence"] = round(sum(confidences) / len(confidences), 3)
        result["context_resolver_version"] = 3
    return result


def semantic_profile_identity(*, label: Any, section: Any = "", field_type: Any = "text") -> str:
    label_slug = slugify_context(label)
    if not label_slug:
        return ""
    section_slug = slugify_context(re.sub(r"^\s*\d+(?:\.\d+)*[.)]?\s*", "", str(section or "")))
    type_slug = slugify_context(field_type) or "text"
    if section_slug:
        return f"{section_slug}.{label_slug}:{type_slug}"
    return f"{label_slug}:{type_slug}"


def stable_context_id(
    label: Any,
    *,
    section: Any = "",
    field_type: Any = "text",
    used_ids: set[str] | None = None,
    fallback_index: int = 1,
) -> str:
    used = used_ids if used_ids is not None else set()
    label_slug = slugify_context(label)
    section_slug = slugify_context(re.sub(r"^\s*\d+(?:\.\d+)*[.)]?\s*", "", str(section or "")))
    type_slug = slugify_context(field_type) or "campo"

    if label_slug:
        generic = normalize_context_text(label) in {normalize_context_text(value) for value in _GENERIC_LABELS}
        if generic and section_slug:
            candidates = [f"{section_slug}.{label_slug}", label_slug]
        else:
            candidates = [label_slug]
            if section_slug:
                candidates.append(f"{section_slug}.{label_slug}")
    else:
        candidates = [f"auto_word.{type_slug}_{max(1, int(fallback_index)):02d}"]

    for candidate in candidates:
        if candidate not in used:
            used.add(candidate)
            return candidate

    base = candidates[-1]
    suffix = 2
    while f"{base}_{suffix}" in used:
        suffix += 1
    resolved = f"{base}_{suffix}"
    used.add(resolved)
    return resolved


def prepare_word_controls_with_context(source_path: Path | str, destination_path: Path | str) -> WordControlPreparation:
    """Create a working DOCX where unnamed native/legacy controls get stable IDs.

    The original file is never modified. Existing Word tags/names remain
    authoritative; contextual inference is only used when they are absent.
    """

    source = Path(source_path)
    destination = Path(destination_path)
    document = Document(str(source))
    resolver = _WordContextIndex(document)
    used_ids = resolver.existing_ids()

    changed = False
    auto_tagged = 0
    fallback_ids = 0
    hints: list[dict[str, Any]] = []
    hint_records: list[tuple[Any, dict[str, Any]]] = []

    for root in iter_unique_story_roots(document):
        for sdt in root.iter(qn("w:sdt")):
            properties = sdt.find(qn("w:sdtPr"))
            if properties is None:
                continue
            control_type, control_element = classify_native_control(properties)
            if control_type is None:
                continue

            native_options = read_dropdown_options(control_element) if control_type == "dropdown" else []
            context = resolver.resolve(sdt, control_type, options=native_options)
            field_id = get_control_identifier(sdt)
            generated = False
            if not field_id:
                field_id = stable_context_id(
                    context.label,
                    section=context.section,
                    field_type=control_type,
                    used_ids=used_ids,
                    fallback_index=auto_tagged + 1,
                )
                _set_modern_control_id(properties, field_id, context.label)
                changed = True
                generated = True
                auto_tagged += 1
                if not context.label:
                    fallback_ids += 1
            else:
                used_ids.add(field_id)

            options = usable_dropdown_options(native_options) if control_type == "dropdown" else []
            hint: dict[str, Any] = {
                "id": field_id,
                "type": control_type,
                "type_source": "native_control",
                "detection_source": "native_word",
                "context_resolver_version": 3,
            }
            if context.label:
                hint["label"] = context.label
                hint["label_source"] = context.label_source
            if context.section:
                hint["section"] = context.section
                hint["section_source"] = "document_context"
            if options:
                hint["options"] = options
            hint["context_evidence"] = context.evidence
            hint["context_confidence"] = context.confidence
            if generated:
                hint["id_source"] = "context_resolver"
                hint["auto_tagged"] = True
            resolved_hint = resolve_field_metadata(hint, used_ids=set(used_ids))
            hints.append(resolved_hint)
            hint_records.append((sdt, resolved_hint))

        # Legacy FORMCHECKBOX controls.
        for fld_char in root.iter(qn("w:fldChar")):
            ff_data = fld_char.find(qn("w:ffData"))
            if ff_data is None or ff_data.find(qn("w:checkBox")) is None:
                continue
            name = ff_data.find(qn("w:name"))
            existing = normalize_control_id(name.get(qn("w:val"), "")) if name is not None else ""
            context = resolver.resolve(fld_char, "checkbox")
            generated = False
            field_id = existing
            if not field_id:
                field_id = stable_context_id(
                    context.label,
                    section=context.section,
                    field_type="checkbox",
                    used_ids=used_ids,
                    fallback_index=auto_tagged + 1,
                )
                if name is None:
                    name = OxmlElement("w:name")
                    ff_data.insert(0, name)
                name.set(qn("w:val"), field_id)
                changed = True
                generated = True
                auto_tagged += 1
                if not context.label:
                    fallback_ids += 1
            else:
                used_ids.add(field_id)

            hint = {
                "id": field_id,
                "type": "checkbox",
                "type_source": "native_control",
                "detection_source": "native_word_legacy",
                "context_resolver_version": 3,
                "context_evidence": context.evidence,
                "context_confidence": context.confidence,
            }
            if context.label:
                hint["label"] = context.label
                hint["label_source"] = context.label_source
            if context.section:
                hint["section"] = context.section
                hint["section_source"] = "document_context"
            if generated:
                hint["id_source"] = "context_resolver"
                hint["auto_tagged"] = True
            resolved_hint = resolve_field_metadata(hint, used_ids=set(used_ids))
            hints.append(resolved_hint)
            hint_records.append((fld_char, resolved_hint))

    _annotate_native_checkbox_choice_groups(hint_records)

    if changed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(destination))
        output = destination
    else:
        output = source

    warnings: list[str] = []
    if auto_tagged:
        warnings.append(
            f"{auto_tagged} controle(s) do Word sem identificação receberam tags automaticamente a partir do contexto próximo."
        )
    if fallback_ids:
        warnings.append(
            f"{fallback_ids} controle(s) não possuíam rótulo confiável e receberam identificadores de fallback para revisão."
        )

    return WordControlPreparation(
        path=output,
        changed=changed,
        auto_tagged=auto_tagged,
        fallback_ids=fallback_ids,
        field_hints=tuple(hints),
        warnings=tuple(warnings),
    )


def build_word_control_context_map(document: Any) -> dict[str, dict[str, Any]]:
    """Return deterministic contextual metadata for native and legacy controls.

    Unnamed controls receive the same stable IDs that the preparation step will
    write into a working copy, allowing scanners and diagnostics to operate
    without treating missing Word developer metadata as fatal.
    """

    resolver = _WordContextIndex(document)
    used_ids = resolver.existing_ids()
    mapping: dict[str, dict[str, Any]] = {}
    mapping_records: list[tuple[Any, dict[str, Any]]] = []
    generated_count = 0

    for root in iter_unique_story_roots(document):
        for sdt in root.iter(qn("w:sdt")):
            properties = sdt.find(qn("w:sdtPr"))
            if properties is None:
                continue
            control_type, control_element = classify_native_control(properties)
            if control_type is None:
                continue
            native_options = read_dropdown_options(control_element) if control_type == "dropdown" else []
            context = resolver.resolve(sdt, control_type, options=native_options)
            field_id = get_control_identifier(sdt)
            generated = not bool(field_id)
            if not field_id:
                generated_count += 1
                field_id = stable_context_id(
                    context.label,
                    section=context.section,
                    field_type=control_type,
                    used_ids=used_ids,
                    fallback_index=generated_count,
                )
            else:
                used_ids.add(field_id)
            hint: dict[str, Any] = {
                "id": field_id,
                "type": control_type,
                "type_source": "native_control",
                "detection_source": "native_word",
                "context_resolver_version": 3,
                "context_evidence": context.evidence,
                "context_confidence": context.confidence,
            }
            if context.label:
                hint["label"] = context.label
                hint["label_source"] = context.label_source
            if context.section:
                hint["section"] = context.section
                hint["section_source"] = "document_context"
            if control_type == "dropdown":
                options = usable_dropdown_options(native_options)
                if options:
                    hint["options"] = options
            if generated:
                hint["id_source"] = "context_resolver"
                hint["auto_tagged"] = True
            mapping[_element_path(sdt)] = hint
            mapping_records.append((sdt, hint))

        for fld_char in root.iter(qn("w:fldChar")):
            ff_data = fld_char.find(qn("w:ffData"))
            if ff_data is None or ff_data.find(qn("w:checkBox")) is None:
                continue
            name = ff_data.find(qn("w:name"))
            field_id = normalize_control_id(name.get(qn("w:val"), "")) if name is not None else ""
            context = resolver.resolve(fld_char, "checkbox")
            generated = not bool(field_id)
            if not field_id:
                generated_count += 1
                field_id = stable_context_id(
                    context.label,
                    section=context.section,
                    field_type="checkbox",
                    used_ids=used_ids,
                    fallback_index=generated_count,
                )
            else:
                used_ids.add(field_id)
            hint = {
                "id": field_id,
                "type": "checkbox",
                "type_source": "native_control",
                "detection_source": "native_word_legacy",
                "context_resolver_version": 3,
                "context_evidence": context.evidence,
                "context_confidence": context.confidence,
            }
            if context.label:
                hint["label"] = context.label
                hint["label_source"] = context.label_source
            if context.section:
                hint["section"] = context.section
                hint["section_source"] = "document_context"
            if generated:
                hint["id_source"] = "context_resolver"
                hint["auto_tagged"] = True
            mapping[_element_path(fld_char)] = hint
            mapping_records.append((fld_char, hint))

    _annotate_native_checkbox_choice_groups(mapping_records)
    return mapping


@dataclass(frozen=True)
class _WordContext:
    label: str
    label_source: str
    section: str
    confidence: float
    evidence: dict[str, Any]


class _WordContextIndex:
    def __init__(self, document: Any) -> None:
        self.document = document
        self.section_by_paragraph: dict[str, str] = {}
        self._build_sections()

    def existing_ids(self) -> set[str]:
        ids: set[str] = set()
        for root in iter_unique_story_roots(self.document):
            for sdt in root.iter(qn("w:sdt")):
                value = get_control_identifier(sdt)
                if value:
                    ids.add(value)
            for fld_char in root.iter(qn("w:fldChar")):
                ff_data = fld_char.find(qn("w:ffData"))
                if ff_data is None:
                    continue
                name = ff_data.find(qn("w:name"))
                if name is None:
                    continue
                value = normalize_control_id(name.get(qn("w:val"), ""))
                if value:
                    ids.add(value)
        return ids

    def _build_sections(self) -> None:
        for root in iter_unique_story_roots(self.document):
            current = ""
            for paragraph in root.iter(qn("w:p")):
                text = _visible_text(paragraph)
                if _looks_like_section(paragraph, text):
                    current = _clean_section(text)
                self.section_by_paragraph[_element_path(paragraph)] = current

    def resolve(
        self,
        element: Any,
        control_type: str,
        *,
        options: Iterable[Any] | None = None,
    ) -> _WordContext:
        paragraph = _ancestor(element, qn("w:p"))
        section = self.section_by_paragraph.get(_element_path(paragraph), "") if paragraph is not None else ""
        candidates: list[ResolvedValue] = []

        if control_type == "dropdown":
            prompt_label = _dropdown_prompt_label(options)
            if prompt_label:
                candidates.append(
                    ResolvedValue(
                        prompt_label,
                        "dropdown_prompt",
                        0.97,
                        "Rótulo inferido pela opção inicial configurada na lista suspensa.",
                    )
                )

        if paragraph is not None:
            before = _text_before_descendant(paragraph, element)
            label = _label_candidate(before)
            if label:
                candidates.append(ResolvedValue(label, "same_paragraph_before", 0.99, "Texto imediatamente antes do controle."))

        cell = _ancestor(element, qn("w:tc"))
        if cell is not None:
            previous = _previous_cell(cell)
            if previous is not None:
                label = _label_candidate(_visible_text(previous))
                if label:
                    candidates.append(ResolvedValue(label, "adjacent_left_cell", 0.98, "Rótulo na célula imediatamente à esquerda."))

            if paragraph is not None:
                previous_paragraph = _previous_paragraph_in_cell(cell, paragraph)
                if previous_paragraph is not None:
                    label = _label_candidate(_visible_text(previous_paragraph))
                    if label:
                        candidates.append(ResolvedValue(label, "same_cell_previous", 0.91, "Texto anterior na mesma célula."))

            if control_type == "checkbox":
                next_cell = _next_cell(cell)
                if next_cell is not None:
                    label = _label_candidate(_visible_text(next_cell))
                    if label:
                        candidates.append(ResolvedValue(label, "adjacent_right_cell", 0.96, "Texto imediatamente à direita da caixa de seleção."))

            header = _column_header_for_cell(cell)
            if header:
                if not section and _SECTION_RE.match(re.sub(r"\s+", " ", header).strip()):
                    section = _clean_section(header)
                header_label = _strip_section_number_from_label(header) or header
                candidates.append(ResolvedValue(header_label, "column_header", 0.88, "Cabeçalho/linha estrutural acima do controle."))

        if paragraph is not None and control_type == "checkbox":
            after = _text_after_descendant(paragraph, element)
            label = _checkbox_option_label(after)
            if label:
                candidates.append(ResolvedValue(label, "same_paragraph_after", 0.995, "Texto imediatamente após a caixa de seleção."))

        if paragraph is not None:
            previous = _previous_flow_paragraph(paragraph)
            if previous is not None:
                label = _label_candidate(_visible_text(previous))
                if label:
                    candidates.append(ResolvedValue(label, "nearby_previous", 0.62, "Texto anterior próximo no documento."))

        candidates.sort(key=lambda item: item.confidence, reverse=True)
        chosen = candidates[0] if candidates else None
        label = chosen.value if chosen else ""
        label_source = chosen.source if chosen else "generated_fallback"
        confidence = chosen.confidence if chosen else 0.35
        evidence: dict[str, Any] = {}
        if chosen:
            evidence["label"] = chosen.as_dict()
        if section:
            evidence["section"] = ResolvedValue(section, "nearest_section", 0.95, "Seção mais próxima no fluxo do documento.").as_dict()
        return _WordContext(label, label_source, section, confidence, evidence)


def usable_dropdown_options(options: Iterable[Any] | None) -> list[str]:
    values = [str(value or "").strip() for value in (options or []) if str(value or "").strip()]
    if not values:
        return []
    first = re.sub(r"\s+", " ", values[0]).strip().rstrip(".:")
    if re.match(
        r"^(?:escolha|escolher|selecione|selecionar)\b",
        first,
        flags=re.IGNORECASE,
    ):
        values = values[1:]
    return values


def _checkbox_option_label(value: Any) -> str:
    text = _clean_label(value)
    if not text or _looks_like_fill(text):
        return ""
    normalized = normalize_context_text(text)
    if normalized in {"sim", "nao", "n a"}:
        return text
    # Checkbox/radio alternatives are often full administrative phrases and
    # legitimately end with punctuation. Unlike ordinary field labels, keep
    # them when they are still a local, bounded fragment.
    if len(text) <= 140:
        return text
    return ""


def _dropdown_prompt_label(options: Iterable[Any] | None) -> str:
    values = [str(value or "").strip() for value in (options or []) if str(value or "").strip()]
    if not values:
        return ""
    first = re.sub(r"\s+", " ", values[0]).strip().rstrip(".:")
    match = re.match(
        r"^(?:escolha|escolher|selecione|selecionar)\s+(?:(?:a|o|uma|um)\s+)?(.+)$",
        first,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    candidate = _clean_label(match.group(1))
    normalized = normalize_context_text(candidate)
    if normalized in {"opcao", "item", "valor", "campo"}:
        return ""
    return candidate


def _strip_section_number_from_label(value: Any) -> str:
    text = _clean_label(value)
    if not text:
        return ""
    return re.sub(r"^\s*\d+(?:\.\d+)*[.)]?\s*", "", text).strip()

def _annotate_native_checkbox_choice_groups(
    records: Iterable[tuple[Any, dict[str, Any]]],
) -> None:
    clusters: dict[str, list[tuple[Any, dict[str, Any]]]] = {}
    for element, hint in records:
        if str(hint.get("type", "")).strip().casefold() != "checkbox":
            continue
        cell = _ancestor(element, qn("w:tc"))
        if cell is None:
            continue
        clusters.setdefault(_element_path(cell), []).append((element, hint))

    for _cell_path, items in clusters.items():
        if not (2 <= len(items) <= 6):
            continue
        labels = [str(hint.get("label", "") or "").strip() for _element, hint in items]
        if not all(labels) or not _looks_like_exclusive_native_choices(labels):
            continue

        first_element, first_hint = items[0]
        group_label = _native_choice_group_label(first_element, first_hint)
        seed = group_label or str(first_hint.get("section", "") or "") or labels[0]
        group_id = "native_choice." + (slugify_context(seed) or "grupo")
        for _element, hint in items:
            hint["layout"] = "choice"
            hint["layout_group"] = group_id
            hint["group"] = group_id
            hint["selection"] = "single"
            hint["choice_required"] = True
            if group_label:
                hint["layout_group_label"] = group_label
                hint["choice_group_label"] = group_label
            hint.setdefault("context_evidence", {})["choice_group"] = ResolvedValue(
                group_id,
                "shared_native_checkbox_region",
                0.94,
                "Caixas de seleção vizinhas com alternativas semanticamente exclusivas foram agrupadas.",
            ).as_dict()


def _looks_like_exclusive_native_choices(labels: Iterable[Any]) -> bool:
    normalized = [normalize_context_text(value) for value in labels if normalize_context_text(value)]
    if len(normalized) < 2:
        return False
    simple = set(normalized)
    if simple <= {"sim", "nao", "n a"} and {"sim", "nao"} <= simple:
        return True

    has_negative = any(re.search(r"(?:^| )nao(?: |$)", value) for value in normalized)
    has_positive = any(not re.search(r"(?:^| )nao(?: |$)", value) for value in normalized)
    has_partial = any("parcial" in value for value in normalized)
    if not (has_negative and has_positive):
        return False

    stop = {
        "nao", "sim", "parcial", "parcialmente", "m", "o", "a", "os", "as",
        "no", "na", "nos", "nas", "de", "do", "da", "dos", "das", "e",
    }
    token_sets = [set(value.split()) - stop for value in normalized]
    if not token_sets or any(not tokens for tokens in token_sets):
        return False
    common = set.intersection(*token_sets)
    return len(common) >= 1 and (has_partial or len(common) >= 2)


def _native_choice_group_label(element: Any, hint: Mapping[str, Any]) -> str:
    paragraph = _ancestor(element, qn("w:p"))
    cell = _ancestor(element, qn("w:tc"))
    if paragraph is not None and cell is not None:
        previous = _previous_paragraph_in_cell(cell, paragraph)
        if previous is not None:
            candidate = _clean_label(_visible_text(previous))
            if candidate and candidate != str(hint.get("label", "") or "").strip():
                return candidate
    section = str(hint.get("section", "") or "").strip()
    return _strip_section_number_from_label(section) if section else ""


def _set_modern_control_id(properties: Any, field_id: str, label: str) -> None:
    tag = properties.find(qn("w:tag"))
    if tag is None:
        tag = OxmlElement("w:tag")
        properties.insert(0, tag)
    tag.set(qn("w:val"), field_id)
    if label:
        alias = properties.find(qn("w:alias"))
        if alias is None:
            alias = OxmlElement("w:alias")
            properties.insert(0, alias)
        if not str(alias.get(qn("w:val"), "")).strip():
            alias.set(qn("w:val"), label[:120])


def _element_path(element: Any) -> str:
    if element is None:
        return ""
    try:
        return str(element.getroottree().getpath(element))
    except Exception:
        return ""


def _ancestor(element: Any, tag: str) -> Any | None:
    current = element
    while current is not None:
        if current.tag == tag:
            return current
        current = current.getparent()
    return None


def _visible_text(element: Any) -> str:
    if element is None:
        return ""
    return "".join(
        node.text or ""
        for node in element.iter()
        if node.tag in {qn("w:t"), qn("w:instrText")}
    )


def _text_before_descendant(paragraph: Any, target: Any) -> str:
    pieces: list[str] = []
    found = False

    def walk(node: Any) -> None:
        nonlocal found
        for child in node.iterchildren():
            if child is target or _contains(child, target):
                if child is target:
                    found = True
                    return
                walk(child)
                if found:
                    return
                continue
            if found:
                return
            if child.tag in {qn("w:t"), qn("w:instrText")}:
                pieces.append(child.text or "")
            else:
                walk(child)
            if found:
                return

    walk(paragraph)
    return "".join(pieces)


def _text_after_descendant(paragraph: Any, target: Any) -> str:
    pieces: list[str] = []
    seen = False

    def walk(node: Any) -> None:
        nonlocal seen
        for child in node.iterchildren():
            if child is target:
                seen = True
                continue
            if _contains(child, target):
                walk(child)
                continue
            if child.tag in {qn("w:t"), qn("w:instrText")}:
                if seen:
                    pieces.append(child.text or "")
            else:
                walk(child)

    walk(paragraph)
    return "".join(pieces)


def _contains(parent: Any, descendant: Any) -> bool:
    current = descendant.getparent()
    while current is not None:
        if current is parent:
            return True
        current = current.getparent()
    return False


def _previous_cell(cell: Any) -> Any | None:
    sibling = cell.getprevious()
    while sibling is not None:
        if sibling.tag == qn("w:tc"):
            return sibling
        sibling = sibling.getprevious()
    return None


def _next_cell(cell: Any) -> Any | None:
    sibling = cell.getnext()
    while sibling is not None:
        if sibling.tag == qn("w:tc"):
            return sibling
        sibling = sibling.getnext()
    return None


def _previous_paragraph_in_cell(cell: Any, paragraph: Any) -> Any | None:
    paragraphs = [item for item in cell.iter(qn("w:p"))]
    try:
        index = paragraphs.index(paragraph)
    except ValueError:
        return None
    for candidate in reversed(paragraphs[:index]):
        if _label_candidate(_visible_text(candidate)):
            return candidate
    return None


def _column_header_for_cell(cell: Any) -> str:
    row = _ancestor(cell, qn("w:tr"))
    table = _ancestor(cell, qn("w:tbl"))
    if row is None or table is None:
        return ""
    rows = [child for child in table.iterchildren() if child.tag == qn("w:tr")]
    try:
        row_index = rows.index(row)
    except ValueError:
        return ""
    cells = [child for child in row.iterchildren() if child.tag == qn("w:tc")]
    try:
        cell_index = cells.index(cell)
    except ValueError:
        return ""
    for previous_row in reversed(rows[:row_index]):
        previous_cells = [child for child in previous_row.iterchildren() if child.tag == qn("w:tc")]
        if cell_index >= len(previous_cells):
            continue
        candidate = _label_candidate(_visible_text(previous_cells[cell_index]))
        if candidate:
            return candidate
    return ""


def _previous_flow_paragraph(paragraph: Any) -> Any | None:
    current = paragraph.getprevious()
    while current is not None:
        if current.tag == qn("w:p") and _label_candidate(_visible_text(current)):
            return current
        current = current.getprevious()
    return None


def _clean_label(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"[☐□☑☒✓✔]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" :：–—-\t\r\n")
    if not text or len(text) > 140:
        return ""
    return text


def _label_candidate(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    # Keep only the local visual fragment around a control.
    text = re.split(r"[\t\r\n]", text)[-1].strip()
    if ":" in text or "：" in text:
        text = re.split(r"[:：]", text)[-2 if re.split(r"[:：]", text)[-1].strip() == "" else 0]
    text = _clean_label(text)
    if not text or _looks_like_fill(text):
        return ""
    normalized = normalize_context_text(text)
    if normalized in {"selecione uma data", "selecione uma opcao", "escolher um item", "escolher uma opcao"}:
        return ""
    # Long complete prose is context/help, not a field label.
    if len(text) > 110 or (text.endswith((".", ";", "!")) and len(text.split()) > 8):
        return ""
    return text


def _looks_like_fill(value: str) -> bool:
    text = str(value or "").strip()
    return bool(_FILL_RE.match(text))


def _looks_like_section(paragraph: Any, text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return False
    if _SECTION_RE.match(cleaned):
        return True
    props = paragraph.find(qn("w:pPr"))
    if props is None:
        return False
    style = props.find(qn("w:pStyle"))
    style_value = normalize_context_text(style.get(qn("w:val"), "")) if style is not None else ""
    return style_value.startswith(("heading", "titulo", "title"))


def _clean_section(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.rstrip(":：").strip()
