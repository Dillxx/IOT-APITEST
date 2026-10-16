"""通用 WebSocket JSON 通信层。
每条连接只有一个接收任务；等待者从共享消息历史查找结果，不各自调用 recv。此层不认识 HDMI 或业务登录。
"""
import asyncio
from collections import deque
from dataclasses import dataclass
import json
from collections.abc import Callable
from websockets.asyncio.client import connect
from support.evidence import Evidence, safe_url


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


class WsClient:
    """每连接唯一接收任务；多个等待者共享历史，不会互相取走对方的消息。"""
    def __init__(self, url: str, evidence: Evidence, *, connect_timeout: float = 10, history_limit: int = 2000):
        """准备连接、限长消息缓存和条件变量，此时还没有建立网络连接。"""
        self.url, self.evidence = url, evidence
        self.connect_timeout = connect_timeout
        self.socket = None
        self.reader = None
        # 限长队列满时淘汰最早消息，避免长连接无限占用内存。
        self.messages = deque(maxlen=history_limit)
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
        """建立连接并启动后台接收任务，项目业务登录由 DeviceClient 执行。"""
        if self.socket is not None:
            raise RuntimeError("Session already opened")
        self.socket = await connect(
            self.url, open_timeout=self.connect_timeout,
            close_timeout=2, proxy=None, max_size=2 * 1024 * 1024,
        )
        self.evidence.record("ws_open", url=safe_url(self.url))
        # 启动后台接收任务；主用例仍可继续发送指令和等待结果。
        self.reader = asyncio.create_task(self._receive(), name="iot-ws-reader")

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
                    # 这里递增的是本地接收序号，不是服务器提供的请求流水号。
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
                async with self.condition:
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
            # 唤醒所有等待者检查共享历史；消息不会被某个等待者独占取走。
            self.condition.notify_all()
        tasks = [self.reader] if self.reader is not None else []
        for task in tasks:
            task.cancel()
        if tasks:
            # 等待取消真正完成，避免用例结束后仍残留后台任务。
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.socket is not None:
            await self.socket.close()
        self.evidence.record("ws_close")
