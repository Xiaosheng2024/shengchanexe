# PLC 磁吸流程调试工具

该工具用于现场与 PLC 工程师逐点联调 DB221 磁吸流程，不参与 MES
主流程。默认连接参数为：

- PLC IP：`192.168.111.50`
- Rack：`0`
- Slot：`1`
- DB：`221`

## 运行

在项目根目录执行：

```bash
python3 plc_magnet_test_tool/main.py
```

首次启动会在程序目录根据 `config.example.ini` 创建本地
`config.ini`。本地配置已被 Git 忽略。

Windows EXE 运行时，`config.ini` 和 `logs/plc_magnet_test.log`
均保存在 EXE 同级目录。内置模板只从 PyInstaller 的资源目录读取，
不会向临时目录写配置，也不依赖启动时的当前工作目录。

构建工作流会从另一个工作目录实际启动 EXE 执行路径自检，并检查
`shared.s7_plc_client`、python-snap7、配置生成位置和日志生成位置。

## 安全规则

- MES 只向 `DBW0`、`DBW4`、`DBW8` 写整数 `1`。
- 工具不提供写 `0`、清零或清全部按钮。
- 每次写入后最多读回 3 次，默认间隔 100ms。
- 左右磁吸结果必须同时为 `1`，才允许写 `DBW8=1` 通知 PLC 解锁。
- `DBD10`、`DBD18` 默认按 Siemens REAL 读取，也可切换为 DWORD
  排查 PLC 数据类型。

## DB 读取诊断

“测试连接”只验证 TCP/S7 会话。“测试DBW0访问”用于确认 DB221
可以被外部访问，“DB长度预检”会读取 `DBB0-25`，确认至少可访问
26字节。读取表格的每一行均有独立按钮；批量读取时单个地址失败不会
中断其他地址，错误单元格和日志会保留 PLC 返回的原始错误。

“原始DB读取”支持一次读取 `DB221` 的连续数据块，默认调用
`db_read(221, 0, 26)`。第三个参数是读取长度，不是结束地址。工具会显示
原始 HEX、逐字节内容，并在本机按 DBW0 至 DBW24 地址表切片解析。
快捷长度为 26、32、40、50、100 字节；自动探测会按
100、80、64、50、40、32、26、24、20、10、2 字节从大到小尝试。
地址表最后一项 DBW24 占 Byte24~Byte25，因此完整解析最少需要 26 字节。
原始块读取只用于调试，不替代现有单点读取。

S7-1200 现场需确认：

- Rack=`0`、Slot=`1`
- CPU 已开启 PUT/GET
- DB221 已关闭 Optimized block access
- DB221 已下载且至少包含26字节

## 独立 Windows 构建

本工具使用独立工作流
`.github/workflows/plc-magnet-tool-build.yml` 构建
`PLC_Magnet_Test_Tool.exe`。它不会加入正式客户端工作流或正式发布包。
