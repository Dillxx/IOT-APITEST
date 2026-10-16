"""WebSocket 请求、业务登录和心跳集中处理。
每条连接只有一个接收任务；等待者读取共享历史，不各自 recv；业务断言留在用例。
"""

import asyncio
from collections import deque
from dataclasses import dataclass
import json
from http.cookies import SimpleCookie
from collections.abc import Callable
from websockets.asyncio.client import connect
from common.evidence import Evidence, safe_url


class SessionClosed(RuntimeError):
    """连接已关闭或执行状态不确定时的异常，提醒调用者停止操作。"""

    pass


class MessageTimeout(TimeoutError):
    """在规定时间内没有找到目标消息时抛出，区别于正常的成功回包。"""

    pass


class HistoryExpired(RuntimeError):
    """等待所需的消息历史已经被缓存淘汰，不能继续可靠匹配。"""

    pass


@dataclass(frozen=True)
class Message:
    """收到的一条消息：sequence 是本地接收序号，payload 是解析后的报文字典。"""

    sequence: int
    payload: dict


class WebSocketClient:
    """每连接唯一接收任务；多个等待者共享历史，不会互相取走对方的消息。"""

    def __init__(self, settings, evidence: Evidence):
        """准备连接、限长消息缓存和条件变量，此时还没有建立网络连接。"""

        self.settings, self.evidence = settings, evidence
        self.url = settings.ws_url
        self.connect_timeout = settings.connect_timeout
        self.operation_lock = asyncio.Lock()
        self.heartbeat = None
        self.control_uncertain = False
        self.last_request_cursor = 0
        self.last_control_cursor = 0
        self.initial_state = None
        self.headers = dict(settings.ws_headers)
        if settings.ws_cookies:
            cookies = SimpleCookie()
            for key, value in settings.ws_cookies.items():
                cookies[key] = value
            self.headers["Cookie"] = "; ".join(item.OutputString() for item in cookies.values())
        self.socket = None
        self.reader = None

        # 限长队列满时淘汰最早消息，避免长连接无限占用内存。
        self.messages = deque(maxlen=settings.history_limit)

        # 条件变量用于新消息到达时唤醒等待者，不需要反复定时轮询。
        self.condition = asyncio.Condition()
        self.sequence = 0
        self.failure = None
        self.closing = False

    @property
    def cursor(self) -> int:
        """返回当前最新接收序号；发送前记录它，可排除之前已经收到的消息。"""

        return self.sequence

    async def open(self):
        """建立连接、启动后台任务，并执行环境对应的业务登录和身份核对。"""

        if self.socket is not None:
            raise RuntimeError("Session already opened")
        self.socket = await connect(
            self.url, open_timeout=self.connect_timeout,
            close_timeout=2, proxy=None, max_size=2 * 1024 * 1024,
            additional_headers=self.headers,
        )
        self.evidence.record("ws_open", url=safe_url(self.url), headers=self.headers)

        # 启动后台接收任务；主用例仍可继续发送指令和等待结果。
        self.reader = asyncio.create_task(self._receive(), name="iot-ws-reader")
        self.heartbeat = asyncio.create_task(self._keep_alive(), name="iot-business-heartbeat")
        try:
            login = await self.request({"actioncode": "login", "data": self.settings.mac})
            if login.get("return") != 0:
                raise AssertionError("WebSocket login rejected")
            info = await self.request({"actioncode": "push_control_info", "data": ""})
            if info.get("return") != 0:
                raise AssertionError("WebSocket device information rejected")
            data = info.get("data", {})
            if data.get("mac", "").lower() != self.settings.mac.lower():
                raise AssertionError("WebSocket connection target MAC mismatch")
            if data.get("device_type") != self.settings.model:
                raise AssertionError("WebSocket connection target model mismatch")
        except BaseException:
            await self.close()
            raise

    async def send(self, body: dict):
        """将已构造的字典编码为 JSON 并发送；发送异常时通知等待者，避免继续等待。"""

        if self.failure or self.closing or self.socket is None:
            raise SessionClosed(self.failure or "Session is not open")
        self.evidence.record("ws_sent", payload=body)
        try:

            # await 在等待网络时让出执行权，让接收任务和心跳继续运行。
            await self.socket.send(json.dumps(body, ensure_ascii=False))
        except Exception:
            await self.fail("WebSocket send failed; command outcome is uncertain")
            raise SessionClosed(self.failure) from None

    async def _receive(self):
        """唯一的后台接收循环：解析、保存、记录消息，并唤醒条件等待者。"""

        try:
            async for raw in self.socket:
                try:
                    body = json.loads(raw)
                    if not isinstance(body, dict):
                        raise ValueError("Expected object message")
                except (ValueError, UnicodeDecodeError):
                    self.evidence.record("protocol_error", reason="Invalid JSON object")
                    await self.fail("Invalid WebSocket message")
                    return
                async with self.condition:
                    """这里递增的是本地接收序号，不是服务器提供的请求流水号。"""

                    self.sequence += 1
                    self.messages.append(Message(self.sequence, body))
                    self.evidence.record("ws_received", message_sequence=self.sequence, payload=body)

                    # 唤醒所有等待者检查共享历史；消息不会被某个等待者独占取走。
                    self.condition.notify_all()

        # 测试清理会主动取消任务；取消应继续传播，不能当成网络故障吞掉。
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.fail("WebSocket receive failed; command outcome is uncertain")
        finally:
            if not self.closing:
                await self.fail("WebSocket disconnected; command outcome is uncertain")

    async def fail(self, reason: str):
        """记录第一次连接失败，并唤醒所有等待任务，让它们立即知道连接不可用。"""

        async with self.condition:
            """在条件锁内检查或更新共享消息历史。"""

            if self.failure is None:
                self.failure = reason
                self.evidence.record("failure", reason=reason)

            # 唤醒所有等待者检查共享历史；消息不会被某个等待者独占取走。
            self.condition.notify_all()

    async def wait(self, predicate: Callable[[dict], bool], after: int,
                   timeout: float, description: str) -> Message:
        """查找 after 之后满足 predicate 的消息，并受 timeout 限制。
        predicate 是判断一条消息是否符合要求的函数；description 用于失败定位。
        """

        try:
            async with asyncio.timeout(timeout):
                """仅在配置超时内等待操作完成。"""

                async with self.condition:
                    """在条件锁内检查或更新共享消息历史。"""

                    while True:

                        # 等待起点已被缓存淘汰，历史证据不完整，必须明确失败。
                        if self.messages and after < self.messages[0].sequence - 1:
                            raise HistoryExpired(f"Message history expired while waiting for {description}")
                        if self.failure or self.closing:
                            raise SessionClosed(self.failure or "Session closed")
                        for message in self.messages:

                            # 同时符合“本次发送后的新消息”和“内容条件”，才返回结果。
                            if message.sequence > after and predicate(message.payload):
                                return message

                        # 等待时释放条件锁，接收任务保存新消息后再唤醒这里。
                        await self.condition.wait()
        except TimeoutError:
            self.evidence.record("failure", reason="timeout", waiting_for=description,
                                 after_message=after, timeout_seconds=timeout)
            raise MessageTimeout(f"Timed out waiting for {description} after message {after}") from None

    async def close(self):
        """关闭流程可重复调用；唤醒等待者，取消接收任务，再关闭实际连接。"""

        if self.closing:
            return
        self.closing = True
        async with self.condition:
            """唤醒所有等待者检查共享历史；消息不会被某个等待者独占取走。"""

            self.condition.notify_all()
        tasks = [task for task in (self.reader, self.heartbeat) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:

            # 等待取消真正完成，避免用例结束后仍残留后台任务。
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.socket is not None:
            await self.socket.close()
        self.evidence.record("ws_close")


    def envelope(self, request_data):
        """补齐环境公共字段；case 显式传入的字段优先，不限制业务输入类型。"""

        return {
            "company": self.settings.company, "device_name": self.settings.device_name,
            "platform": self.settings.platform, "token": self.settings.token,
            "sign": self.settings.ws_sign, "return": 0,
            "return_message": "success", "lang": self.settings.lang,
            **request_data,
        }

    async def request(self, request_data, *, timeout=None, match=None):
        """发送一个业务请求，返回原始回包；成功码与返回值由用例断言。
        默认按 actioncode 匹配，可提供 match 处理特殊协议；同连接请求串行。
        """

        action = request_data["actioncode"]
        is_control = action not in {"login", "push_control_info", "heartbeat", "edudevice_get_state"}
        async with self.operation_lock:
            """持锁直到对应回包到达，避免并发请求混淆响应。"""

            if self.control_uncertain and is_control:
                raise SessionClosed("Previous control failed; re-establish and verify the session before another control")
            cursor = self.cursor
            self.last_request_cursor = cursor
            if is_control:
                self.last_control_cursor = cursor
            try:
                await self.send(self.envelope(request_data))
                reply = await self.wait(
                    match or (lambda body: body.get("actioncode") == action), cursor,
                    timeout if timeout is not None else self.settings.reply_timeout, action,
                )
                return reply.payload
            except BaseException:
                if is_control:
                    self.control_uncertain = True
                await self.fail("Request failed; connection must be re-established before further requests")
                raise

    async def wait_for_state(self, expected, *, timeout=None, after=None):
        """从最近控制发送前的游标查找目标推送，允许状态先于控制回包到达。"""

        def matches(body):
            """只匹配成功状态消息，字段的类型和值均须一致。"""

            state = body.get("data")
            return (body.get("actioncode") == "edudevice_get_state"
                    and body.get("return") == 0 and isinstance(state, dict)
                    and all(type(state.get(key)) is type(value) and state[key] == value
                            for key, value in expected.items()))

        async with self.operation_lock:
            """等待状态时仍保持同一连接上的业务操作串行。"""

            try:
                reply = await self.wait(matches, self.last_control_cursor if after is None else after,
                                        timeout if timeout is not None else self.settings.state_timeout,
                                        f"HDMI state = {expected}")
                return reply.payload["data"]
            except BaseException:
                self.control_uncertain = True
                await self.fail("State confirmation failed; control outcome is uncertain")
                raise

    async def _keep_alive(self):
        """独立发送业务心跳；接收仍由唯一 reader 负责。"""

        try:
            while True:
                await asyncio.sleep(self.settings.heartbeat_interval)
                await self.send(self.envelope({"actioncode": "heartbeat", "data": ""}))
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.fail("Application heartbeat failed")
