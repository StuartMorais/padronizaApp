from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class WorkspaceContext:
    return_home: Callable[[], None]
    get_theme: Callable[[], str]


WorkspaceFactory = Callable[[WorkspaceContext], QWidget]
