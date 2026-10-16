"""按接口和类别显式读取 JSON，不猜测参数名，不改变输入或业务预期。"""

from copy import deepcopy
import json
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


def load_cases(file, group="normal"):
    """返回某类 case；只检查组织结构，负数、小数、空值等均原样保留。"""

    path = Path(file)
    if not path.is_absolute():
        path = DATA_ROOT / path
    with path.open(encoding="utf-8-sig") as stream:
        """读取数据副本，防止运行时修改污染后续子用例。"""

        groups = json.load(stream)
    if not isinstance(groups, dict):
        raise ValueError(f"Case data must be grouped by category: {path.name}")
    seen = set()
    for name, cases in groups.items():
        if not isinstance(cases, list):
            raise ValueError(f"Case group must be a list: {name}")
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
                raise ValueError("Every case requires a non-empty string id")
            if case["id"] in seen:
                raise ValueError(f"Duplicate case id: {case['id']}")
            seen.add(case["id"])
            if not isinstance(case.get("request"), dict) or not isinstance(case.get("expected"), dict):
                raise ValueError(f"Case requires request/expected objects: {case['id']}")
    if group not in groups or not groups[group]:
        raise ValueError(f"No cases in category {group}: {path.name}")
    return deepcopy(groups[group])
