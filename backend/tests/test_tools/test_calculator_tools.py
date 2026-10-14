"""Tests for app.tools.calculator_tools."""

from __future__ import annotations

import math

import pytest

from app.tools.calculator_tools import _safe_eval, calculator_tool, unit_converter_tool


# =============================================================================
# _safe_eval — pure function tests
# =============================================================================


class TestSafeEval:
    """Unit tests for the restricted math expression evaluator."""

    # -- Basic arithmetic -------------------------------------------------

    def test_addition(self):
        assert _safe_eval("2 + 3") == 5

    def test_subtraction(self):
        assert _safe_eval("10 - 4") == 6

    def test_multiplication(self):
        assert _safe_eval("6 * 7") == 42

    def test_division(self):
        assert _safe_eval("15 / 4") == 3.75

    def test_floor_division(self):
        assert _safe_eval("15 // 4") == 3

    def test_modulo(self):
        assert _safe_eval("10 % 3") == 1

    def test_power(self):
        assert _safe_eval("2 ** 10") == 1024

    # -- Unary operators --------------------------------------------------

    def test_negative_number(self):
        assert _safe_eval("-5") == -5

    def test_positive_number(self):
        assert _safe_eval("+5") == 5

    # -- Constants --------------------------------------------------------

    def test_pi(self):
        assert _safe_eval("pi") == pytest.approx(math.pi)

    def test_e(self):
        assert _safe_eval("e") == pytest.approx(math.e)

    # -- Functions --------------------------------------------------------

    def test_sqrt(self):
        assert _safe_eval("sqrt(144)") == pytest.approx(12.0)

    def test_log_natural(self):
        assert _safe_eval("log(1)") == pytest.approx(0.0)

    def test_log_with_base(self):
        assert _safe_eval("log(100, 10)") == pytest.approx(2.0)

    def test_log10(self):
        assert _safe_eval("log10(1000)") == pytest.approx(3.0)

    def test_abs_negative(self):
        assert _safe_eval("abs(-42)") == 42

    def test_round(self):
        assert _safe_eval("round(3.14159, 2)") == pytest.approx(3.14)

    def test_min_max(self):
        assert _safe_eval("min(5, 3, 8)") == 3
        assert _safe_eval("max(5, 3, 8)") == 8

    def test_ceil_floor(self):
        assert _safe_eval("ceil(3.2)") == 4
        assert _safe_eval("floor(3.9)") == 3

    def test_sin_cos_tan(self):
        assert _safe_eval("sin(0)") == pytest.approx(0.0)
        assert _safe_eval("cos(0)") == pytest.approx(1.0)
        assert _safe_eval("tan(0)") == pytest.approx(0.0)

    # -- Complex expressions -----------------------------------------------

    def test_order_of_operations(self):
        assert _safe_eval("2 + 3 * 4") == 14

    def test_parenthesized(self):
        assert _safe_eval("(2 + 3) * 4") == 20

    def test_nested_functions(self):
        assert _safe_eval("sqrt(abs(-16))") == pytest.approx(4.0)

    def test_pi_expression(self):
        assert _safe_eval("pi * 5 ** 2") == pytest.approx(math.pi * 25)

    # -- Error cases -------------------------------------------------------

    def test_invalid_syntax(self):
        with pytest.raises(ValueError, match="Invalid expression"):
            _safe_eval("2 +")

    def test_unknown_variable(self):
        with pytest.raises(ValueError, match="Unknown variable"):
            _safe_eval("x + 1")

    def test_unknown_function(self):
        with pytest.raises(ValueError, match="Unknown function"):
            _safe_eval("exec('import os')")

    def test_division_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            _safe_eval("1 / 0")

    def test_empty_expression(self):
        with pytest.raises(ValueError):
            _safe_eval("")


# =============================================================================
# calculator_tool (LangChain tool wrapper)
# =============================================================================


class TestCalculatorTool:
    """Tests for the calculator_tool LangChain tool."""

    def test_simple_expression(self):
        result = calculator_tool.invoke({"expression": "2 + 3 * 4"})
        assert result == "14"

    def test_returns_int_for_whole_floats(self):
        result = calculator_tool.invoke({"expression": "sqrt(144)"})
        assert result == "12"

    def test_returns_float(self):
        result = calculator_tool.invoke({"expression": "1 / 3"})
        assert "0.333" in result

    def test_error_message_on_bad_input(self):
        result = calculator_tool.invoke({"expression": "foo + bar"})
        assert result.startswith("Error:")

    def test_error_on_division_by_zero(self):
        result = calculator_tool.invoke({"expression": "1 / 0"})
        assert result.startswith("Error:")

    def test_rejects_excessive_exponents(self) -> None:
        result = calculator_tool.invoke({"expression": "2**10000"})
        assert result.startswith("Error:")


# =============================================================================
# unit_converter_tool
# =============================================================================


class TestUnitConverterTool:
    """Tests for the unit_converter_tool LangChain tool."""

    # -- Length -----------------------------------------------------------

    def test_km_to_mi(self):
        result = unit_converter_tool.invoke({"value": 1.0, "from_unit": "km", "to_unit": "mi"})
        assert "km" in result
        assert "mi" in result
        # 1 km ≈ 0.6214 mi
        assert "0.62" in result

    def test_m_to_ft(self):
        result = unit_converter_tool.invoke({"value": 1.0, "from_unit": "m", "to_unit": "ft"})
        assert "3.28" in result

    # -- Weight -----------------------------------------------------------

    def test_kg_to_lb(self):
        result = unit_converter_tool.invoke({"value": 1.0, "from_unit": "kg", "to_unit": "lb"})
        assert "2.20" in result

    # -- Temperature ------------------------------------------------------

    def test_c_to_f(self):
        result = unit_converter_tool.invoke({"value": 100.0, "from_unit": "C", "to_unit": "F"})
        assert "212" in result

    def test_f_to_c(self):
        result = unit_converter_tool.invoke({"value": 32.0, "from_unit": "F", "to_unit": "C"})
        assert "0" in result

    def test_c_to_k(self):
        result = unit_converter_tool.invoke({"value": 0.0, "from_unit": "C", "to_unit": "K"})
        assert "273" in result

    # -- Data sizes -------------------------------------------------------

    def test_gb_to_mb(self):
        result = unit_converter_tool.invoke({"value": 1.0, "from_unit": "GB", "to_unit": "MB"})
        assert "1024" in result

    # -- Unsupported pair -------------------------------------------------

    def test_unsupported_conversion(self):
        result = unit_converter_tool.invoke({"value": 1.0, "from_unit": "kg", "to_unit": "km"})
        assert "Cannot convert" in result
