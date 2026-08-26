from __future__ import annotations

import re

# The automatic detector is deliberately conservative. Explicit tags and Word
# form controls remain authoritative; this module only proposes additions.
X_PLACEHOLDER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:\(\d{2}\)\s*)?[Xx]{4,}(?:\s*[@./()\-]\s*[Xx]{2,})*(?![A-Za-z0-9])"
)
# Underscore masks are often short (``UF: __`` or ``Banco: ___``) and can
# include punctuation (``__/__/____``, ``___.___.___-__``).  Match the whole
# visual mask instead of only the longest underscore fragment so the inserted
# tag replaces the complete fill area.
UNDERSCORE_PLACEHOLDER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])_{2,}(?:\s*[/.:\-]\s*_{2,})*(?![A-Za-z0-9])"
)
ZERO_PHONE_PLACEHOLDER_PATTERN = re.compile(
    r"(?<!\d)\(\s*0{2}\s*\)\s*0{4,5}\s*-\s*0{4}(?!\d)"
)
ZERO_CPF_PLACEHOLDER_PATTERN = re.compile(
    r"(?<!\d)0{3}\s*\.\s*0{3}\s*\.\s*0{3}\s*-\s*0{2}(?!\d)"
)
# Monetary fill masks occur frequently in institutional documents as
# ``R$ XXX.XXX,XX``, ``R$ XXX.XXX.XX``, ``R$ 000.000,00`` or underline
# variants. Match the currency prefix together with the visual mask so the
# generated currency value does not leave a fixed ``R$`` behind and become
# ``R$ R$ 1.000,00``. Decimal/group punctuation is deliberately tolerant
# because hand-authored templates are not always consistent.
CURRENCY_PLACEHOLDER_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])R\$\s*"
    r"(?:"
    r"[Xx]{2,}(?:\s*[.,]\s*[Xx]{2,3}){0,3}"
    r"|0{2,}(?:\s*[.,]\s*0{2,3}){0,3}"
    r"|_{2,}(?:\s*[.,]\s*_{2,3}){0,3}"
    r")"
    r"(?![A-Za-z0-9])"
)
SAMPLE_EMAIL_PLACEHOLDER_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9._%+\-])"
    r"(?:contato|email|e-mail|exemplo|teste|usuario|usu[aá]rio|user|x{4,})"
    r"@(?:empresa|exemplo|example|dominio|dom[ií]nio|x{4,})"
    r"(?:\.[A-Za-zx]{2,}){1,3}"
    r"(?![A-Za-z0-9._%+\-])"
)
# Legacy/custom form documents often use a single-braced token such as
# ``{descricao.demanda}`` instead of Padroniza's authoritative ``{{...}}``
# syntax.  Treat these as assisted placeholders only when context strongly
# supports a field interpretation; ordinary prose using braces must remain
# static. Unicode word characters are accepted here because Brazilian forms
# frequently contain accents inside these legacy markers.
LEGACY_BRACED_PLACEHOLDER_PATTERN = re.compile(
    r"(?<!\{)\{([^\W\d_][\w.-]{0,95})\}(?!\})",
    re.UNICODE,
)
CHOICE_SEPARATOR_PATTERN = re.compile(r"^\s*OU\s*$", re.IGNORECASE)
INSTRUCTION_PATTERN = re.compile(
    r"^\s*(?:informar|informe|descrever|descreva|detalhar|detalhe|"
    r"indicar|indique|justificar|justifique|preencher|preencha)\b",
    re.IGNORECASE,
)
GENERIC_DROPDOWN_PATTERN = re.compile(
    r"^\s*(?:escolher|selecione|selecionar)\s+(?:um|uma)\s+(?:item|op[cç][aã]o)\.?\s*$",
    re.IGNORECASE,
)
CHECKBOX_LINE_PATTERN = re.compile(r"^\s*(?:☐|□|☑|☒|\(\s*\))\s*(.+?)\s*$")
CHECKBOX_TOKEN_PATTERN = re.compile(r"(?:☐|□|☑|☒|\(\s*\))")
# Checked Word forms are sometimes rendered as a bare check mark in an otherwise
# empty narrow cell instead of a Unicode checked-box character. Keep these
# glyphs restricted to the isolated-cell heuristic so they are not mistaken for
# ordinary mathematical or prose characters elsewhere in the document.
ISOLATED_CHECK_MARK_PATTERN = re.compile(r"(?:✓|✔|√)")
FOLLOWUP_AREA_PATTERN = re.compile(
    r"^\s*(?:observa[cç][aã]o(?:\s*/\s*justificativa)?|justificativa|"
    r"complemento|detalhamento|informa[cç][oõ]es? complementares?)\b",
    re.IGNORECASE,
)
SECTION_NUMBER_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s*")
LABEL_TAIL_PATTERN = re.compile(r"([^:;|]{2,120})\s*[:：]\s*$")


_SOURCE_LABELS = {
    "long_choice": "Alternativas separadas por OU",
    "repeatable_table": "Tabela com linhas repetíveis",
    "inline_placeholder": "Texto de preenchimento (XXXX ou sublinhado)",
    "legacy_placeholder": "Marcador legado entre chaves simples",
    "instruction": "Texto instrucional substituível",
    "empty_cell": "Célula vazia ao lado de um rótulo",
    "dropdown_prompt": "Indicação 'Escolher um item'",
    "sample_value": "Valor de exemplo após o rótulo",
    "checkbox_choice": "Opções com caixas de seleção",
    "checkbox_single": "Caixa de seleção independente",
    "consistency_repair": "Reparo por consistência do formulário",
    "prefilled_text": "Texto existente possivelmente editável",
    "terminal_prompt": "Prompt final após bloco de instruções",
    "colored_prompt": "Placeholder textual destacado por formatação",
    "colored_inline_choice": "Alternativas coloridas dentro do texto",
}

