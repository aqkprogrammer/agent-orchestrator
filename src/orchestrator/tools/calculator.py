"""Safe arithmetic evaluator. Parses to an AST and walks a whitelist; never calls eval()."""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable
from typing import Any

MAX_EXPRESSION_LENGTH = 300
MAX_NODES = 200
MAX_EXPONENT = 1000
MAX_MAGNITUDE = 1e100


class CalculatorError(ValueError):
    pass


_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def normalize(expression: str) -> str:
    expr = expression.strip()
    expr = expr.replace("\u00d7", "*").replace("\u00f7", "/").replace("^", "**")
    expr = re.sub(r"(?<=\d),(?=\d{3}\b)", "", expr)  # thousands separators
    expr = re.sub(
        r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"(\1/100)*", expr, flags=re.IGNORECASE
    )  # "15% of 200"
    expr = re.sub(r"(\d+(?:\.\d+)?)%(?!\s*[\d(])", r"(\1/100)", expr)  # trailing percent
    return expr


def _check(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CalculatorError("Only numeric values are supported")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise CalculatorError("Result is not a finite number")
    if abs(value) > MAX_MAGNITUDE:
        raise CalculatorError("Result is too large")
    return value


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        return _check(node.value)
    if isinstance(node, ast.Name):
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise CalculatorError(f"Unknown name: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculatorError("Exponent too large")
        try:
            return _check(_BINOPS[type(node.op)](left, right))
        except ZeroDivisionError as exc:
            raise CalculatorError("Division by zero") from exc
        except OverflowError as exc:
            raise CalculatorError("Result is too large") from exc
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _check(_UNARY[type(node.op)](_eval(node.operand)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        func = _FUNCS.get(node.func.id)
        if func is None:
            raise CalculatorError(f"Unknown function: {node.func.id}")
        try:
            return _check(func(*[_eval(a) for a in node.args]))
        except (ValueError, TypeError) as exc:
            raise CalculatorError(f"Invalid arguments for {node.func.id}: {exc}") from exc
    raise CalculatorError(f"Unsupported syntax: {type(node).__name__}")


def evaluate(expression: str) -> int | float:
    """Evaluate an arithmetic expression safely."""
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError("Expression is too long")
    expr = normalize(expression)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"Invalid expression: {expression!r}") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise CalculatorError("Expression is too complex")
    result: int | float = _eval(tree)
    if isinstance(result, float):
        if result.is_integer() and abs(result) < 1e15:
            return int(result)
        return round(result, 10)
    return result
