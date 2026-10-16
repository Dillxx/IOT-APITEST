"""检查主要生产模块的导入方向，防止下层依赖业务或测试层。
AST 是 Python 语法树；这里只分析导入语句，不执行被检查模块。
"""
import ast
from pathlib import Path


def test_production_layers_keep_dependency_direction():
    """读取各生产层的导入语句，检查它们是否只依赖允许的下层模块。"""
    root = Path(__file__).resolve().parents[2]
    project_layers = {"clients", "config", "support", "tests", "mocks"}
    allowed = {
        "clients": {"clients", "config", "support"},
        "config": {"config"},
        "support": {"support"},
    }
    violations = []
    for layer, permitted in allowed.items():
        for file in (root / layer).rglob("*.py"):
            # 遍历语法树中的导入节点，只检查项目层间依赖，不执行模块。
            for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [node.module]
                for module in modules:
                    dependency = module.split(".")[0]
                    if dependency in project_layers and dependency not in permitted:
                        violations.append(f"{file.relative_to(root)} imports {module}")
    assert not violations, "\n".join(violations)
