import pytest
from pydantic import ValidationError

from app.graph.nodes.refine_ops import Operation, Selector, RefinePlan


def test_operation_minimal_defaults():
    op = Operation(op="reorder", day=1)
    assert op.op == "reorder" and op.day == 1
    assert op.strategy == "optimize" and op.direction == "relax"
    assert op.selector is None and op.amount is None


def test_selector_defaults():
    s = Selector(by="ordinal", kind="meal", index=0)
    assert s.by == "ordinal" and s.kind == "meal" and s.index == 0
    assert Selector().by == "name" and Selector().index == -1


def test_refine_plan_parses_mixed_ops_from_dict():
    plan = RefinePlan(**{
        "operations": [
            {"op": "set_region", "day": 1, "area": "黄埔"},
            {"op": "set_pace", "day": 1, "direction": "relax"},
            {"op": "remove_poi", "day": 2, "selector": {"by": "name", "name": "武侯祠"}},
        ],
        "clarification": None,
    })
    assert [o.op for o in plan.operations] == ["set_region", "set_pace", "remove_poi"]
    assert plan.operations[0].area == "黄埔"
    assert plan.operations[2].selector.name == "武侯祠"


def test_refine_plan_empty_with_clarification():
    plan = RefinePlan(operations=[], clarification="你想把第几天换到哪里？")
    assert plan.operations == [] and plan.clarification.startswith("你想")


def test_unknown_op_rejected():
    with pytest.raises(ValidationError):
        Operation(op="teleport", day=1)
