from __future__ import annotations

import pytest

from orchestrator.tools.calculator import CalculatorError, evaluate


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("2 ^ 10", 1024),
        ("15% of 2,340", 351),
        ("10 % 3", 1),
        ("50%", 0.5),
        ("7 / 2", 3.5),
        ("7 // 2", 3),
        ("-3 + +5", 2),
        ("sqrt(16) + abs(-2)", 6),
        ("round(pi, 2)", 3.14),
        ("max(1, 5, 3)", 5),
        ("12 \u00d7 49", 588),
    ],
)
def test_evaluates_arithmetic(expression: str, expected: float) -> None:
    assert evaluate(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd')",
        "(1).__class__",
        "[1, 2, 3]",
        "lambda: 1",
        "x + 1",
        "1 / 0",
        "9 ** 9 ** 9",
        "10 ** 200",
        "'a' * 3",
        "sqrt(-1)",
        "1 +",
        "a" * 400,
    ],
)
def test_rejects_unsafe_or_invalid(expression: str) -> None:
    with pytest.raises(CalculatorError):
        evaluate(expression)
