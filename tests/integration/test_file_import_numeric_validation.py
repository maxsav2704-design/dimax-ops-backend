from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.projects.application.file_import_service import (
    _parse_price,
    _parse_quantity,
)


@pytest.mark.parametrize("value", ["1.5", "1,5", "1.00000000000000001", "1000.1", "NaN", "Infinity", "-Infinity", "0", "1001", "1e1000", "bad"])
def test_import_quantity_rejects_invalid_numbers(value):
    with pytest.raises(HTTPException) as error:
        _parse_quantity(value)
    assert error.value.status_code == 422


@pytest.mark.parametrize(("value", "expected"), [(None, 1), (" ", 1), ("1", 1), ("1.0", 1), ("2,0", 2), ("2e1", 20), ("1000", 1000)])
def test_import_quantity_preserves_whole_number_formats(value, expected):
    assert _parse_quantity(value) == expected


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity", "-0.01", "bad"])
def test_import_price_rejects_invalid_numbers(value):
    with pytest.raises(HTTPException) as error:
        _parse_price(value, Decimal("250"))
    assert error.value.status_code == 422


@pytest.mark.parametrize(("value", "expected"), [(None, "250"), (" ", "250"), ("0", "0"), ("0.01", "0.01"), ("12,50", "12.50"), ("1e3", "1000")])
def test_import_price_preserves_decimal_values(value, expected):
    assert _parse_price(value, Decimal("250")) == Decimal(expected)
