# 关键工位防错追溯系统

PyQt5 单机界面原型，包含：

- 左侧工艺过程步骤列表，展示扫码/螺丝工序完成状态。
- 右侧当前产品中文名称、当前工序、扫码输入、螺丝数量方块提示。
- 主界面显示已生成零件数、扫码错误总数。
- “模拟螺钉枪OK信号”按钮，用于测试真实 OK 信号接入前的流程。
- 主界面支持通过 TCP 轮询螺钉枪寄存器，按方向、触发和状态判断后自动计螺丝数量。
- “设置功能”按钮弹出独立设置窗口，可维护产品中文名称、扫码复核规则、条码截取位、螺丝数量、工序顺序。
- “历史记录 / 统计报表”按钮弹出独立查询窗口，可按日期查看历史记录和工序耗时统计。
- 支持离线/在线模式；在线模式可从网页端同步项目、工位和工序配置。
- 在线模式下，第 2 工位及以后会按条码查询前一工位是否完成；离线模式不做前置工位校验。

## 运行

桌面端本地运行：

```bash
pip3 install -r requirements-client.txt
python3 main.py
```

网页服务本地运行：

```bash
pip3 install -r requirements-server.txt
python3 web_admin.py
```

## 模块结构

```text
main.py                         桌面端启动入口
desktop_app/window.py           PyQt5 主窗口和界面流程
desktop_app/tool_client.py      螺钉枪 Modbus TCP 通讯
desktop_app/tool_worker.py      螺钉枪后台线程轮询和写寄存器
shared/models.py                项目、工位、产品、工序共享数据模型
web_admin.py                    网页管理端启动入口
web_admin_app/server.py         HTTP 路由和接口响应
web_admin_app/services.py       项目/工位/工序/记录增删改查业务
web_admin_app/database.py       SQLite 数据库连接、建表和初始化数据
web_admin_app/admin_page.py     网页管理端前端页面模板
```

## 网页端管理后台

启动后端和管理页面：

```bash
python3 web_admin.py
```

Windows 上也可以一条命令启动网页服务：

```bat
deploy\start_web_service.bat
```

浏览器打开：

```text
http://127.0.0.1:8000
```

网页端包含：

- 左侧标签，右侧功能区
- 左侧项目/工位/工序规则三级菜单，点击后右侧自动切换并绑定当前层级
- 项目管理：新增、修改、删除
- 工位管理：新增、修改、删除
- 工序规则管理：新增、修改、删除
- 螺丝数量 / 条码扫描规则维护
- 扫描记录查询：支持条码、开始时间、结束时间筛选，并支持记录修改、删除

### Web 管理后台账号

生产服务器首次部署时执行：

```bash
sudo /opt/mes/scripts/security/init_web_admin_accounts.sh
```

初始 `admin` 和 `super_admin` 密码保存在服务器本地：

```text
/root/server-secrets/web_admin_accounts.txt
```

该文件权限为 `600 root:root`，不能提交到 Git。客户管理员可以在后台修改自己的密码；超级管理员密码只能在服务器执行：

```bash
sudo /opt/mes/scripts/security/reset_super_admin_password.sh
```

客户管理员忘记密码时执行：

```bash
sudo /opt/mes/scripts/security/reset_admin_password.sh
```

网页管理 API 需要登录 Cookie。桌面客户端使用的配置下载、工位占用/心跳、生产记录上传、工位完成校验和版本下载接口保持独立，不要求网页登录。

服务端生产默认使用 PostgreSQL。Windows MES 客户端仍然只通过 HTTP 访问 `http://服务器IP:8000`，不直接连接 PostgreSQL；所有数据库操作都由 `web_admin.py` 服务端完成。

`config.ini` 数据库配置示例：

```ini
[DATABASE]
type = postgresql
host = 127.0.0.1
port = 5432
database = mes_db
user = mes_user
password = change_me_random_password

[SERVER]
host = 0.0.0.0
port = 8000
```

Git 中只提交 `config.example.ini`。生产真实配置建议放在 `/opt/mes/config.ini`，权限设置为 `600`，不要把真实数据库密码提交到 Git。

本地调试仍兼容 SQLite：

```ini
[DATABASE]
type = sqlite
path = quality_control.db
```

首次启动会自动创建项目、工位、工序、扫码记录、工位完成记录和生产追溯表。

桌面端从本机 `config.ini` 读取 MES 服务器地址：

