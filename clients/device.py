"""设备客户端：所有已实现的业务报文和操作集中在一个文件。
测试直接调用 set_volume/query_state；连接和恢复由 fixture 管理。
WebSocket 唯一接收循环位于 clients/websocket.py。
"""
import asyncio
import json
from config.settings import Settings
from support.evidence import Evidence
from clients.http import HttpClient
from clients.websocket import WsClient, SessionClosed, Message

# 业务指令与报文放在操作入口附近，修改一个接口无需跨协议/API/会话查找。
LOGIN = "login"
DEVICE_INFO = "push_control_info"
HEARTBEAT = "heartbeat"
GET_STATE = "edudevice_get_state"
HDMI_CONTROL = "execute_HDMI_Audio_Control"


def envelope(settings: Settings, action: str, data) -> dict:
    """为具体指令添加 company、Token 等公共字段；HTTP sign 与 WS sign 分开使用。"""
    return {
        "company": settings.company,
        "device_name": settings.device_name,
        "platform": settings.platform,
        "actioncode": action,
        "data": data,
        "token": settings.token,
        "sign": settings.ws_sign,
        "return": 0,
        "return_message": "success",
        "lang": settings.lang,
    }


def require_success(message):
    """按本项目 return=0 的语义检查回包；错误回包立即失败，不继续判定状态成功。"""
    if message.payload.get("return") != 0:
        raise AssertionError(f"Command {message.payload.get('actioncode')} rejected: return={message.payload.get('return')}")


LIST_PATH = "/api/educontrol/lists"


def list_params(settings: Settings) -> dict:
    """构造设备列表请求参数；data 字段是 JSON 字符串，不是普通嵌套查询参数。"""
    return {
        "company": settings.company,
        "device_name": settings.http_device_name,
        "sign": settings.sign,
        "actioncode": "get_lists",
        "data": json.dumps({"status": 0, "is_page": 0}, separators=(",", ":")),
    }


def parse_devices(body: dict) -> list[dict]:
    """先检查业务成功码，再从已捕获的嵌套结构取出设备列表。"""
    if body.get("result") != 200 or body.get("data", {}).get("status") != "success":
        raise AssertionError(f"Device list business failure: result={body.get('result')}")
    # 这是采集到的具体接口嵌套结构，不是所有 HTTP 接口的固定格式。
    return body["data"]["data"]["data"]


