"""Storage and validation of optional temperature and equipment requests."""
import pytest

from app.extensions import db
from app.models.cargo import Cargo
from app.validators import ValidationError
from app.validators.cargo_validator import validate_cargo_handling


def test_unchecked_and_legacy_inputs_have_no_handling_request():
    assert validate_cargo_handling({}) == {
        "temperature_requirement": "", "special_container_type": ""}


@pytest.mark.parametrize("field,value", [
    ("temperature_requirement", "warm"), ("special_container_type", "invalid")])
def test_invalid_handling_value_is_rejected(field, value):
    with pytest.raises(ValidationError):
        validate_cargo_handling({field: value})


def test_requests_survive_multiple_cargo_lines_and_storage(create_shipment, cargo_input):
    items = [
        {**cargo_input, "temperature_requirement": "frozen", "special_container_type": "open_top"},
        {**cargo_input, "temperature_requirement": "chilled", "special_container_type": "unspecified"},
        {**cargo_input},
    ]
    shipment = create_shipment(cargo={"items": items})
    ids = [cargo.id for cargo in shipment.cargos]
    db.session.expire_all()
    cargos = [db.session.get(Cargo, cargo_id) for cargo_id in ids]
    assert cargos[0].to_dict()["temperature_requirement"] == "frozen"
    assert cargos[0].special_container_type == "open_top"
    assert cargos[0].handling_summary == "냉동 · 오픈탑"
    assert cargos[1].temperature_requirement == "chilled"
    assert cargos[1].special_container_type == "unspecified"
    assert cargos[2].handling_summary == ""


def test_handling_flags_are_independent_of_dangerous_goods(cargo_input):
    result = validate_cargo_handling({**cargo_input, "is_dangerous": False,
                                    "temperature_requirement": "frozen", "special_container_type": "tank"})
    assert result == {"temperature_requirement": "frozen", "special_container_type": "tank"}


def test_existing_database_gains_empty_handling_columns_without_changing_rows():
    from types import SimpleNamespace
    from sqlalchemy import create_engine, text
    from app import migrate_cargo_lines

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE cargos (id INTEGER PRIMARY KEY, line_no INTEGER, product_description TEXT)"))
        connection.execute(text("INSERT INTO cargos VALUES (1, 1, 'Existing cargo')"))
    database = SimpleNamespace(engine=engine)
    migrate_cargo_lines(database)
    migrate_cargo_lines(database)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT product_description, temperature_requirement, special_container_type FROM cargos")).one()
        assert tuple(row) == ("Existing cargo", "", "")