```ini
[SERVER]
url = http://mes-server:8000
```

也可以在桌面端通过“系统设置 -> 服务器设置”修改并测试连接。修改服务器地址不会重新生成 `client_id`。
服务器迁移步骤见 [deploy/README_服务器迁移到公司内网.md](deploy/README_服务器迁移到公司内网.md)。

## 离线部署

客户现场无法访问外网时，先在开发电脑执行：

```bat
deploy\download_offline_deps.bat
```

然后把整个项目目录复制到 U 盘，再复制到客户电脑。客户电脑执行：

```bat
deploy\install_offline_deps.bat
```

启动网页服务：

```bat
deploy\start_web_service.bat
```

同时启动网页服务和桌面端：

```bat
deploy\start_all.bat
```

详细说明见：

```text
deploy\README_OFFLINE.md
```

## Rocky Linux 9 PostgreSQL 部署

Rocky Linux 9 服务端部署 PostgreSQL 16：

```bash
sudo bash deploy/rocky9/02_install_mes_server.sh
```

脚本会安装 PostgreSQL 16、创建 `mes_db` 和 `mes_user`、写入 `/opt/mes/config.ini`，并只开放 `8000/tcp` 和 `22/tcp`。默认不开放 `5432/tcp`；MES 服务和 PostgreSQL 在同一台服务器时，PostgreSQL 只需要监听本机 `127.0.0.1`。

备份：

```bash
deploy/rocky9/db_tools/pg_backup.sh
```

恢复：

```bash
deploy/rocky9/db_tools/pg_restore.sh /opt/mes/backup/mes_db_YYYYMMDD_HHMMSS.dump
```

## SQLite 迁移到 PostgreSQL

旧 SQLite 文件 `quality_control.db` 可迁移到 PostgreSQL：

```bash
python3 tools/migrate_sqlite_to_postgres.py --sqlite quality_control.db
```

如果目标 PostgreSQL 已有数据，脚本会拒绝迁移。确认继续时使用：

```bash
python3 tools/migrate_sqlite_to_postgres.py --sqlite quality_control.db --force
```

迁移表：`projects`、`stations`、`steps`、`scan_records`、`station_completions`。

## Mac 远程管理 PostgreSQL

推荐使用 SSH 隧道，不直接暴露服务器 `5432`：

```bash
ssh -L 5433:127.0.0.1:5432 admin@服务器IP
```

Mac 上数据库工具连接：

```text
Host: 127.0.0.1
Port: 5433
Database: mes_db
User: mes_user
Password: /opt/mes/config.ini 中的随机密码
```

## Windows 打包

在 Windows 电脑上双击或运行：

```bat
build_windows.bat
```

打包完成后，可执行文件在：

```text
dist\QualityControlSystem.exe
```

如果代码推送到 GitHub，仓库里的 GitHub Actions 会自动在 Windows 环境打包，并生成 `QualityControlSystem-windows` 下载附件。

### 依赖文件说明

- `requirements-client.txt`：桌面端和 PLC 测试工具依赖
- `requirements-server.txt`：Rocky Linux 服务端依赖，不包含 Qt / GUI 包
- `requirements-dev.txt`：开发与打包依赖

## 当前默认流程

产品：汽车前中控面板X04C 灰色

1. 扫码A零件
2. 扫码B零件条码
3. 打螺丝10颗
4. 扫码C零件

扫码规则可在设置窗口自定义。检测内容为空时表示只确认扫码，不校验内容。

## 接入真实螺钉枪 TCP OK 信号

当前测试按钮调用的是 `QualityControlWindow.handle_screw_ok()`。

主界面“螺钉枪TCP OK信号”区域默认按 Modbus TCP 读取：

- 端口：502
- 站号：1
- 状态寄存器：100，对应说明书中的 `拧紧状态`
- OK 值：2

状态值说明：`0 准备`、`1 作业中`、`2 OK`、`3 NG`、`4 暂停`、`5 正转`、`6 反转`。

螺钉枪计数逻辑：

- 状态地址：`100`
- OK 值：`2`
- NG 值：`3`
- 触发地址：`53`
- 触发值：`1`
- 触发复位值：`0`
- 锁定控制地址：`4`
- 锁定值：`2`，禁止启动 / 禁止打螺丝
- 解锁值：`1`，允许启动 / 允许打螺丝；现场如需 `0` 解锁，可在界面改为 `0`
- 方向地址：`54`
- 正转值：默认 `3`，允许计数，允许处理 OK / NG
- 反转值：默认 `2`，不计数，不处理 OK / NG
- 反向触发是否自动清 `53`：默认启用
- 管理员解锁密码：默认 `0000`

