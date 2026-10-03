"""Lossless numeric and approval validation shared by all input boundaries."""

from __future__ import annotations

import math
import re
from typing import Annotated

from pydantic import BeforeValidator


def strict_int(value: object, name: str = "valor") -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, str) and not re.fullmatch(r"[+-]?[0-9]+", value.strip()):
            raise ValueError
        parsed = int(value)
        if not isinstance(value, (str, int)) and value != parsed:
            raise ValueError
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} deve ser inteiro.") from exc
    return parsed


def finite_float(value: object, name: str = "valor") -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} deve ser numerico e finito.") from exc
    return parsed


def strict_bool(value: object, name: str = "aprovacao") -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} deve ser booleano.")
    return value


IntegerInput = Annotated[int, BeforeValidator(strict_int)]
FiniteInput = Annotated[float, BeforeValidator(finite_float)]
ApprovalInput = Annotated[bool, BeforeValidator(strict_bool)]
