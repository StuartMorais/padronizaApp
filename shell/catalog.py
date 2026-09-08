from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    title: str
    subtitle: str
    description: str
    tags: tuple[str, ...]
    icon: str
    accent: str
    shortcut: str


MODULES = (
    ModuleSpec(
        key="padroniza", title="Padroniza", subtitle="Modelos, documentos e geração",
        description="Acesse modelos oficiais, gere documentos e mantenha a padronização do seu trabalho.",
        tags=("Modelos", "Documentos", "Geração", "Padronização"),
        icon="document", accent="blue", shortcut="Ctrl+2",
    ),
    ModuleSpec(
        key="checklist", title="Checklist", subtitle="Listas, revisão e scanner",
        description="Organize suas verificações, revise documentos e acompanhe cada etapa com clareza.",
        tags=("Listas", "Revisão", "Scanner", "Conformidade"),
        icon="checklist", accent="teal", shortcut="Ctrl+3",
    ),
)

PAGE_TITLES = {
    "home": "Início", **{item.key: item.title for item in MODULES},
    "settings": "Configurações", "about": "Sobre",
}
ACCENT_COLORS = {"blue": "#315FDB", "teal": "#087E79"}