class DeviceClient:
    """设备操作入口：HTTP 核对、WS 登录、状态查询和 HDMI 控制集中在这里。"""
    def __init__(self, settings: Settings, evidence: Evidence, http_transport=None):
        """组装传输客户端、业务心跳和操作锁；control_uncertain 标记未知的控制结果。"""
        self.settings, self.evidence = settings, evidence
        self.http = HttpClient(settings.http_base_url, settings.http_timeout, evidence, http_transport)
        self.initial_state = None
        self.transport = WsClient(settings.ws_url, evidence,
                                  connect_timeout=settings.connect_timeout,
                                  history_limit=settings.history_limit)
        self.heartbeat = None
        # 同一设备共用操作锁，避免并发控制的回包和状态互相混淆。
        self.operation_lock = asyncio.Lock()
        self.control_uncertain = False
        self.closing = False

    async def open(self):
        """建立连接，发送携带 MAC 的业务登录，再查询设备信息并核对目标。
        任何准备步骤失败都会关闭会话并继续向上抛出异常。
        """
        await self.transport.open()
        self.heartbeat = asyncio.create_task(self._keep_alive(), name="iot-business-heartbeat")
        try:
            # 必须在发送前记录游标；服务器响应很快时也不会漏掉消息。
            cursor = self.transport.cursor
            await self.send(LOGIN, self.settings.mac)
            login = await self.wait_action(LOGIN, cursor, self.settings.reply_timeout)
            require_success(login)
            # 必须在发送前记录游标；服务器响应很快时也不会漏掉消息。
            cursor = self.transport.cursor
            # 业务登录后查询设备信息，再次核对 MAC 和型号。
            await self.send(DEVICE_INFO, "")
            info = await self.wait_action(DEVICE_INFO, cursor, self.settings.reply_timeout)
            require_success(info)
            data = info.payload["data"]
            if data.get("mac", "").lower() != self.settings.mac.lower():
                raise AssertionError("WebSocket connection target MAC mismatch")
            if data.get("device_type") != self.settings.model:
                raise AssertionError("WebSocket connection target model mismatch")
        except BaseException:
            await self.close()
            raise

    async def send(self, action: str, data):
        """把 action 与 data 补齐为项目报文，交给通用客户端发送。"""
        await self.transport.send(envelope(self.settings, action, data))

    async def wait_action(self, action: str, after: int, timeout: float) -> Message:
        """按 actioncode 等待消息；当前没有请求流水号，必须结合游标和串行操作使用。"""
        # lambda 是判断函数；这里只按 actioncode 匹配，还需要游标和串行操作配合。
        return await self.transport.wait(lambda body: body.get("actioncode") == action, after, timeout, action)

    async def _keep_alive(self):
        """按配置周期发送业务 heartbeat；失败时通知底层停止正常等待。"""
        try:
            while True:
                # sleep 用来控制心跳周期，不用于猜测设备操作成功。
                await asyncio.sleep(self.settings.heartbeat_interval)
                await self.send(HEARTBEAT, "")
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.transport.fail("Application heartbeat failed")

    async def close(self):
        """先取消业务心跳，再关闭底层连接；避免清理后仍有后台任务发送消息。"""
        if self.closing:
            return
        self.closing = True
        if self.heartbeat is not None:
            self.heartbeat.cancel()
            await asyncio.gather(self.heartbeat, return_exceptions=True)
        try:
            await self.transport.close()
        finally:
            await self.http.close()


    async def list_devices(self) -> dict:
        """调用列表接口并验证其业务结构，返回原业务报文给调用者。"""
        body = await self.http.request_json("GET", LIST_PATH, params=list_params(self.settings))
        parse_devices(body)
        return body

    async def verify_device(self):
        """目标 MAC 必须唯一，型号匹配且在线；成功时返回对应设备记录。"""
        records = parse_devices(await self.list_devices())
        # MAC 忽略大小写；唯一匹配后再检查型号与在线状态。
        matches = [item for item in records if item.get("mac", "").lower() == self.settings.mac.lower()]
        if len(matches) != 1:
            raise AssertionError("Target MAC must identify exactly one device")
        device = matches[0]
        if device.get("device_type") != self.settings.model:
            raise AssertionError("Target device model mismatch")
        if device.get("online_status") != 1:
            raise AssertionError("Target device is not online")
        return device


    async def _query_state(self) -> dict:
        """内部状态查询，不自行加锁；调用者必须已持有 operation_lock。
        返回报告状态；尚不能证明它来自终端实时物理测量。
        """
        cursor = self.transport.cursor
        await self.send(GET_STATE, "get_state")
        reply = await self.wait_action(
            GET_STATE, cursor, self.settings.state_timeout)
        require_success(reply)
        # 确认状态结构包含音量字段，不能把不完整数据当成成功。
        state = reply.payload.get("data")
        if not isinstance(state, dict) or "HDMI_audio_status" not in state:
            raise AssertionError("State query missing HDMI_audio_status")
        return state

    async def query_state(self) -> dict:
        """对外查询入口，通过操作锁避免查询和控制互相干扰。"""
        async with self.operation_lock:
            return await self._query_state()

    async def set_volume(self, volume: int) -> dict:
        """检查设备能力和参数，再串行执行控制；失败后标记会话控制结果不确定。"""
        settings = self.settings
        if not settings.supports_hdmi:
            raise ValueError("Configured device does not support HDMI volume")
        if type(volume) is not int or not settings.hdmi_min <= volume <= settings.hdmi_max:
            raise ValueError("HDMI volume must be an integer within the configured range")
        async with self.operation_lock:
            # 上次可能已经执行却没有回包，不能盲目继续发送新的控制。
            if self.control_uncertain:
                raise SessionClosed("Previous control failed; re-establish and verify the session before another control")
            try:
                return await self._set_volume(volume)
            except BaseException:
                self.control_uncertain = True
                raise

    async def _set_volume(self, volume: int) -> dict:
        """执行控制闭环：发送、回包、状态等待、主动查询和证据记录。
        由 set_volume 持锁调用；不能再次加同一把锁，否则会等待自己释放而卡住。
        """
        cursor = self.transport.cursor
        # 第 1 步：保存消息游标后发送控制，后续允许状态先于回包到达。
        await self.send(HDMI_CONTROL, volume)
        # 第 2 步：核对控制回包的成功码和返回值。
        ack = await self.wait_action(
            HDMI_CONTROL, cursor, self.settings.reply_timeout)
        require_success(ack)
        if type(ack.payload.get("data")) is not int or ack.payload["data"] != volume:
            raise AssertionError("HDMI control acknowledgement value mismatch")
        # 第 3 步：等待目标状态，下面的消息类型、成功码、结构和值需同时匹配。
        await self.transport.wait(
            lambda body: body.get("actioncode") == GET_STATE
            and body.get("return") == 0
            and isinstance(body.get("data"), dict)
            and type(body["data"].get("HDMI_audio_status")) is int
            and body["data"]["HDMI_audio_status"] == volume,
            cursor, self.settings.state_timeout, f"HDMI state = {volume}",
        )
        # 第 4 步：主动查询复核；外层已持锁，调用内部无锁方法避免重复加锁卡住。
        state = await self._query_state()
        actual = state.get("HDMI_audio_status")
        if type(actual) is not int or actual != volume:
            raise AssertionError(f"HDMI_audio_status expected integer {volume}, got {actual!r}")
        self.evidence.record("checkpoint", operation="HDMI volume verified", value=volume,
                                     evidence_level="reported state; physical execution not measured")
        return state
