"""公共运行配置和设备工厂；不放 HDMI 数据或音量恢复逻辑。"""
from contextlib import AsyncExitStack
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import os
import uuid
import pytest
from clients.device import DeviceClient
from config.settings import load_settings
from mocks.device_server import MockDevice
from support.evidence import Evidence

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    """pytest 启动时注册项目参数；运行脚本只是把这些参数传给 pytest。"""
    parser.addoption("--live", action="store_true", help="Run the HDMI business case against a real terminal")
    parser.addoption("--iot-config", default=str(ROOT / "config" / "environments" / "test.toml"), help="Environment TOML")
    parser.addoption("--iot-data", default=str(ROOT / "testdata" / "audio" / "hdmi.json"), help="HDMI test input JSON")
    parser.addoption("--iot-artifacts", default=None, help="Unique directory for this run's evidence")


def pytest_configure(config):
    """在执行用例前检查真机凭据和并行限制，并确定本次证据目录。"""
    if config.getoption("--live"):
        # 在准备网络连接前检查凭据，缺失时不会访问真机。
        if not os.environ.get("IOT_TOKEN") or not os.environ.get("IOT_SIGN"):
            raise pytest.UsageError("--live requires IOT_TOKEN and IOT_SIGN environment variables; no credentials are stored in the project")
        if getattr(config.option, "numprocesses", None):
            raise pytest.UsageError("Live terminal control must run serially; disable xdist")
    config.iot_run_dir = (Path(config.getoption("--iot-artifacts"))
                          if config.getoption("--iot-artifacts") else ROOT / "artifacts" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]))


def pytest_report_header(config):
    """在控制台展示本地/真机模式和证据位置，方便确认这次运行的范围。"""
    mode = "LIVE: physical terminal commands enabled" if config.getoption("--live") else "LOCAL SIMULATOR: no physical terminal commands"
    return [mode, f"Evidence: {config.iot_run_dir}"]


@pytest.fixture
def settings(request):
    """fixture：按 --iot-config 读取设置，pytest 会自动把结果传入需要它的 fixture。"""
    return load_settings(Path(request.config.getoption("--iot-config")))


@pytest.fixture
def evidence(request):
    """fixture：以本次运行目录和用例名创建独立证据记录器。"""
    name = request.node.name.replace("/", "_").replace("\\", "_").replace(":", "_")
    return Evidence(request.config.iot_run_dir / name)


@pytest.fixture
async def device_factory(request, settings, evidence):
    """提供已核对并登录的客户端；退出时按相反顺序关闭设备连接和模拟服务。
    异常测试可注入 behavior/配置覆盖；业务测试由局部 fixture 调用。
    """
    async with AsyncExitStack() as resources:
        async def create(behavior=None, live=False, **overrides):
            if live and not request.config.getoption("--live"):
                raise pytest.UsageError("Live device creation requires explicit --live")
            current = replace(settings, **overrides)
            simulator = None
            if not live:
                simulator = MockDevice(current.mac, current.model, behavior)
                ws_url = await simulator.start()
                resources.push_async_callback(simulator.close)
                current = replace(current, ws_url=ws_url, token="mock-token",
                                  sign="mock-sign", http_base_url="http://mock.local")
            device = DeviceClient(current, evidence,
                                  simulator.http_transport() if simulator else None)
            # 模拟器只用于本地故障测试检查，不是业务调用链中的容器。
            device.simulator = simulator
            resources.push_async_callback(device.close)
            await device.verify_device()
            await device.open()
            return device

        yield create
