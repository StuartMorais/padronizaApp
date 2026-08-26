from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TypeInference:
    field_type: str
    confidence: float
    reasons: tuple[str, ...] = field(default_factory=tuple)


_DATE_MASK_RE = re.compile(r"(?:_+|x+|0+)\s*/\s*(?:_+|x+|0+)\s*/\s*(?:_+|x+|0+)", re.IGNORECASE)
_PHONE_RE = re.compile(r"\(?\s*\d{2}\s*\)?\s*[-_x0\d .]{6,}", re.IGNORECASE)
_EMAIL_RE = re.compile(r"@|e[- ]?mail", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"\bR\$|\b(?:valor|pre[cç]o|custo|montante|or[cç]amento)\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"%|percent|porcent|al[ií]quota", re.IGNORECASE)
_YES_NO_RE = re.compile(r"\b(?:sim\s*/\s*n[aã]o|sim\s+ou\s+n[aã]o)\b", re.IGNORECASE)


def infer_field_type(
    label: str,
    *,
    section: str = "",
    preview: str = "",
    options: list[object] | None = None,
) -> TypeInference:
    """Infer field type from several independent signals.

    This function intentionally returns the evidence/confidence as well as the
    type.  Callers can keep ambiguous cases reviewable instead of silently
    treating a weak keyword hit as authoritative.
    """

    context = " ".join(str(value or "") for value in (label, section, preview)).strip()
    folded = context.casefold()
    reasons: list[str] = []

    if options and len(options) >= 2:
        return TypeInference("dropdown", 0.98, ("Há duas ou mais opções configuradas.",))
    if _YES_NO_RE.search(context):
        return TypeInference("dropdown", 0.94, ("O texto apresenta uma escolha SIM/NÃO.",))
    if "cnpj" in folded:
        return TypeInference("cnpj", 0.99, ("O contexto menciona CNPJ.",))
    if re.search(r"(?:^|\W)cpf(?:$|\W)", folded):
        return TypeInference("cpf", 0.99, ("O contexto menciona CPF.",))
    if re.search(r"(?:^|\W)cep(?:$|\W)", folded):
        return TypeInference("cep", 0.98, ("O contexto menciona CEP.",))
    if _EMAIL_RE.search(context):
        return TypeInference("email", 0.98, ("O contexto possui sinal de e-mail.",))
    if any(token in folded for token in ("telefone", "celular", "whatsapp", "fone")) or _PHONE_RE.search(preview):
        return TypeInference("phone", 0.95, ("O contexto possui sinal de telefone.",))
    if _DATE_MASK_RE.search(preview):
        return TypeInference("date", 0.99, ("A área possui máscara visual de data.",))
    if any(
        token in folded
        for token in (
            "data de ", " data ", "data:", "prazo", "vencimento", "validade",
            "previsão de entrega", "previsao de entrega", "previsão que os serviços",
            "previsao que os servicos", "início dos serviços", "inicio dos servicos",
            "assinatura eletrônica", "assinatura eletronica",
        )
    ):
        return TypeInference("date", 0.91, ("O contexto semântico indica uma data/prazo.",))
    if _PERCENT_RE.search(context):
        return TypeInference("percentage", 0.96, ("O contexto indica percentual.",))
    if _CURRENCY_RE.search(context):
        return TypeInference("currency", 0.93, ("O contexto indica valor monetário.",))
    if any(token in folded for token in ("quantidade", "qtd", "número de itens", "numero de itens")):
        return TypeInference("integer", 0.89, ("O contexto indica quantidade contável.",))
    if any(
        token in folded
        for token in (
            "justificativa", "descrição", "descricao", "observação", "observacao",
            "fundamentação", "fundamentacao", "providência", "providencia", "objeto",
            "detalhamento", "motivo", "notas adicionais",
        )
    ):
        return TypeInference("multiline", 0.86, ("O rótulo normalmente exige resposta textual longa.",))

    if len(str(preview or "").strip()) >= 140:
        return TypeInference("multiline", 0.68, ("A área textual é longa.",))
    return TypeInference("text", 0.60, ("Nenhum formato especializado ficou suficientemente claro.",))