程序只有在当前工序为螺丝工序，并且 `地址54 == forward_value`、`地址53 == 1`、`地址100 == 2` 时才会计 1 颗螺丝。进入螺丝工序时写 `地址53 = 0` 并写 `地址4 = 1` 解锁螺钉枪；处理完一次触发后会写 `地址53 = 0`，防止地址100保持 OK 时重复计数。若 `地址54 == reverse_value`，程序显示反转状态，不计数、不处理 OK/NG；如已触发 `地址53 == 1`，默认会自动写 `地址53 = 0` 清除反转触发。正转时地址100为 NG，程序记录 NG、写 `地址4 = 2` 锁定螺钉枪、写 `地址53 = 0`，并弹出管理员解锁窗口。管理员输入 `0000` 后写 `地址4 = 1` 解锁，提示重新打当前这颗螺丝。螺丝数量满足后写 `地址4 = 2` 锁定螺钉枪；非螺丝工序保持锁定。

高级参数保存在 `config.ini` 的 `[TOOL]` 段中，常用字段保留在主界面，触发、锁定、方向、轮询、超时和管理员密码在“螺钉枪高级设置”弹窗中维护。
`command_delay_ms` 控制检测状态后写寄存器前的延迟，默认 `50ms`。延迟在螺钉枪 worker 线程内执行，不阻塞主界面。
`poll_interval_ms` 控制地址 `53/54/100` 的持续轮询间隔，默认 `100ms`，现场可在 `50ms` 到 `5000ms` 范围内调整。正常轮询始终复用同一个 TCP 长连接。

## 第一工位 S7 PLC 接收主条码

正式生产版支持工序类型：`PLC接收`。

默认第一工位工序：

```text
工位1 → PLC接收主条码
类型：PLC接收
是否主条码：是
PLC IP：10.162.86.65
主条码：DB201.DBB800 长度40
PARTS_OK：DB221.DBW358，递增表示完成OK
```

PLC 工序判断规则：

1. 第一次读取只建立 `主条码 / PARTS_OK` 基准，不完成工序。
2. 先检测到 PLC 主条码变化，缓存为待确认主条码。
3. 再检测到 `PARTS_OK` 递增，才确认该条码 OK。
4. 如果 `PARTS_OK` 递增但之前没有条码变化，不完成工序并记录异常。
5. 如果 `PARTS_OK` 变小，认为 PLC 重启、清零或换班，只重新建立基准。
6. PLC 主条码工序完成后才设置桌面端 `current_barcode`，并用于后续工位流转校验。
7. 非主条码 PLC 工序必须与当前主条码一致，不允许覆盖当前主条码。

PLC 接收只负责主条码和 `PARTS_OK` 判断，不负责螺丝数量、工位完成时间统计或直接写入 `station_completions`；工位完成仍由 MES 当前工位所有工序完成后统一上报。

修改 PLC IP 的推荐方式：

1. 打开 MES Web 管理后台：`http://服务器IP:8000`
2. 进入：项目 / 工位 / 工序配置
3. 找到：`工位1 → PLC接收主条码`
4. 修改：`PLC IP`
5. 保存后，第一工位客户端点击“同步配置”或重启客户端

如果现场临时更换 PLC IP，桌面端可打开“本机设置”启用 `PLC本地覆盖`，但正式生产建议仍回到网页端配置，避免多台客户端配置不一致。

`s7_plc_test_tool` 仍保留为现场测试工具，用于验证 PLC 地址、编码和通讯是否正常；正式生产由 MES 主程序内置 PLC worker 读取。

## 工位占用

在线模式下，同一项目和工位同一时间只允许一台设备生产。客户端选择项目/工位后会申请占用，并通过心跳维持占用；未成功占用时禁止扫码、PLC接收、螺钉枪计数和工位完成上报。管理员密码 `0000` 可强制接管。

工位占用字段统一使用：

- `client_id`：当前设备唯一ID
- `computer_name`：当前电脑名称
- `ip_address`：当前电脑IP
- `last_heartbeat_at`：最后心跳时间

