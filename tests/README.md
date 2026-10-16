# 接口测试

http/websocket 按协议放用例脚本，workflows 放跨接口流程，二者都调用独立 api 模块；framework 验证公共能力和 API 边界。数据在独立的 data 对应目录；前后置在 conftest.py。
