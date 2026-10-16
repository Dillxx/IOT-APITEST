# 如何阅读和新增测试

## 阅读顺序

1. tests/audio/test_9220_hdmi.py：看数据绑定、操作和通过条件。
2. testdata/audio/hdmi.json：看本次输入与期望。
3. tests/audio/conftest.py：需要了解前后置时再看原状态和恢复。
4. clients/device.py：需要了解报文时，搜索 set_volume 或 query_state。
5. clients/websocket.py / http.py：仅在排查收发、超时和连接问题时阅读。

公共配置在 tests/conftest.py 和 config 中；日志在 artifacts。读一条业务用例不需要先学习所有基础模块。

## 新增用例

- 相同操作、不同正常输入：在 JSON 的 cases 中追加记录，id 保持唯一。
- 新的业务组合：在对应测试文件直接写操作与 assert；前后置由 fixture 提供。
- 新增设备指令：先取得协议依据，在 clients/device.py 增加明确命名的操作；复用现有收发，不额外创建只转发一层的 API 类。
- 需要不同准备或恢复：在相应业务目录添加局部 fixture；全项目确实共用的资源才进入 tests/conftest.py。
- 简单断言直接写；复杂且出现多次的比较再提取，避免为了缩短测试行数隐藏业务预期。

## hdmi_case 是怎样获得的

测试文件中的 pytest_generate_tests 读取 `--iot-data` 指定的文件，调用 load_hdmi_cases，并明确执行 `metafunc.parametrize("hdmi_case", cases, ...)`。默认路径在 tests/conftest.py 的 pytest_addoption 中。

`metafunc` 是 pytest 传入的当前测试描述对象。它负责收集时绑定数据，不负责连接设备。

## 调试

F5 使用 `.vscode/launch.json` 中的“调试 HDMI 用例（本地模拟）”。在 set_volume 行前观察输入，在其后观察 after；前后置也可以在 audio/conftest.py 中单独设断点。

默认只运行模拟器。模拟报告和实际物理效果是不同证据层级。
