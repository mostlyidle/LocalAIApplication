"""Calculator tools for mathematical operations.

Provides a safe math evaluation tool that avoids eval() by using
a restricted expression parser.
"""

from __future__ import annotations

import math
import operator
from typing import Any

from langchain_core.tools import tool

_MAX_EXPRESSION_LENGTH = 1_000
_MAX_AST_NODES = 200
_MAX_EXPONENT = 1_000
_MAX_INTEGER_BITS = 16_384

# Safe operators for math evaluation
_SAFE_OPS: dict[str, Any] = {
    # Arithmetic
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "//": operator.floordiv,
    "%": operator.mod,
    "**": operator.pow,
    # Math functions
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
    "ceil": math.ceil,
    "floor": math.floor,
    "pow": math.pow,
}


def _safe_eval(expression: str) -> float | int:
    """Evaluate a math expression safely without using eval().

    Uses Python's ast module to parse and evaluate only numeric
    expressions and whitelisted math functions.

    Args:
        expression: A math expression string.

    Returns:
        The numeric result.

    Raises:
        ValueError: If the expression is invalid or uses disallowed operations.
    """
    import ast

    # Normalize
    expr = expression.strip()
    if len(expr) > _MAX_EXPRESSION_LENGTH:
        raise ValueError(f"Expression exceeds {_MAX_EXPRESSION_LENGTH} characters.")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression: {exc}") from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
        raise ValueError(f"Expression exceeds {_MAX_AST_NODES} syntax nodes.")

    def _eval_node(node: ast.AST) -> float | int:
        # Numbers
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value

        # Named constants (pi, e)
        if isinstance(node, ast.Name):
            if node.id in _SAFE_OPS and isinstance(_SAFE_OPS[node.id], float):
                return _SAFE_OPS[node.id]
            raise ValueError(f"Unknown variable: {node.id}")

        # Unary operators (+x, -x)
        if isinstance(node, ast.UnaryOp):
            operand = _eval_node(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +operand
            if isinstance(node.op, ast.USub):
                return -operand
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")

        # Binary operators (x + y, x * y, etc.)
        if isinstance(node, ast.BinOp):
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            op_map = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
                ast.Pow: operator.pow,
            }
            op_func = op_map.get(type(node.op))
            if op_func is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
                raise ValueError(f"Exponent exceeds the limit of {_MAX_EXPONENT}.")
            result = op_func(left, right)
            if isinstance(result, int) and result.bit_length() > _MAX_INTEGER_BITS:
                raise ValueError(f"Integer result exceeds {_MAX_INTEGER_BITS} bits.")
            return result

        # Function calls (sqrt(x), log(x), etc.)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Only simple function calls are allowed.")
            func_name = node.func.id
            if func_name not in _SAFE_OPS or not callable(_SAFE_OPS[func_name]):
                raise ValueError(f"Unknown function: {func_name}")
            args = [_eval_node(arg) for arg in node.args]
            if func_name == "pow" and len(args) == 2 and abs(args[1]) > _MAX_EXPONENT:
                raise ValueError(f"Exponent exceeds the limit of {_MAX_EXPONENT}.")
            return _SAFE_OPS[func_name](*args)

        # Expression wrapper
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)

        raise ValueError(f"Unsupported expression: {ast.dump(node)}")

    return _eval_node(tree)


@tool
def calculator_tool(expression: str) -> str:
    """Evaluate a mathematical expression safely.

    Supports basic arithmetic (+, -, *, /, //, %, **) and common math
    functions (sqrt, log, sin, cos, tan, abs, round, min, max, ceil, floor).
    Also supports constants pi and e.

    Examples:
        "2 + 3 * 4"        -> "14"
        "sqrt(144)"         -> "12.0"
        "log(100, 10)"      -> "2.0"
        "pi * 5**2"         -> "78.53981633974483"

    Args:
        expression: A mathematical expression to evaluate.

    Returns:
        The result as a string, or an error message.
    """
    try:
        result = _safe_eval(expression)
        # Format nicely
        if isinstance(result, float) and result == int(result):
            return str(int(result))
        return str(result)
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
        return f"Error: {exc}"


@tool
def unit_converter_tool(value: float, from_unit: str, to_unit: str) -> str:
    """Convert between common units of measurement.

    Supports length (m, km, mi, ft, in, cm, mm),
    weight (kg, g, lb, oz), temperature (C, F, K),
    and data (B, KB, MB, GB, TB).

    Args:
        value: The numeric value to convert.
        from_unit: The source unit (e.g., "km", "lb", "C").
        to_unit: The target unit (e.g., "mi", "kg", "F").

    Returns:
        The converted value as a formatted string.
    """
    # Conversion tables (to base unit)
    length_to_m = {
        "m": 1.0,
        "km": 1000.0,
        "mi": 1609.344,
        "ft": 0.3048,
        "in": 0.0254,
        "cm": 0.01,
        "mm": 0.001,
        "yd": 0.9144,
    }
    weight_to_kg = {
        "kg": 1.0,
        "g": 0.001,
        "lb": 0.453592,
        "oz": 0.0283495,
        "mg": 0.000001,
        "ton": 1000.0,
    }
    data_to_bytes = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }

    fu = from_unit.strip()
    tu = to_unit.strip()

    # Temperature (special case)
    temp_units = {"C", "F", "K"}
    if fu in temp_units and tu in temp_units:
        # Convert to Celsius first
        if fu == "F":
            celsius = (value - 32) * 5 / 9
        elif fu == "K":
            celsius = value - 273.15
        else:
            celsius = value

        # Convert from Celsius to target
        if tu == "F":
            result = celsius * 9 / 5 + 32
        elif tu == "K":
            result = celsius + 273.15
        else:
            result = celsius

        return f"{value} {fu} = {result:.4g} {tu}"

    # Length
    if fu in length_to_m and tu in length_to_m:
        meters = value * length_to_m[fu]
        result = meters / length_to_m[tu]
        return f"{value} {fu} = {result:.6g} {tu}"

    # Weight
    if fu in weight_to_kg and tu in weight_to_kg:
        kg = value * weight_to_kg[fu]
        result = kg / weight_to_kg[tu]
        return f"{value} {fu} = {result:.6g} {tu}"

    # Data
    if fu in data_to_bytes and tu in data_to_bytes:
        bytes_val = value * data_to_bytes[fu]
        result = bytes_val / data_to_bytes[tu]
        return f"{value} {fu} = {result:.6g} {tu}"

    return f"Cannot convert from {fu} to {tu}. Unsupported unit pair."


# All calculator tools for agent binding
calculator_tools = [calculator_tool, unit_converter_tool]
