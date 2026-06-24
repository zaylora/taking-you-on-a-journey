from app.graph.nodes.collect_context import collect_context_node


async def test_node_wraps_context_under_key(fake_amap):
    fake_amap["search_poi"] = [{"name": "越秀公园", "poi_id": "G1"}]
    out = await collect_context_node(
        {"operations": [{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 2}}],
         "normalized_req": {"city": "广州"}}, None)
    assert "context" in out
    assert out["context"]["attractions"][0]["name"] == "越秀公园"


async def test_node_local_op_empty_context(fake_amap):
    out = await collect_context_node({"operations": [{"op": "reorder", "day": 1}]}, None)
    assert out["context"]["attractions"] == []
