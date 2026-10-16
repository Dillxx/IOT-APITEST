"""在独立 pytest 进程中验证真实 fixture 的失败恢复与清理，不连接真机。"""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

pytestmark = pytest.mark.stability
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("failure", ["assertion", "restore"])
def test_hdmi_fixture_restores_or_reports_failure_and_always_closes(tmp_path, failure):
    # 临时探针位于 audio 下，使用生产中相同的前后置；退出后自动移除。
    with TemporaryDirectory(prefix="_lifecycle_", dir=ROOT / "tests" / "audio") as directory:
        probe = Path(directory) / "test_probe.py"
        probe.write_text(
            'async def test_probe(hdmi_device):\n'
            '    await hdmi_device.set_volume(10)\n'
            + ('    assert False, "intentional business failure"\n' if failure == "assertion"
               else '    hdmi_device.simulator.behavior.reject = True\n'),
            encoding="utf-8",
        )
        env = {**os.environ, "PYTEST_ADDOPTS": "", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(probe), "-q", "-o", "addopts=",
             "--iot-artifacts", str(tmp_path / "evidence")],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    assert result.returncode == 1, result.stdout + result.stderr
    events = [json.loads(line) for line in
              (tmp_path / "evidence" / "test_probe" / "traffic.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(event["type"] == "ws_close" for event in events)
    controls = [event["payload"]["data"] for event in events
                if event["type"] == "ws_sent"
                and event["payload"]["actioncode"] == "execute_HDMI_Audio_Control"]
    assert controls == [10, 30]  # 只执行一次目标控制和一次恢复，没有自动重试。
    if failure == "assertion":
        assert "1 failed" in result.stdout
        assert any(event.get("operation") == "original HDMI volume restored"
                   and event["value"] == 30 for event in events)
    else:
        assert "1 error" in result.stdout
        assert any(event["type"] == "restore_failed" and event["original_volume"] == 30
                   for event in events)
