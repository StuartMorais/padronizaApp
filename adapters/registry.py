"""Lazy workspace registry for the combined Nexo application."""
from adapters.contracts import WorkspaceFactory
from adapters.padroniza import create_padroniza
from adapters.checklist import create_checklist


WORKSPACE_FACTORIES: dict[str, WorkspaceFactory] = {
    "padroniza": create_padroniza,
    "checklist": create_checklist,
}
