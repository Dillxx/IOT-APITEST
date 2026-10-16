# 账号登录与运行级共享凭据

## 账号保存位置

本机填写 config/accounts.local.toml，该文件由 .gitignore 排除。空模板 accounts.local.toml.example 可以提交，不包含有效账号。

```toml
[admin]
username = ""
password = ""
```

私有文件的 admin 表是云控平台管理员账号，不属于 TS-9260 或 TS-9220。test 和 ts9260 环境都引用这一表；切换设备只改变设备身份。不同服务器环境仍各自登录取得 Token，不把一台服务器的 Token 直接用于另一台服务器。

IOT_USERNAME/IOT_PASSWORD 可以覆盖文件中的账号，但作为一整对来源选择：只提供其中一个时不会从文件补齐另一个，会明确报告缺失。当前账号密码由用户自行填写，分组迁移时完整保留，没有从 HAR 读取。

## 登录和共享

```text
本机账号配置
    ↓
GET /accessToken → HTTP 接入令牌
    ↓
POST /api/login/login → data.data 会话 Token
    ↓
核对登录结果 → 缓存在本次运行的 auth 中
    ↓
所有普通 HTTP/WS 接口共用
```

- auth.token：登录返回的 data.data，供 HTTP token 请求头和 WS JSON token 使用。
- auth.sign：HTTP 接入令牌，供 Authorization Bearer 和 HTTP sign 使用。
- token fixture：auth.token 的直接取值入口，不是第二份 Token。

auth 是 session 级 fixture，每次测试启动生成一次，相当于本次运行的共享变量。结束后丢弃，不写 Token 文件，不跨运行或环境复用旧值。

客户端默认自动携带凭据；用例确需显式传值时可这样写：

```python
async def test_get_device_list(device_api, case, auth):
    """从共享上下文取出 Token，业务断言仍写在用例中。"""

    response = await device_api.get_device_list(
        params=case["request"]["params"],
        headers={"token": auth.token},
    )

    # 验证结果。
    assert response.status_code == case["expected"]["status_code"]
```

## 登录接口测试

LoginApi 仍是独立 API，调用后只返回响应，不自动覆盖 auth。后续正常、错误密码等登录用例可单独编写；它们的响应应作为各自 case 的验证数据，不能把失败响应写进其他接口使用的共享上下文。

启动登录是其他接口的前置，不依赖某条 test_login 必须先执行。需要身份切换或破坏会话的测试使用独立客户端，避免污染普通接口。

## 执行与边界

```powershell
.\run-tests.ps1 -Env ts9260 -Live -TestPath tests/websocket/test_hdmi_volume.py -CaseId hdmi_volume_10
```

缺少账号时在联网前退出。HAR 的日常输入入口已移除，不读取旧文件、不复用旧 Token；历史抓包和报告仅保留为协议及过去执行的证据。

用户填写的值已完整保留，配置仅将分组名从设备名称改为 admin。此次只调整账号归属并做本地验证，不发送设备控制指令。
