# 生产工艺过程质量控制系统

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

```bash
pip3 install PyQt5
python3 main.py
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

服务端生产默认使用 PostgreSQL。Windows MES 客户端仍然只通过 HTTP 访问 `http://服务器IP:8000`，不直接连接 PostgreSQL；所有数据库操作都由 `web_admin.py` 服务端完成。

`config.ini` 数据库配置示例：

```ini
[DATABASE]
type = postgresql
host = 127.0.0.1
port = 5432
database = mes_db
user = mes_user
password = mes_password
```

本地调试仍兼容 SQLite：

```ini
[DATABASE]
type = sqlite
path = quality_control.db
```

首次启动会自动创建项目、工位、工序、扫码记录、工位完成记录和生产追溯表。

桌面端在线模式的接口地址默认可填：

```text
http://127.0.0.1:8000
```

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
Password: mes_password
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
- 正向值：`0`，允许计数，允许处理 OK / NG
- 反向值：`1`，不计数，不处理 OK / NG
- 反向触发是否自动清 `53`：默认启用
- 管理员解锁密码：默认 `0000`

程序只有在当前工序为螺丝工序，并且 `地址54 == 0`、`地址53 == 1`、`地址100 == 2` 时才会计 1 颗螺丝。进入螺丝工序时写 `地址53 = 0` 并写 `地址4 = 1` 解锁螺钉枪；处理完一次触发后会写 `地址53 = 0`，防止地址100保持 OK 时重复计数。若 `地址54 == 1`，程序显示反向状态，不计数、不处理 OK/NG；如已触发 `地址53 == 1`，默认会自动写 `地址53 = 0` 清除反向触发。若 `地址54 == 0`、`地址53 == 1` 且 `地址100 == 3`，程序记录 NG、写 `地址4 = 2` 锁定螺钉枪、写 `地址53 = 0`，并弹出管理员解锁窗口。管理员输入 `0000` 后写 `地址4 = 1` 解锁，提示重新打当前这颗螺丝。螺丝数量满足后写 `地址4 = 2` 锁定螺钉枪；非螺丝工序保持锁定。

高级参数保存在 `config.ini` 的 `[TOOL]` 段中，常用字段保留在主界面，触发、锁定、方向、轮询、超时和管理员密码在“螺钉枪高级设置”弹窗中维护。

## 版本说明

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
