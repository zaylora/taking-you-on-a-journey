# -*- coding: utf-8 -*-
"""Shared helpers for Agent tool argument coercion."""
import ast
import json
from typing import Any


def parse_jsonish_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return ast.literal_eval(text)
