from __future__ import annotations

import math


def object_value(value: object, label: str = "Value") -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object with string keys.")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def array_value(value: object, label: str = "Value", limit: int = 100) -> list[object]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{label} must be an array of at most {limit} items.")
    return list(value)


def text_value(value: object, label: str, limit: int = 4000, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(
            f"{label} must be {'a' if empty else 'a nonempty'} string of at most {limit} characters."
        )
    return value.strip()


def confidence_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Model confidence must be a number.")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("Model confidence must be between 0 and 1.")
    return result


def string_list(value: object, label: str, limit: int = 100) -> tuple[str, ...]:
    result = tuple(text_value(item, label, 160) for item in array_value(value, label, limit))
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must not contain duplicate IDs.")
    return result
