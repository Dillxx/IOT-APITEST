"""共享连接按接口文件管理，每条 case 独立标记日志与恢复状态。"""

from copy import copy
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from common.evidence import Evidence
from common.http_client import HttpClient
from common.setup import read_state, restore_hdmi, verify_device
from common.websocket_client import WebSocketClient
from config.settings import load_settings
from mocks.device_server import MockDevice


@pytest.fixture(scope="session")
def settings(pytestconfig):
    """一次运行选择一份环境；各接口客户端使用自己的设置副本。"""

    return load_settings(pytestconfig.iot_config_path)


@pytest.fixture(scope="module")
def interface_evidence(request):
    """每接口文件保留完整流量，日志同时包含当前 case ID 和阶段。"""

    root = Path(__file__).resolve().parents[1]
    relative = Path(request.module.__file__).relative_to(root).with_suffix("")
    return Evidence(request.config.iot_run_dir / relative)


@pytest.fixture(autouse=True)
def case_context(request, interface_evidence):
    """跨后台接收任务共享可变的日志上下文，不依赖任务局部变量。"""

    interface_evidence.case_id = request.node.nodeid
    interface_evidence.phase = "setup"
    interface_evidence.record("case_start")
    yield
    interface_evidence.record("case_end")
    interface_evidence.case_id = None
    interface_evidence.phase = "connection"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def simulator(request, settings):
    """每个接口文件一台模拟器；真机模式不启动模拟服务。"""

    if request.config.getoption("--live"):
        yield None
        return
    device = MockDevice(settings.mac, settings.model)
    await device.start()
    try:
        yield device
    finally:
        await device.close()


@pytest.fixture(scope="module")
def connection_settings(settings, simulator):
    """模拟地址只覆盖当前接口，不改写环境文件。"""

    if simulator is None:
        return settings
    port = simulator.server.sockets[0].getsockname()[1]
    return replace(settings, ws_url=f"ws://127.0.0.1:{port}", http_base_url="http://mock.local",
                   token="mock-token", sign="mock-sign", ws_sign="mock-ws-sign")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def http_connection(connection_settings, simulator, interface_evidence):
    """同接口共享 HTTPX 客户端和会话，接口结束时关闭连接池。"""

    client = HttpClient(connection_settings, interface_evidence,
                        simulator.http_transport() if simulator else None)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture(loop_scope="module")
async def http(http_connection, case_context):
    """复用连接，同时隔离各 case 对默认 headers/cookies/params 的修改。"""

    headers = httpx.Headers(http_connection.headers)
    cookies = httpx.Cookies()
    for cookie in http_connection.cookies.jar:
        cookies.jar.set_cookie(copy(cookie))
    params = http_connection.params
    try:
        yield http_connection
    finally:
        http_connection.headers = headers
        http_connection.cookies = cookies
        http_connection.params = params


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def ws_connection(http_connection, connection_settings, interface_evidence):
    """同接口共享 WS；不确定结果后仅在重连核对原状态一致时允许后续测试。"""

    current = None

    async def acquire():
        """健康连接直接复用，失效连接不重放命令。"""

        nonlocal current
        if current and not current.failure and not current.closing and not current.control_uncertain:
            return current
        needs_recovery = current is not None and current.control_uncertain
        reference = getattr(current, "recovery_volume", None)
        if current:
            await current.close()
        await verify_device(http_connection, connection_settings)
        current = WebSocketClient(connection_settings, interface_evidence)
        await current.open()
        if needs_recovery:
            state = await read_state(current)
            if reference is None or type(state.get("HDMI_audio_status")) is not int or state["HDMI_audio_status"] != reference:
                current.control_uncertain = True
                current.recovery_volume = reference
                await current.close()
                pytest.fail("Previous control outcome uncertain; current state differs from baseline. Check device manually")
        return current

    try:
        yield acquire
    finally:
        if current:
            await current.close()


@pytest_asyncio.fixture(loop_scope="module")
async def ws(ws_connection, case_context):
    """提供可直接 request 的已登录连接；不隐藏任何业务用例的操作断言。"""

    return await ws_connection()


@pytest_asyncio.fixture(loop_scope="module")
async def initial_state(ws, connection_settings):
    """改状态的测试按需使用此 fixture，每条子用例分别记录和恢复原值。"""

    before = await read_state(ws)
    if not connection_settings.supports_hdmi:
        pytest.fail("Configured device does not support HDMI volume")
    original = before["HDMI_audio_status"]
    if type(original) is not int or not connection_settings.hdmi_min <= original <= connection_settings.hdmi_max:
        pytest.fail("Cannot safely restore the original HDMI volume; original value invalid")
    ws.initial_state = before
    ws.recovery_volume = original
    ws.evidence.record("checkpoint", operation="baseline", state=before)
    try:
        yield before
    finally:
        if connection_settings.restore_original:
            await restore_hdmi(ws, original)


@pytest_asyncio.fixture(loop_scope="module")
async def isolated_http(connection_settings, simulator, interface_evidence, case_context):
    """身份切换等特殊测试独立创建客户端，不污染普通接口共享会话。"""

    client = HttpClient(connection_settings, interface_evidence,
                        simulator.http_transport() if simulator else None)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture(loop_scope="module")
async def isolated_ws(isolated_http, connection_settings, interface_evidence):
    """登录和断线测试使用独立连接；不进行普通 HDMI 状态恢复。"""

    await verify_device(isolated_http, connection_settings)
    connection = WebSocketClient(connection_settings, interface_evidence)
    try:
        await connection.open()
        yield connection
    finally:
        await connection.close()
