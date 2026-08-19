from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.repositories.local_data import JsonFileStore, now_iso


DEFAULT_GROUPS: list[dict[str, Any]] = [
    {
        "id": "company-information",
        "name": 'Informações da empresa',
        "description": 'Razão social, nome fantasia, CNPJ, e-mail e telefone.',
        "builtin": True,
        "fields": [
            {"id": "company.legal_name", "label": 'Razão social', "type": "text", "required": True, "section": 'Empresa / Fornecedor', "profile_key": "company.legal_name"},
            {"id": "company.trade_name", "label": 'Nome fantasia', "type": "text", "required": False, "section": 'Empresa / Fornecedor', "profile_key": "company.trade_name"},
            {"id": "company.cnpj", "label": "CNPJ", "type": "cnpj", "required": True, "section": 'Empresa / Fornecedor', "profile_key": "company.cnpj"},
            {"id": "company.email", "label": "E-mail", "type": "email", "required": False, "section": 'Empresa / Fornecedor', "profile_key": "company.email"},
            {"id": "company.phone", "label": "Telefone", "type": "phone", "required": False, "section": 'Empresa / Fornecedor', "profile_key": "company.phone"},
        ],
    },
    {
        "id": "address",
        "name": 'Endereço',
        "description": 'Logradouro, número, complemento, cidade, estado e CEP.',
        "builtin": True,
        "fields": [
            {"id": "address.street", "label": 'Logradouro', "type": "text", "required": True, "section": 'Endereço', "profile_key": "address.street"},
            {"id": "address.number", "label": 'Número', "type": "text", "required": True, "section": 'Endereço', "profile_key": "address.number"},
            {"id": "address.complement", "label": 'Complemento', "type": "text", "required": False, "section": 'Endereço', "profile_key": "address.complement"},
            {"id": "address.city", "label": 'Cidade', "type": "text", "required": True, "section": 'Endereço', "profile_key": "address.city"},
            {"id": "address.state", "label": 'Estado', "type": "text", "required": True, "section": 'Endereço', "profile_key": "address.state"},
            {"id": "address.cep", "label": "CEP", "type": "cep", "required": True, "section": 'Endereço', "profile_key": "address.cep"},
        ],
    },
    {
        "id": "process-information",
        "name": 'Informações do processo',
        "description": 'Número do processo, modalidade, objeto e data.',
        "builtin": True,
        "fields": [
            {"id": "process.number", "label": 'Número do processo', "type": "text", "required": True, "section": 'Processo / Contrato'},
            {"id": "process.modality", "label": 'Modalidade', "type": "text", "required": False, "section": 'Processo / Contrato'},
            {"id": "process.object", "label": 'Objeto', "type": "multiline", "required": True, "section": 'Processo / Contrato'},
            {"id": "process.date", "label": 'Data do processo', "type": "date", "required": True, "automatic": True, "section": 'Processo / Contrato'},
        ],
    },
    {
        "id": "signature",
        "name": 'Assinatura',
        "description": 'Nome, função e CPF do signatário.',
        "builtin": True,
        "fields": [
            {"id": "signatory.name", "label": 'Nome do signatário', "type": "text", "required": True, "section": 'Assinaturas', "profile_key": "signatory.name"},
            {"id": "signatory.role", "label": 'Função', "type": "text", "required": True, "section": 'Assinaturas', "profile_key": "signatory.role"},
            {"id": "signatory.cpf", "label": "CPF", "type": "cpf", "required": False, "section": 'Assinaturas', "profile_key": "signatory.cpf"},
        ],
    },
]


class FieldLibraryStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "field_library.json"
        self.store = JsonFileStore(self.path, [], kind="field_library")

    def list_groups(self) -> list[dict[str, Any]]:
        custom = self.store.read()
        if not isinstance(custom, list):
            custom = []
        groups = deepcopy(DEFAULT_GROUPS)
        groups.extend(item for item in custom if isinstance(item, dict))
        groups.sort(key=lambda item: str(item.get("name", "")).casefold())
        return groups

    def save_group(
        self,
        *,
        name: str,
        fields: list[dict[str, Any]],
        description: str = "",
    ) -> str:
        name = str(name).strip()
        if not name:
            raise ValueError('O nome do grupo de campos não pode ficar vazio.')
        if not fields:
            raise ValueError('Selecione pelo menos um campo para salvar.')

        custom = self.store.read()
        if not isinstance(custom, list):
            custom = []

        group_id = self._unique_id(name, custom)
        custom.append(
            {
                "id": group_id,
                "name": name,
                "description": str(description).strip(),
                "builtin": False,
                "fields": deepcopy(fields),
                "updated_at": now_iso(),
            }
        )
        self.store.write(custom)
        return group_id

    def delete_group(self, group_id: str) -> bool:
        custom = self.store.read()
        if not isinstance(custom, list):
            return False
        retained = [item for item in custom if str(item.get("id", "")) != str(group_id)]
        changed = len(retained) != len(custom)
        if changed:
            self.store.write(retained)
        return changed

    @staticmethod
    def _unique_id(name: str, groups: list[dict[str, Any]]) -> str:
        import re

        base = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "field-group"
        existing = {str(item.get("id", "")) for item in groups}
        candidate = base
        counter = 2
        while candidate in existing or any(str(item.get("id", "")) == candidate for item in DEFAULT_GROUPS):
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate
