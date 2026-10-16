"""框架故障测试使用独立本地连接，不与正式接口共享被故意破坏的会话。"""

from contextlib import AsyncExitStack
from dataclasses import replace

import pytest
import pytest_asyncio

from common.evidence import Evidence
from common.http_client import HttpClient
from common.setup import connect_ws, verify_device
from common.websocket_client import WebSocketClient
from mocks.device_server import MockDevice


@pytest.fixture
def evidence(tmp_path, request):
    """故障注入各自保留证据，避免污染其他回归的日志。"""

    result = Evidence(tmp_path / "traffic")
    result.case_id = request.node.nodeid
    return result


@pytest_asyncio.fixture(loop_scope="function")
async def session_factory(settings, evidence):
    """只创建本地模拟连接，准备失败也关闭已经创建的全部资源。"""

    async with AsyncExitStack() as resources:
        """按 WS、HTTP、模拟服务的相反登记顺序清理。"""

        async def create(behavior=None, **overrides):
            """故障开关和超时仅影响这条框架回归。"""

            current = replace(settings, **overrides)
            simulator = MockDevice(current.mac, current.model, behavior)
            url = await simulator.start()
            resources.push_async_callback(simulator.close)
            current = replace(current, ws_url=url, http_base_url="http://mock.local",
                              token="mock-token", sign="mock-sign", ws_sign="mock-ws-sign")
            http = HttpClient(current, evidence, simulator.http_transport())
            resources.push_async_callback(http.aclose)
            await verify_device(http, current)
            ws = WebSocketClient(current, evidence)
            ws.simulator = simulator
            ws.http = http
            resources.push_async_callback(ws.close)
            await connect_ws(ws)
            return ws

        yield create
