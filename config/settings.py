"""读取环境和设备配置，形成不可修改的 Settings 对象。
服务器地址、设备身份从 TOML 读取；Token/sign 从环境变量读取；用例目标值由 testdata 提供。
"""

from dataclasses import dataclass, field
from pathlib import Path
import os
import json
import tomllib


@dataclass(frozen=True)
class Settings:
    """一份运行设置。frozen=True 禁止运行途中改字段，测试覆盖设置时用 replace 创建副本。"""

    http_base_url: str
    ws_url: str
    mac: str
    model: str
    name: str
    company: str = "BL"
    device_name: str = "edu"
    http_device_name: str = "TE-0600R"
    platform: str = "manage"
    lang: str = "zh-cn"

    # repr=False 防止打印设置对象时顺带把身份凭据输出。
    token: str = field(default="", repr=False)
    sign: str = field(default="", repr=False)
    ws_sign: str = field(default="", repr=False)

    # 各阶段独立超时；这些值不等于整个用例的总耗时。
    connect_timeout: float = 10
    http_timeout: float = 10
    reply_timeout: float = 5
    state_timeout: float = 10
    heartbeat_interval: float = 5
    history_limit: int = 2000

    # 设备能力和保护范围归配置，用例目标值另从 testdata 读取。
    supports_hdmi: bool = True
    hdmi_min: int = 0
    hdmi_max: int = 100
    restore_original: bool = True
    http_headers: dict = field(default_factory=dict, repr=False)
    http_cookies: dict = field(default_factory=dict, repr=False)
    http_params: dict = field(default_factory=dict, repr=False)
    ws_headers: dict = field(default_factory=dict, repr=False)
    ws_cookies: dict = field(default_factory=dict, repr=False)


def load_settings(path: Path) -> Settings:
    """先读取环境 TOML，再按相对路径读取设备 TOML，合并凭据并检查基本配置。
    返回 Settings，供 fixture 和设备客户端共用；不读取目标音量用例数据。
    """

    with path.open("rb") as stream:
        """在文件打开期间完成读取或写入。"""

        raw = tomllib.load(stream)

    # 设备相对路径以环境 TOML 所在目录为基准，不依赖命令行当前目录。
    device_path = path.parent / raw["device"]["config_file"]
    with device_path.open("rb") as stream:
        """在文件打开期间完成读取或写入。"""

        device_config = tomllib.load(stream)
    server, device = raw["server"], device_config["device"]
    timeouts = raw["timeouts"]
    settings = Settings(

        # ** 将各配置字典展开为构造参数，合并不同来源的设置。
        **server, **device, **raw["protocol"],
        token=os.environ.get("IOT_TOKEN", ""),
        sign=os.environ.get("IOT_SIGN", ""),
        ws_sign=os.environ.get("IOT_WS_SIGN", ""),
        connect_timeout=timeouts["connect"], http_timeout=timeouts["http"],
        reply_timeout=timeouts["reply"], state_timeout=timeouts["state"],
        heartbeat_interval=timeouts["heartbeat_interval"],
        history_limit=timeouts["history_limit"],
        supports_hdmi=device_config["capabilities"]["hdmi_volume"],
        hdmi_min=device_config["hdmi"]["min"], hdmi_max=device_config["hdmi"]["max"],
        restore_original=raw["execution"]["restore_original"],
        http_headers={**raw.get("http", {}).get("headers", {}), **json.loads(os.environ.get("IOT_HTTP_HEADERS", "{}"))},
        http_cookies=json.loads(os.environ.get("IOT_HTTP_COOKIES", "{}")),
        http_params=raw.get("http", {}).get("params", {}),
        ws_headers={**raw.get("websocket", {}).get("headers", {}), **json.loads(os.environ.get("IOT_WS_HEADERS", "{}"))},
        ws_cookies=json.loads(os.environ.get("IOT_WS_COOKIES", "{}")),
    )
    for value in (settings.connect_timeout, settings.http_timeout,
                  settings.reply_timeout, settings.state_timeout,
                  settings.heartbeat_interval):
        if value <= 0:
            raise ValueError("Timeouts and heartbeat interval must be positive")
    if settings.history_limit < 2:
        raise ValueError("history_limit must be at least 2")
    if settings.hdmi_min > settings.hdmi_max:
        raise ValueError("HDMI minimum cannot exceed maximum")
    return settings
