from __future__ import annotations

import re
import tokenize
from typing import Any

from pint import UnitRegistry
from pint.errors import PintError

ureg: UnitRegistry = UnitRegistry()
Q_ = ureg.Quantity

# Everything pint's expression evaluator raises on a unit string it cannot
# read: 'mm/0' divides by zero, 'mm^0' cancels itself out of the registry
# lookup (KeyError), 'mm)' unbalances pint's own tokenizer, and a huge
# exponent overflows. Shared by the CLI option path and the JSON --input path
# so neither can leak a traceback.
UNIT_EVALUATION_ERRORS = (
    ArithmeticError,
    AssertionError,
    KeyError,
    PintError,
    TypeError,
    ValueError,
    tokenize.TokenError,
)

# A unit expression is unit names joined by * / · ** ^ with parentheses and
# exponents. Anything else is a character pint's preprocessor would silently
# normalize rather than reject: it deletes commas ('m,m' becomes 'mm'), strips
# quoted text and '#' comments (dropping their digits), and reads '%' as the
# number 0.01. Underscore appears inside canonical names like degree_Celsius.
_UNIT_PUNCTUATION = frozenset("*/^()·._+-")
_ASCII_DIGITS = frozenset("0123456789")

# An unparenthesized exponent is the one place a unit legitimately spells a
# number: 'm/s^2', 'm**-2', or 'mm^1e400' (left for the dimension gate). A
# leading-zero integer part ('mm^01') is excluded: it is not a Python numeric
# literal, so pint's own tokenizer reads it differently across interpreter
# versions ('mm^0' times 1 on 3.11, 'mm^1' on 3.12+); refusing it here gives
# one verdict everywhere.
_UNIT_EXPONENT = re.compile(
    r"(?:\*\*|\^)\s*[+-]?\s*(?:(?:0|[1-9][0-9]*)(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
)


def unit_expression_problem(unit: str) -> str | None:
    """Why this unit string may not reach pint's evaluator, or None.

    Both rules are checked on the string itself, so the verdict does not vary
    with any parser's token boundaries or the interpreter's tokenizer. A digit
    inside a unit name -- 'ft_H2O', 'inH2O' -- is not a number: pint's
    tokenizer needs a word boundary before digits to split them out, so a
    digit continuing an identifier can never carry a scale factor.
    """
    for character in unit:
        if (
            character.isalpha()
            or character == "°"
            or character.isspace()
            or character in _ASCII_DIGITS
            or character in _UNIT_PUNCTUATION
        ):
            continue
        return f"may not contain {ascii(character)}"
    # Balance is checked here, not left to pint, because pint's tokenizer
    # raises a different exception class for an unbalanced bracket on
    # Python 3.11 than on 3.12+, and the error contract must not vary with
    # the interpreter.
    depth = 0
    for character in unit:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return "has an unmatched ')'"
    if depth:
        return "has an unmatched '('"
    # The exponent is replaced with a space, not deleted: deleting '^0' out of
    # 'mm^01' would splice the leftover '1' onto 'mm' and read as a digit
    # continuing a name, and the space keeps the two apart.
    inside_name = False
    for character in _UNIT_EXPONENT.sub(" ", unit):
        if character.isalpha() or character == "_":
            inside_name = True
        elif character in _ASCII_DIGITS:
            if not inside_name:
                return "spells a number only in an unparenthesized exponent, as in 'm/s^2'"
        else:
            inside_name = False
    return None


def dimensionless_factor(quantity: Any) -> str | None:
    """Name a unit component that is itself a pure number, or None.

    pint admits named constants and ratios -- 'pi', 'ppm', 'percent' -- as
    components of a unit expression and folds them into the magnitude at
    conversion, so '2 pi mm' would quietly become 6.28 mm. Every quantity this
    package accepts is dimensional, so a dimensionless component is a number
    spelled as a name, not part of a unit.
    """
    # _units is the UnitsContainer of canonical component names to exponents;
    # pint keeps a scale-carrying component (exponent sign included) listed
    # there rather than folding it before conversion.
    for name in quantity.units._units:
        if Q_(1, name).dimensionless:
            return name
    return None


def require_quantity(value: Any, name: str) -> Any:
    if not hasattr(value, "to"):
        raise TypeError(f"{name} must be a Pint Quantity")
    return value


def magnitude(value: Any, unit: str) -> float:
    require_quantity(value, "value")
    return float(value.to(unit).magnitude)