如果同一 `project_id + station_id` 已有在线占用，但 `last_heartbeat_at` 超过 120 秒，服务端会自动将旧记录标记为离线并允许当前客户端占用。同一个 `client_id` 重新进入同一工位时只刷新心跳，不报冲突。

接口：

```http
POST /api/station-session/acquire
POST /api/station-session/heartbeat
POST /api/station-session/release
POST /api/station-session/force-acquire
GET  /api/station-sessions?status=online
```

## 数据库维护接口

```http
GET  /api/admin/db/status
POST /api/admin/db/backup
POST /api/admin/db/archive
POST /api/admin/db/delete-old-records
GET  /api/admin/db/maintenance-logs
POST /api/admin/db/vacuum-or-analyze
```

默认维护表包括：`scan_records`、`station_work_records`、`step_work_records`、`screw_action_records`、`station_session_logs`。`station_completions` 是前后工位校验关键表，默认不删除，必须单独选择。

## 版本说明

- `v0.8.6`：修复地址53复位等待时静默跳过的问题，写53成功后解除防重复锁，失败或仍为1时持续重试；最后一颗先显示10/10并清53、锁枪，再进入下一轮。
- `v0.8.5`：地址 `53/54/100` 默认每 `100ms` 持续轮询，补充触发漏采诊断日志；扫码行压缩，10颗螺丝改为5+5两排大方块显示。
- `v0.8.4`：螺钉枪 Modbus TCP 保持长连接，所有寄存器写指令默认在线程内延迟 `50ms`，并支持通过 `command_delay_ms` 配置。
- `v0.8.3`：Windows 打包版无 `config.ini` 时内置使用方向地址 `54`、正转值 `3`、反转值 `2`；首次生成配置时同步写入这些默认值。
- 螺钉枪方向协议值可在 `config.ini` 的 `[TOOL]` 中通过 `forward_value`、`reverse_value` 配置，默认正转 `3`、反转 `2`。
- `v0.8.2`：螺钉枪 Modbus TCP 改为 worker 线程内长连接和自动重连，切换工位/项目及退出时安全锁枪断开；压缩生产状态文字并突出螺丝数量进度。
- `v0.8.1`：补全 PLC 接收工序正式流转，统一主条码字段，增加 PLC 主条码前后工位校验、本机 PLC 覆盖配置和工位占用超时释放。
- `v0.8.0`：正式生产版集成 S7 PLC 接收工序、第一工位默认 PLC 主条码、工位占用检查、数据库维护归档/删除接口。
- `v0.5.0`：MES 服务端数据库支持 PostgreSQL，增加 SQLite 到 PostgreSQL 迁移方案、分页追溯接口和 Rocky Linux PostgreSQL 部署/备份脚本。
- `v0.2.0`：增加地址54方向判断、NG锁枪、管理员密码解锁、线程安全写寄存器。

## 在线模式接口约定

主界面填写网页端接口地址后，可使用“同步项目工位”和“下载配置”。

同步项目工位：

```http
GET /api/projects
```

返回示例：

```json
{
  "projects": [
    {"name": "项目A", "stations": ["工位1", "工位2", "工位3"]}
  ]
}
```

下载工位配置：

```http
GET /api/projects/{project}/stations/{station}/config
```

返回示例：

```json
{
  "product_name": "汽车前中控面板X04C 灰色",
  "steps": [
    {"name": "扫码A零件", "type": "扫码", "barcode_start": 1, "barcode_end": 1, "expected_content": "A"},
    {"name": "打螺丝10颗", "type": "螺丝", "required_count": 10}
  ]
}
```

前一工位完成校验：

```http
GET /api/station-completions/check?project=项目A&barcode=条码&previous_station=工位1
```

返回示例：

```json
{"completed": true}
```

当前工位完成上报：

```http
POST /api/station-completions
Content-Type: application/json

{
  "project": "项目A",
  "station": "工位2",
  "barcode": "ABC123",
  "completed_at": "2026-06-12T10:30:00"
}
```

分页追溯接口：

```http
GET /api/production-records?main_barcode=xxx&page=1&page_size=100
GET /api/step-records?main_barcode=xxx&page=1&page_size=100
GET /api/screw-records?main_barcode=xxx&page=1&page_size=100
GET /api/trace?barcode=xxx
```

支持 `main_barcode`、`project_id`、`station_id`、`start_time`、`end_time`、`result`、`page`、`page_size`。默认 `page_size=100`，最大 `500`，禁止无条件查询大表。
