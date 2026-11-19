from warehouse.products import format_product_id, validate_product


def test_valid_product_has_no_errors():
    errors = validate_product("Hex Bolt M8", "Spare Part", "EA", 0.25, "Schmidt GmbH", 5)
    assert errors == []


def test_empty_name_is_rejected():
    errors = validate_product("   ", "Spare Part", "EA", 0.25, "Schmidt GmbH", 5)
    assert "Product name is required." in errors


def test_negative_cost_is_rejected():
    errors = validate_product("Hex Bolt M8", "Spare Part", "EA", -1, "Schmidt GmbH", 5)
    assert "Unit cost cannot be negative." in errors


def test_unknown_category_is_rejected():
    errors = validate_product("Hex Bolt M8", "Food", "EA", 0.25, "Schmidt GmbH", 5)
    assert len(errors) == 1


def test_lead_time_limits():
    assert "Lead time cannot be negative." in validate_product(
        "Hex Bolt M8", "Spare Part", "EA", 0.25, "Schmidt GmbH", -1)
    assert validate_product("Hex Bolt M8", "Spare Part", "EA", 0.25, "Schmidt GmbH", 365) == []
    assert len(validate_product("Hex Bolt M8", "Spare Part", "EA", 0.25, "Schmidt GmbH", 366)) == 1


def test_several_errors_reported_together():
    errors = validate_product("", "Spare Part", "EA", -5, "", 5)
    assert len(errors) == 3


def test_format_product_id():
    assert format_product_id(7) == "MAT-00007"