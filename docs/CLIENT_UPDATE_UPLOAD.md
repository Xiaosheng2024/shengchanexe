# 客户端在线更新

## 管理端上传

进入“系统维护 / 客户端版本管理”，填写：

- 版本号
- 渠道：`stable` 或 `debug`
- 更新说明
- 是否启用
- EXE 或 ZIP 文件

`stable` ZIP 必须包含 `QualityControlSystem.exe`，`debug` ZIP 必须包含
`QualityControlSystem_Debug.exe`。ZIP 上传后，服务端提取对应 EXE 作为客户端
下载文件。

上传接口：

```text
POST /api/client-update/upload
multipart/form-data:
version, channel, file, release_notes, is_active, remark
```

上传接口要求 Web 管理员登录。

## 客户端接口

以下接口不要求 Web 登录：

```text
GET /api/client-update/latest?client_version=xxx&channel=stable
GET /api/client-update/download/{file_id}
```

旧版下载接口继续兼容：

```text
GET /api/client-update/download/{version}/release
GET /api/client-update/download/{version}/debug
```

## 服务器目录

文件保存在：

```text
/opt/mes/releases/client_updates
```

首次部署或权限异常时，在服务器执行：

```bash
SERVICE_USER="$(systemctl show mes-web -p User --value)"
[ -n "$SERVICE_USER" ] || SERVICE_USER=dell
sudo mkdir -p /opt/mes/releases/client_updates
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" /opt/mes/releases
sudo chmod -R 755 /opt/mes/releases
```

部署代码时必须保留 `/opt/mes/releases`，不得用更新包覆盖或删除。
