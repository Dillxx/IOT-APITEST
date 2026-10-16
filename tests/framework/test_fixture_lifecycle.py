"""独立 pytest 探针验证共享连接、每条恢复、异常后的重连及停止控制。"""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

pytestmark = pytest.mark.stability
ROOT = Path(__file__).resolve().parents[2]


def run_probe(tmp_path, source):
    """临时脚本继承正式 fixture；独立运行且自动删除，不访问真机。"""

    with TemporaryDirectory(prefix="_probe_", dir=ROOT / "tests" / "websocket") as directory:
        """将探针放在 tests 内以使用真实项目 fixture。"""

        probe = Path(directory) / "test_probe.py"
        probe.write_text('import pytest\npytestmark = pytest.mark.asyncio(loop_scope="module")\n' + source,
                         encoding="utf-8")
        env = {**os.environ, "PYTEST_ADDOPTS": "", "PYTHONIOENCODING": "utf-8"}
        env.pop("IOT_HDMI_VOLUME", None)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(probe), "-q", "-o", "addopts=",
             "--iot-artifacts", str(tmp_path / "evidence")],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    paths = list((tmp_path / "evidence").rglob("traffic.jsonl"))
    assert len(paths) == 1, result.stdout + result.stderr
    events = [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines()]
    return result, events


def controls(events):
    """从日志取出控制尝试值，核对没有重放。"""

    return [event["payload"]["data"] for event in events if event["type"] == "ws_sent"
            and event["payload"]["actioncode"] == "execute_HDMI_Audio_Control"]


@pytest.mark.parametrize("failure", ["assertion", "restore"])
def test_hdmi_fixture_restores_or_reports_failure_and_always_closes(tmp_path, failure):
    """断言失败后恢复；恢复被拒绝时报告错误并继续关闭。"""

    source = (
        'async def test_probe(ws, initial_state, simulator):\n'
        '    await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": 10})\n'
        + ('    assert False, "intentional business failure"\n' if failure == "assertion"
           else '    simulator.behavior.reject = True\n')
    )
    result, events = run_probe(tmp_path, source)
    assert result.returncode == 1, result.stdout + result.stderr
    assert any(event["type"] == "ws_close" for event in events)
    assert any(event["type"] == "http_close" for event in events)
    assert controls(events) == [10, 30]
    if failure == "assertion":
        assert "1 failed" in result.stdout
        assert any(event.get("operation") == "original HDMI volume restored" and event["value"] == 30
                   for event in events)
    else:
        assert "1 error" in result.stdout
        assert any(event["type"] == "restore_failed" and event["original_volume"] == 30 for event in events)


def test_connections_reused_but_each_case_restores_state_and_http_defaults(tmp_path):
    """两条数据复用同一连接，每条恢复音量及 HTTP cookie/header 修改。"""

    result, events = run_probe(tmp_path, '''
seen = []

@pytest.mark.parametrize("case", [{"id": "first", "volume": 10}, {"id": "second", "volume": 20}], ids=lambda c: c["id"])
async def test_probe(http, ws, initial_state, case):
    assert initial_state["HDMI_audio_status"] == 30
    assert "case_cookie" not in http.cookies
    assert "X-Case" not in http.headers
    if seen:
        assert seen[0] == (id(http), id(ws))
    seen.append((id(http), id(ws)))
    http.cookies.set("case_cookie", "temporary")
    http.headers["X-Case"] = case["id"]
    response = await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": case["volume"]})
    assert response["data"] == case["volume"]
''')
    assert result.returncode == 0 and "2 passed" in result.stdout, result.stdout + result.stderr
    assert controls(events) == [10, 30, 20, 30]
    assert sum(event["type"] == "ws_open" for event in events) == 1
    assert sum(event["type"] == "http_close" for event in events) == 1
    assert len({event["case_id"] for event in events if event["type"] == "case_start"}) == 2
    assert {event["phase"] for event in events} >= {"setup", "test", "teardown"}


@pytest.mark.parametrize("changed", [False, True])
def test_uncertain_connection_requires_reconnect_and_baseline_verification(tmp_path, changed):
    """状态一致才允许下一条；未知控制已改变状态时停止，禁止自动恢复或重放。"""

    failure_step = (
        '        simulator.behavior.omit_ack = True\n'
        '        with pytest.raises(MessageTimeout):\n'
        '            await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": 10}, timeout=0.1)\n'
        if changed else
        '        await ws.socket.close()\n'
        '        with pytest.raises(SessionClosed):\n'
        '            await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": 10})\n'
    )
    source = (
        'from common.websocket_client import MessageTimeout, SessionClosed\n'
        '@pytest.mark.parametrize("case", [1, 2])\n'
        'async def test_probe(ws, initial_state, simulator, case):\n'
        '    if case == 1:\n' + failure_step +
        '    else:\n'
        '        response = await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": 20})\n'
        '        assert response["data"] == 20\n'
    )
    result, events = run_probe(tmp_path, source)
    assert result.returncode == 1, result.stdout + result.stderr
    assert sum(event["type"] == "ws_open" for event in events) == 2
    if changed:
        assert "current state differs from baseline" in result.stdout
        assert controls(events) == [10]
    else:
        assert "2 passed" in result.stdout
        assert controls(events) in ([20, 30], [10, 20, 30])
