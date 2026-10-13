import pytest

from chronology.tools.registry import Registry, Tool


def make_registry():
    reg = Registry()
    reg.register(Tool("add", "Add two ints",
                      {"type": "object", "properties": {"a": {"type": "integer"},
                                                        "b": {"type": "integer"}}},
                      lambda a, b: a + b))
    return reg


def test_specs_and_call():
    reg = make_registry()
    assert reg.specs(["add"])[0]["function"]["name"] == "add"
    assert reg.call("add", {"a": 2, "b": 3}) == 5


def test_duplicate_name_rejected():
    reg = make_registry()
    with pytest.raises(ValueError):
        reg.register(Tool("add", "", {}, lambda: None))
