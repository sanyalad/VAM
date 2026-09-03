"""Domain model for reliable PPR cell-color decisions."""

from dataclasses import dataclass, field
from enum import Enum


WHITE_EXCEL_COLORS = frozenset({16777215})


class ColorState(str, Enum):
    COLORED = "colored"
    UNCOLORED = "uncolored"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CellColorDecision:
    state: ColorState
    source: str
    color: int | None = None
    error: str = ""


def decide_excel_color(interior_color, display_color, use_display_format=True):
    """Classify one COM color read without converting failures to white."""
    source = "excel_display_format" if use_display_format else "excel_interior"
    selected = display_color if use_display_format else interior_color
    if selected is None:
        return CellColorDecision(
            ColorState.UNKNOWN,
            source,
            error="Excel не вернул цвет ячейки",
        )
    try:
        color = int(selected)
    except (TypeError, ValueError, OverflowError) as exc:
        return CellColorDecision(
            ColorState.UNKNOWN,
            source,
            error=f"Некорректное значение цвета: {selected!r} ({exc})",
        )
    state = (
        ColorState.UNCOLORED
        if color in WHITE_EXCEL_COLORS
        else ColorState.COLORED
    )
    return CellColorDecision(state, source, color=color)


def normalize_coord(coord):
    sheet, row, col = coord
    return str(sheet), int(row), int(col)


@dataclass
class ColorBatchResult:
    checked: set = field(default_factory=set)
    colored: set = field(default_factory=set)
    unknown: set = field(default_factory=set)
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return (
            not self.errors
            and not self.unknown
            and self.colored <= self.checked
        )

    def to_payload(self):
        return {
            "ok": self.ok,
            "checked": [list(c) for c in sorted(self.checked)],
            "colored": [list(c) for c in sorted(self.colored)],
            "unknown": [list(c) for c in sorted(self.unknown)],
            "errors": list(self.errors),
        }

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict):
            raise ValueError("Ожидался объект результата проверки цветов")
        return cls(
            checked={normalize_coord(c) for c in payload.get("checked", [])},
            colored={normalize_coord(c) for c in payload.get("colored", [])},
            unknown={normalize_coord(c) for c in payload.get("unknown", [])},
            errors=[str(e) for e in payload.get("errors", [])],
        )
