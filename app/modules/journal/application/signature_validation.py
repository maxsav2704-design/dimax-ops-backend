from math import isfinite
from typing import NoReturn

from app.shared.domain.errors import ValidationError


def validate_signature_payload(payload: dict) -> None:
    def number(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and abs(value) <= 100000
            and isfinite(value)
        )

    def invalid() -> NoReturn:
        raise ValidationError("Signature must contain visible strokes and a valid viewport")

    if not isinstance(payload, dict):
        invalid()
    viewport = payload.get("viewport")
    if not isinstance(viewport, dict):
        invalid()
    width, height = viewport.get("width"), viewport.get("height")
    if not all(number(value) and 1 <= value <= 10000 for value in (width, height)):
        invalid()
    strokes = payload.get("strokes")
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 100:
        invalid()
    count = 0
    visible = False
    for stroke in strokes:
        if not isinstance(stroke, list) or len(stroke) < 2:
            invalid()
        count += len(stroke)
        if count > 20000:
            invalid()
        previous = None
        for point in stroke:
            if not isinstance(point, dict):
                invalid()
            x, y = point.get("x"), point.get("y")
            if not all(number(value) for value in (x, y)):
                invalid()
            current = (x, y)
            if previous is not None and current != previous:
                visible |= (0 <= x <= width and 0 <= y <= height) or (
                    0 <= previous[0] <= width and 0 <= previous[1] <= height
                )
            previous = current
    if not visible:
        invalid()
