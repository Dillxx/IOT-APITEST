"""本地模拟设备：提供 HTTP 列表返回和 WebSocket 消息交互。
通过 Behavior 开关注入错误与乱序，用于验证框架，而不是替代真实设备验收。
"""
import asyncio
from dataclasses import dataclass
import json
import httpx
from websockets.asyncio.server import serve


@dataclass
class Behavior:
    """模拟异常开关；全为 False 时正常返回，指定开关则制造对应故障。"""
    state_before_ack: bool = False
    reject: bool = False
    disconnect: bool = False
    omit_ack: bool = False
    omit_state: bool = False
    wrong_ack: bool = False
    wrong_query: bool = False
    wrong_device: bool = False
    invalid_json: bool = False
    change_other_audio: bool = False


class MockDevice:
    """一台本地模拟设备，维护报告状态并按请求返回消息。"""
    def __init__(self, mac: str, model: str, behavior=None):
        """初始化模拟状态、收到的请求列表以及测试用于等待的事件。"""
        self.mac, self.model = mac, model
        self.behavior = behavior or Behavior()
        self.state = {"HDMI_audio_status": 30, "IP_broadcast_audio_status": 70,
                      "MIC_audio_status": 30, "iHub_audio_status": 0,
                      "Recorder_audio_status": 0, "Desktop_mike_audio_status": 0}
        self.received = []
        self.server = None
        self.socket = None
        self.heartbeat_seen = asyncio.Event()
        self.control_seen = asyncio.Event()

    async def start(self):
        """只监听本机随机空闲端口，避免碰到真实服务器或固定端口冲突。"""
        # 端口 0 由操作系统分配空闲端口，本地用例不必竞争固定端口。
        self.server = await serve(self.handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}"

    async def close(self):
        """关闭模拟服务，并等待其连接清理完成。"""
        self.server.close()
        await self.server.wait_closed()

    async def emit(self, action: str, data, result=0):
        """构造模拟业务回包并发送，用于正常与异常场景。"""
        await self.socket.send(json.dumps({"device_name": "edu", "actioncode": action,
                                          "return": result, "return_message": "ok", "data": data}))

    async def handler(self, socket):
        """模拟服务的连接处理函数，根据 actioncode 更新状态或注入异常消息。"""
        self.socket = socket
        async for raw in socket:
            request = json.loads(raw)
            self.received.append(request)
            action, data = request["actioncode"], request["data"]
            if action == "login":
                await self.emit("login", {"clientId": "local-only"})
            elif action == "push_control_info":
                await self.emit(action, {"mac": "00:00:00:00:00:00" if self.behavior.wrong_device else self.mac,
                                         "device_type": self.model})
            elif action == "heartbeat":
                self.heartbeat_seen.set()
                await self.emit(action, "")
            elif action == "edudevice_get_state":
                state = dict(self.state)
                if self.behavior.wrong_query and self.control_seen.is_set():
                    state["HDMI_audio_status"] = 99
                await self.emit(action, state)
            elif action == "execute_HDMI_Audio_Control":
                self.control_seen.set()
                if self.behavior.disconnect:
                    await socket.close(code=1011, reason="simulated failure")
                    return
                if self.behavior.invalid_json:
                    await socket.send("{invalid-json")
                    continue
                if self.behavior.reject:
                    await self.emit(action, data, result=1)
                    continue
                self.state["HDMI_audio_status"] = data
                if self.behavior.change_other_audio:
                    self.state["MIC_audio_status"] = 88
                # 插入日志和心跳，验证客户端不会把任意下一条消息当作控制回包。
                await self.emit("control_latest_log", {"id": 1, "command": "HDMI volume changed"})
                await self.emit("heartbeat", "")
                # 故意改变消息顺序，模拟状态先于控制回包到达的现场情况。
                if self.behavior.state_before_ack and not self.behavior.omit_state:
                    await self.emit("edudevice_get_state", dict(self.state))
                if not self.behavior.omit_ack:
                    await self.emit(action, data + 1 if self.behavior.wrong_ack else data)
                if not self.behavior.state_before_ack and not self.behavior.omit_state:
                    await self.emit("edudevice_get_state", dict(self.state))

    def http_transport(self):
        """返回 HTTPX 模拟传输器，本地列表请求直接得到模拟响应，不联网。"""
        def handler(request):
            """检查调用的是列表接口，再返回包含当前模拟设备的列表报文。"""
            assert request.url.path == "/api/educontrol/lists"
            assert request.url.params["actioncode"] == "get_lists"
            return httpx.Response(200, json={"result": 200, "data": {"status": "success", "data": {
                "data": [{"mac": self.mac, "device_type": self.model, "online_status": 1}],
                "data_sum": 1}}})
        return httpx.MockTransport(handler)

