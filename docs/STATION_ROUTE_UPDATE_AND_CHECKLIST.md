# 工位路线配置更新与维护自检

本文用于部署和验收“项目 → 路线 → 工位 → 工序规则”配置，适用于
Rocky Linux 9、PostgreSQL 16 和 Windows MES 客户端。

## 一、更新内容

`stations` 表增加并统一使用以下字段：

| 字段 | 默认值 | 用途 |
| --- | --- | --- |
| `route_name` | `A主线` | A主线、B子线、返修线或其他 |
| `route_order` | `0` | 路线内显示顺序 |
| `station_role` | `普通工位` | 工位在路线中的业务作用 |
| `material_type` | 空 | 当前工位生产的父件物料类型 |

Web 工位管理、左侧项目树和工艺路线配置页面都直接读取这组字段，
不存在第二套路线表。路线顺序只控制显示，生产放行仍由工位依赖规则控制。

工位作用包括：

- 普通工位
- 起点工位
- PLC起点
- 主条码切换工位
- 合并绑定工位
- 后续工位
- B起点工位
- B完成工位

## 二、部署前检查

在 Mac 项目目录执行：

```bash
cd "/Users/apple/Documents/生产工艺过程质量控制系统"
git status
git pull --ff-only origin main
git rev-parse HEAD
python3 -m unittest discover -s tests
```

允许 `s7_plc_test_tool/config.ini` 保留本机调试参数。准备脚本会忽略该文件，
服务器更新包从当前已提交 commit 生成，不会打入本机配置。

## 三、准备更新包

在可以访问外网时执行：

```bash
bash "/Users/apple/Documents/生产工艺过程质量控制系统/prepare_update_package.sh"
```

确认生成：

```text
dist_deploy/mes_update.tar.gz
dist_deploy/offline_wheels.tar.gz
dist_deploy/SHA256SUMS
dist_deploy/deploy_commit.txt
```

## 四、部署服务器

切换到公司内网后执行：

```bash
bash "/Users/apple/Documents/生产工艺过程质量控制系统/deploy_update_to_server.sh"
```

脚本会依次执行：

1. 校验本地更新包。
2. 检查 `10.162.70.53` 的 SSH 连接。
3. 上传源码包和离线依赖。
4. 备份 PostgreSQL。
5. 备份当前 `/opt/mes` 代码。
6. 停止 `mes-web`。
7. 保留 `config.ini`、`.venv`、`backups`、`logs` 和 `releases` 后同步代码。
8. 仅安装 `requirements-server.txt`。
9. 执行可重复的数据库初始化和迁移。
10. 启动并检查 `mes-web`。

PostgreSQL 监听检查只拦截：

```text
0.0.0.0:5432
*:5432
[::]:5432
```

以下本机监听属于正常状态：

```text
127.0.0.1:5432
[::1]:5432
```

## 五、服务器状态自检

```bash
sudo systemctl is-enabled mes-web
sudo systemctl is-active mes-web
sudo systemctl is-enabled postgresql-16
sudo systemctl is-active postgresql-16
ss -lntp | grep -E ':8000|:5432'
curl -I http://127.0.0.1:8000
sudo journalctl -u mes-web -n 120 --no-pager
```

预期：

```text
Web:        0.0.0.0:8000 或 *:8000
PostgreSQL: 127.0.0.1:5432
```

## 六、数据库字段自检

```bash
sudo -iu postgres psql -d mes_db -c "
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name='stations'
  AND column_name IN ('route_name','route_order','station_role','material_type')
ORDER BY column_name;"
```

检查旧工位仍然存在：

```bash
sudo -iu postgres psql -d mes_db -c "
SELECT id, project_id, name, route_name, route_order, station_role, material_type
FROM stations
ORDER BY project_id, route_name, route_order, id;"
```

迁移不会删除旧工位。首次从无路线字段的旧表迁移时，旧工位默认归入
`A主线`，`route_order` 使用原工位 ID；之后可在 Web 页面手工调整。

## 七、X04C 路线配置

进入 Web 后台：

```text
项目管理 → 选择 X04C
工位管理 → 逐个编辑工位
```

建议配置：

