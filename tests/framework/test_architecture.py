"""API、公共功能和配置不依赖测试或模拟服务。"""

import ast
from pathlib import Path


def test_common_code_does_not_import_tests_or_mocks():
    """只检查真正影响复用的依赖边界，不要求七层目录结构。"""

    root = Path(__file__).resolve().parents[2]
    violations = []
    for folder in ("api", "common", "config"):
        for file in (root / folder).rglob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = ([item.name for item in node.names] if isinstance(node, ast.Import)
                         else [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                if any(name.split(".")[0] in {"tests", "mocks"} for name in names):
                    violations.append(str(file.relative_to(root)))
    assert not violations, violations
