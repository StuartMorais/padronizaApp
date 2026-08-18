from app.context_resolver import resolve_field_metadata


def test_context_resolver_fills_missing_id_type_and_profile_identity() -> None:
    resolved = resolve_field_metadata(
        {
            'label': 'CPF',
            'placeholder': '000.000.000-00',
            'type': 'text',
            'section': '1. Identificação',
        },
        used_ids=set(),
    )

    assert resolved['id'] == 'cpf'
    assert resolved['type'] == 'cpf'
    assert resolved['id_source'] == 'context_resolver'
    assert resolved['type_source'] == 'context_resolver'
    assert resolved['profile_identity'].endswith('cpf:cpf')
    assert resolved['context_resolver_version'] == 3
    assert resolved['context_evidence']['type']['source'] == 'mask'


def test_context_resolver_never_overrides_explicit_specialized_type() -> None:
    resolved = resolve_field_metadata(
        {
            'id': 'prioridade',
            'label': 'Prioridade',
            'type': 'dropdown',
            'type_source': 'native_control',
            'options': ['Normal', 'Alta', 'Crítica'],
        },
        used_ids=set(),
    )

    assert resolved['type'] == 'dropdown'
    assert resolved['type_source'] == 'native_control'


def test_context_resolver_uses_section_to_disambiguate_duplicate_labels() -> None:
    used: set[str] = set()
    first = resolve_field_metadata(
        {'label': 'Responsável', 'section': '3. Ocorrências', 'type': 'text'},
        used_ids=used,
    )
    second = resolve_field_metadata(
        {'label': 'Responsável', 'section': '5. Autorização', 'type': 'text'},
        used_ids=used,
    )

    assert first['id'] == 'ocorrencias.responsavel'
    assert second['id'] == 'autorizacao.responsavel'


def test_context_resolver_understands_currency_mask() -> None:
    resolved = resolve_field_metadata(
        {
            'label': 'Valor estimado',
            'placeholder': 'R$ XXX.XXX,XX',
            'type': 'text',
        },
        used_ids=set(),
    )
    assert resolved['type'] == 'currency'