| 路线 | 顺序 | 工位 | 工位作用 | 物料类型 |
| --- | ---: | --- | --- | --- |
| A主线 | 1 | 中饰板预装-中出风口-磁吸 | PLC起点 | A物料 |
| A主线 | 2 | 中饰板预装-左右出风口 | 普通工位 | A物料 |
| A主线 | 3 | 上盖板预装-气囊装配 | 普通工位 | A物料 |
| A主线 | 4 | 总装工位1 | 主条码切换工位 | A物料 |
| A主线 | 5 | 总装工位2 | 合并绑定工位 | A物料 |
| A主线 | 6 | 总装工位3 | 后续工位 | A物料 |
| B子线 | 1 | 上盖板预装1 | B起点工位 | B物料 |
| B子线 | 2 | 上盖板预装2 | B完成工位 | B物料 |

保存后刷新页面，确认：

- 工位列表列顺序为“项目 / 路线 / 顺序 / 工位 / 工位作用 / 创建时间 / 操作”。
- 左侧树在 X04C 下分别显示 A主线和 B子线。
- 工艺路线配置页面显示相同路线、顺序和工位作用。

## 八、子物料绑定配置自检

在 A 的“合并绑定工位”新增或编辑“子物料绑定”工序：

1. 父件物料类型显示为下拉框，值来自当前 A 工位的 `material_type`。
2. 父件物料类型在绑定工序中只读，避免与工位配置产生两套值。
3. 同项目 A/B 线路选择“按完成工序绑定主条码”。
4. 子物料项目留空表示当前项目。
5. B路线可选；为空时不限制路线。
6. 多选 B 主条码必须完成的工位，此项必填。
7. 设置子物料数量。
8. 保存并重新编辑，确认所有选项正确回显。

下拉选项来源：

- 基础选项 `A物料`、`B物料`。
- 所选项目的产品类型。
- 所选项目现有工位的物料类型。
- 数据库中已经保存的旧类型会保留为下拉选项，不会因编辑丢失。

## 九、生产流程验收

按顺序验证：

1. A 的 PLC起点可创建并接收 A 主条码。
2. A 普通工位只能使用当前 A 主条码继续。
3. 主条码切换后，旧 A 码不能继续生产，新 A 码可以继续。
4. B起点工位可创建 B 产品。
5. B完成工位依赖 B起点工位。
6. B 未完成必需工位时，A-B 绑定失败并显示缺少工位。
7. B 完成全部必需工位后可以绑定 A。
8. 同一 B 不能绑定其他 A。
9. A 后续工位在未绑定 B 时不能进入。
10. 扫码、PLC 和螺丝工序原有功能正常。

桌面端重点确认：

- `PLC起点` 能建立新的产品实体。
- `B起点工位` 能建立新的 B 产品实体。
- 普通工位不会因为显示顺序变化而绕过依赖。

## 十、异常排查与回滚

服务启动失败：

```bash
sudo systemctl status mes-web --no-pager
sudo journalctl -u mes-web -n 200 --no-pager
```

确认部署脚本输出的两个备份路径：

```text
数据库备份：/opt/mes/backups/manual/mes_db_before_update_*.dump
代码备份：/opt/mes/backups/manual/mes_code_before_update_*.tar.gz
```

不要删除备份。需要回滚时先停止服务，再恢复代码和数据库，最后启动并重新执行
“服务器状态自检”和“数据库字段自检”。

## 十一、维护完成清单

- [ ] Git commit 与准备包中的 `deploy_commit.txt` 一致。
- [ ] 单元测试全部通过。
- [ ] PostgreSQL 更新前备份存在且非空。
- [ ] 当前代码备份存在且非空。
- [ ] `mes-web`、`postgresql-16` 均为 active。
- [ ] Web 监听 `0.0.0.0:8000`。
- [ ] PostgreSQL 只监听本机 5432。
- [ ] stations 四个路线字段存在。
- [ ] 旧项目和旧工位数量未减少。
- [ ] A主线、B子线在左侧树正确分组。
- [ ] 工位管理新增、编辑和刷新回显正确。
- [ ] 父件、子件物料类型均不能手工输入。
- [ ] Windows 客户端可以下载配置和占用工位。
- [ ] PLC、扫码、螺丝、主条码切换和子物料绑定流程通过。
