from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class WorkspaceContext:
    return_home: Callable[[], None]


WorkspaceFactory = Callable[[WorkspaceContext], QWidget]
