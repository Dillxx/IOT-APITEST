"""pytest 的环境和执行范围选项，不参与业务请求或断言。"""

from datetime import datetime
import json
import os
from pathlib import Path
import uuid

import pytest
from config.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    """HTTP、WS 和关联流程采用相同的执行入口。"""

    parser.addoption("--env", default=None, help="Environment name, default: test")
    parser.addoption("--iot-config", default=None, help="Explicit environment TOML path")
    parser.addoption("--live", action="store_true", help="Enable real device access explicitly")
    parser.addoption("--auth-har", default=None, help="Removed: configure local account credentials")
    parser.addoption("--protocol", choices=("http", "websocket"), default=None)
    parser.addoption("--category", choices=("normal", "rejected", "special"), default=None)
    parser.addoption("--case-id", action="append", default=[], help="Exact data id; can be repeated")
    parser.addoption("--iot-artifacts", default=None)
    parser.addoption("--iot-data", default=None, help="Removed: use per-interface data files and --case-id")


def pytest_configure(config):
    """先校验选项与真机条件，再确定本次输出目录；此阶段不联网。"""

    if config.getoption("--iot-data") is not None or "IOT_HDMI_VOLUME" in os.environ:
        raise pytest.UsageError("--iot-data/IOT_HDMI_VOLUME were removed; edit data/<protocol>/<interface>.json and select --case-id")
    if config.getoption("--auth-har") is not None or "IOT_AUTH_HAR" in os.environ:
        raise pytest.UsageError("HAR login input was removed; configure config/accounts.local.toml or IOT_USERNAME/IOT_PASSWORD")
    if config.getoption("--env") and config.getoption("--iot-config"):
        raise pytest.UsageError("--env and --iot-config cannot be combined")
    name = config.getoption("--env") or "test"
    if Path(name).name != name or not name:
        raise pytest.UsageError("--env must be an environment name, not a path")
    config.iot_config_path = (Path(config.getoption("--iot-config")) if config.getoption("--iot-config")
                              else ROOT / "config" / "environments" / f"{name}.toml")
    if not config.iot_config_path.is_file():
        raise pytest.UsageError(f"Environment file not found: {config.iot_config_path}")
    if config.getoption("--live"):
        settings = load_settings(config.iot_config_path)
        if settings.auth_mode == "login":
            if not settings.login_username or not settings.login_password:
                raise pytest.UsageError("Live login requires config/accounts.local.toml or IOT_USERNAME/IOT_PASSWORD; no network operation was started")
        elif not settings.token or not settings.sign:
            raise pytest.UsageError("--live requires IOT_TOKEN and IOT_SIGN, or configured login mode; no network operation was started")
        if getattr(config.option, "numprocesses", None):
            raise pytest.UsageError("Live terminal control must run serially; disable xdist")
    config.iot_run_dir = (Path(config.getoption("--iot-artifacts")) if config.getoption("--iot-artifacts")
                          else ROOT / "artifacts" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]))


def pytest_report_header(config):
    """在终端显示环境、模式和输出路径。"""

    return [f"Mode: {'LIVE' if config.getoption('--live') else 'LOCAL SIMULATOR'}",
            f"Environment: {config.iot_config_path}", f"Evidence: {config.iot_run_dir}"]


def pytest_collection_modifyitems(session, config, items):
    """各筛选条件取交集，ID 精确匹配；无匹配时明确失败。"""

    protocol, category = config.getoption("--protocol"), config.getoption("--category")
    ids = set(config.getoption("--case-id"))
    selected, deselected, found = [], [], set()
    for item in items:
        case = getattr(item, "callspec", None)
        data = case.params.get("case") if case else None
        case_id = data.get("id") if isinstance(data, dict) else None
        parts = Path(item.path).relative_to(ROOT).parts
        matches = (not protocol or len(parts) > 1 and parts[1] == protocol)
        matches = matches and (not category or item.get_closest_marker(category) is not None)
        matches = matches and (not ids or case_id in ids)
        (selected if matches else deselected).append(item)
        if matches and case_id:
            found.add(case_id)
    if session.testsfailed:
        return
    if ids - found:
        raise pytest.UsageError(f"No matching cases for IDs: {', '.join(sorted(ids - found))}")
    if not selected:
        raise pytest.UsageError("No tests matched the selected protocol/category/path/case IDs")
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
    config.iot_run_dir.mkdir(parents=True, exist_ok=True)
    (config.iot_run_dir / "selection.json").write_text(json.dumps(
        {"mode": "live" if config.getoption("--live") else "simulator",
         "environment": str(config.iot_config_path), "tests": [item.nodeid for item in selected]},
        ensure_ascii=False, indent=2), encoding="utf-8")


def pytest_runtest_call(item):
    """将共享连接的日志明确标记为当前 case 的执行阶段。"""

    evidence = item.funcargs.get("interface_evidence")
    if evidence:
        evidence.phase = "test"


def pytest_runtest_teardown(item):
    """恢复和关闭期间仍保留当前 case ID。"""

    evidence = item.funcargs.get("interface_evidence")
    if evidence:
        evidence.phase = "teardown"
