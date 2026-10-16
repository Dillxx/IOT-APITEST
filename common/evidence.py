"""逐用例保存脱敏 JSONL 证据。
UTC 时间戳和本地 sequence 用于追踪消息，sequence 不是服务器协议流水号。
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import logging
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

LOGGER = logging.getLogger(__name__)

# 按常见字段名识别凭据，忽略大小写；普通业务字段仍然保留。
SECRET = re.compile(r"^(token|sign|authorization|proxy-authorization|cookie|set-cookie|password|passwd|pwd|access_?token|refresh_?token|api[_-]?key|clientId|client_id|client_secret|secret|usernum|userpassword|username)$", re.I)


def sensitive_key(key):
    """识别普通字段及 data[userpassword] 这样的表单字段。"""

    parts = [part for part in re.split(r"[\[\].]", unquote(str(key))) if part]
    return bool(parts and SECRET.fullmatch(parts[-1]))


def redact(value):
    """递归复制字典和列表，替换敏感字段；不直接修改原报文。"""

    if isinstance(value, dict):
        return {key: "[REDACTED]" if sensitive_key(key) else redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                return json.dumps(redact(parsed), ensure_ascii=False, separators=(",", ":"))
        except ValueError:
            pass
    return value


def safe_url(url: str) -> str:
    """去掉 URL 中的账号密码和片段，脱敏敏感查询参数，保留正常接口定位信息。"""

    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parts.port:
        host += f":{parts.port}"
    query = urlencode([(key, "[REDACTED]" if sensitive_key(key) else redact(val))
                       for key, val in parse_qsl(parts.query, keep_blank_values=True)])

    # host 不含原 URL 用户名密码，最后的空字符串去掉片段部分。
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


class Evidence:
    """每条用例的独立证据记录器；文件按 UTF-8 追加，一行一个 JSON 对象。"""

    def __init__(self, directory: Path):
        """创建输出目录并从零开始本地记录序号，路径由 fixture 按用例分配。"""

        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "traffic.jsonl"
        self.sequence = 0
        self.case_id = None
        self.phase = "connection"

    def record(self, kind: str, **data):
        """添加 UTC 时间戳、本地序号和事件类型，脱敏后写入 traffic.jsonl。"""

        self.sequence += 1
        event = {"timestamp": datetime.now(timezone.utc).isoformat(),
                 "sequence": self.sequence, "type": kind,
                 "case_id": self.case_id, "phase": self.phase, **redact(data)}
        with self.path.open("a", encoding="utf-8") as stream:
            """JSONL 每行是独立 JSON，便于按类型、时间和序号筛选分析。"""

            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        if kind in {"failure", "checkpoint", "restore_failed"}:
            LOGGER.info("%s: %s", kind, redact(data))

