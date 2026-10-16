"""真实收集过程验证协议、类别、多接口、数据 ID 和环境筛选。"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.stability
ROOT = Path(__file__).resolve().parents[2]


def collect(tmp_path, args, extra_env=None):
    """只收集不执行，不建立网络连接；清除调用终端的额外 pytest 参数。"""

    env = {**os.environ, "PYTEST_ADDOPTS": "", "PYTHONIOENCODING": "utf-8"}
    for key in ("IOT_TOKEN", "IOT_SIGN", "IOT_HDMI_VOLUME", "IOT_AUTH_HAR", "IOT_USERNAME", "IOT_PASSWORD"):
        env.pop(key, None)
    env.update({"IOT_USERNAME": "", "IOT_PASSWORD": ""})
    env.update(extra_env or {})
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(ROOT / "pyproject.toml"),
         "--collect-only", "-q", f"--iot-artifacts={tmp_path}", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    selection = tmp_path / "selection.json"
    nodes = json.loads(selection.read_text(encoding="utf-8"))["tests"] if selection.exists() else []
    return result, nodes


@pytest.mark.parametrize("args,expected", [
    (["--protocol", "http"], ["device_list_online"]),
    (["--protocol", "websocket"], ["hdmi_volume_10"]),
    (["tests/http/test_device_list.py", "tests/websocket/test_hdmi_volume.py"], ["device_list_online", "hdmi_volume_10"]),
    (["tests/workflows"], ["http_to_ws_hdmi_10"]),
    (["--category", "normal"], ["device_list_online", "hdmi_volume_10", "http_to_ws_hdmi_10"]),
    (["--case-id", "hdmi_volume_10"], ["hdmi_volume_10"]),
    (["--case-id", "device_list_online", "--case-id", "hdmi_volume_10"], ["device_list_online", "hdmi_volume_10"]),
    (["tests/websocket/test_hdmi_volume.py::test_set_volume_success[hdmi_volume_10]", "--env", "test"], ["hdmi_volume_10"]),
])
def test_execution_selection(tmp_path, args, expected):
    """选择范围精确对应测试节点，不意外执行其他协议或框架回归。"""

    result, nodes = collect(tmp_path, args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(nodes) == len(expected)
    assert {node.rsplit("[", 1)[-1].rstrip("]") for node in nodes} == set(expected)


@pytest.mark.parametrize("args,message", [
    (["--case-id", "missing"], "No matching cases"),
    (["--protocol", "http", "--case-id", "hdmi_volume_10"], "No matching cases"),
    (["--category", "rejected"], "No tests matched"),
    (["--env", "missing-environment"], "Environment file not found"),
    (["--env", "test", "--iot-config", "config/environments/test.toml"], "cannot be combined"),
    (["--iot-data", "old.json"], "were removed"),
    (["--live"], "Live login requires"),
    (["--live", "--env", "ts9260"], "Live login requires"),
    (["--live", "--auth-har", "old-login-source.har"], "HAR login input was removed"),
])
def test_invalid_selection_fails_explicitly(tmp_path, args, message):
    """无匹配、冲突、旧入口、缺失环境与凭据均明确报错。"""

    result, _ = collect(tmp_path, args)
    assert result.returncode == 4, result.stdout + result.stderr
    assert message in result.stdout + result.stderr


def test_old_volume_override_is_not_silently_applied(tmp_path):
    """不允许隐藏环境变量改变具名 case 的输入和预期。"""

    result, _ = collect(tmp_path, [], {"IOT_HDMI_VOLUME": "25"})
    assert result.returncode == 4 and "were removed" in result.stderr


def test_live_login_collection_accepts_account_credentials_without_static_tokens(tmp_path):
    """收集阶段只检查输入已配置，不在此时发出登录请求。"""

    result, nodes = collect(tmp_path, ["tests/websocket/test_hdmi_volume.py", "--env", "ts9260",
                                      "--live"], {"IOT_USERNAME": "mock-user", "IOT_PASSWORD": "mock-password"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(nodes) == 1 and "hdmi_volume_10" in nodes[0]
