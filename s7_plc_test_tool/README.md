# S7 PLC 条码读取测试工具（已废弃）

PLC 参数验证工具已废弃，正式环境使用主客户端 PLC 静默监听。
从 `v0.9.3-rc2` 起，本工具不再参与正式发布，也不再生成 EXE。

本目录仅保留历史参数验证源码。

## 安装依赖

```bash
pip install -r ../requirements-client.txt
```

## 运行

在项目根目录运行：

```bash
python s7_plc_test_tool/main.py
```

程序启动后不会自动连接 PLC，需要手动点击“连接PLC”，再点击“开始监听”。

## 打包 EXE

已禁用。`build_exe.bat` 只显示废弃提示，不再生成可执行文件。

## 修改配置

现场参数全部在 `config.ini` 修改，不需要改代码。

默认地址：

```text
PLC IP = 10.162.86.65
Rack = 0
Slot = 1

PARTS_OK = DB221.DBW358
条码1 = DB201.DBB800 长度40
条码2 = DB201.DBB840 长度40
```

条码默认编码为 `ascii`。如果现场显示乱码，可以把 `config.ini` 中的 `encoding` 修改为：

```text
utf-8
gbk
latin1
```

## 记录逻辑

监听时每个周期读取：

- `DB221.DBW358`：合格计数 `PARTS_OK`
- `DB201.DBB800` 长度 40：条码1
- `DB201.DBB840` 长度 40：条码2

触发规则：

- 第一次读取只建立基准值，默认不记录。
- `PARTS_OK` 不变时不记录。
- `PARTS_OK` 递增时才尝试记录。
- 两个条码都为空且 `allow_empty_barcode=false` 时不记录。
- `ignore_duplicate_barcode_pair=true` 时，同一组条码1+条码2不重复记录。
- `PARTS_OK` 降低时，默认认为 PLC 计数清零、换班或重启，只更新基准，不补记录。

## CSV 和日志

CSV 文件：

```text
data/plc_records.csv
```

日志文件：

```text
logs/plc_test.log
```

CSV 使用 `utf-8-sig` 保存，Excel 打开不容易乱码。每次新记录都会立即写入文件，减少断电丢失风险。

## 现场 PLC 要求

S7-1200 需要在 TIA Portal 中检查：

1. 允许 PUT/GET Communication。
2. 如果使用 `DB201.DBB800`、`DB201.DBB840`、`DB221.DBW358` 这类绝对地址读取，DB201、DB221 需要关闭 Optimized Block Access。
3. 修改后需要重新编译并下载到 PLC。

如果报 `function refused by CPU`，优先检查以上三项。

## 常见问题

PLC连接失败：

- 检查 IP、网线、PLC 是否允许外部访问、Rack/Slot。

DB读取失败：

- 检查 DB号、offset、length 是否正确。

条码为空：

- 检查 PLC 是否已经写入条码，offset/length 是否正确。

PARTS_OK 不递增：

- 程序只监听不记录，这是正常逻辑。

通讯中断：

- 程序会显示异常并写入日志，不会因为单次读取失败而崩溃。

## 禁止事项

- 不要写 PLC。
- 不要把本工具集成到 MES 主程序。
- 不要把 IP、DB、偏移、长度、编码写死到代码里。
- 不要在 `PARTS_OK` 不变时重复记录。
