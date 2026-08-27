from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class CreationStepper(QFrame):
    """Compact progress indicator for the guided new-template workflow."""

    STEPS = (
        ("Documento", "Escolher arquivo"),
        ("Campos", "Conferir o que muda"),
        ("Organizar", "Ajustar o formulário"),
        ("Concluir", "Revisar e criar"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("templateCreationStepper")
        self._step_frames: list[QFrame] = []
        self._number_labels: list[QLabel] = []
        self._title_labels: list[QLabel] = []
        self._subtitle_labels: list[QLabel] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        for index, (title, subtitle) in enumerate(self.STEPS):
            frame = QFrame()
            frame.setObjectName("templateCreationStep")
            frame.setProperty("stepState", "pending")
            frame_layout = QHBoxLayout(frame)
            frame_layout.setContentsMargins(9, 7, 9, 7)
            frame_layout.setSpacing(8)

            number = QLabel(str(index + 1))
            number.setObjectName("templateCreationStepNumber")
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setFixedSize(28, 28)

            text_widget = QWidget()
            text_layout = QVBoxLayout(text_widget)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(0)

            title_label = QLabel(title)
            title_label.setObjectName("templateCreationStepTitle")
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("templateCreationStepSubtitle")

            text_layout.addWidget(title_label)
            text_layout.addWidget(subtitle_label)
            frame_layout.addWidget(number)
            frame_layout.addWidget(text_widget, 1)

            self._step_frames.append(frame)
            self._number_labels.append(number)
            self._title_labels.append(title_label)
            self._subtitle_labels.append(subtitle_label)
            layout.addWidget(frame, 1)

        self.set_step(0)

    def set_step(self, step: int) -> None:
        step = max(0, min(int(step), len(self._step_frames) - 1))
        for index, frame in enumerate(self._step_frames):
            state = "current" if index == step else "done" if index < step else "pending"
            frame.setProperty("stepState", state)
            number = self._number_labels[index]
            number.setText("✓" if state == "done" else str(index + 1))
            # Dynamic-property QSS needs an explicit repolish after changing
            # state, otherwise some Qt themes keep the old appearance.
            for widget in (frame, number, self._title_labels[index], self._subtitle_labels[index]):
                style = widget.style()
                if style is not None:
                    style.unpolish(widget)
                    style.polish(widget)
                widget.update()
