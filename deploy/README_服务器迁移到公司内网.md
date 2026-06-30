# MES 服务器迁移到公司内网

MES 服务端监听 `0.0.0.0:8000`，客户端通过本机配置中的服务器 URL 访问。服务器内网地址变化时，不需要修改程序代码。

## 1. 查看公司内网地址

服务器接入公司网络后执行：

```bash
hostname -I
ip addr
```

记录公司分配的固定 IP。生产环境建议在路由器或 DHCP 服务中为 MES 服务器保留固定地址。

## 2. 检查 MES 服务

```bash
sudo systemctl status mes-web --no-pager
ss -lntp | grep 8000
```

端口应监听在 `0.0.0.0:8000` 或 `*:8000`，不能只监听 `127.0.0.1:8000`。

## 3. 检查防火墙

```bash
sudo firewall-cmd --list-ports
```

应包含：

```text
8000/tcp
```

如果没有，执行：

```bash
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

## 4. 修改客户端服务器地址

在桌面端打开：

```text
系统设置 -> 服务器设置
```

填写：

```text
http://公司服务器IP:8000
```

保存并点击“测试连接”。修改服务器地址不会改变本机 `client_id`。

## 5. 推荐使用内网 DNS

如果公司提供 DNS，建议使用稳定主机名：

```text
http://mes-server:8000
http://mes.company.local:8000
```

也可以在客户端 hosts 文件中将固定名称映射到服务器当前 IP。以后地址变化时只修改 DNS 或 hosts，不需要逐台修改程序。

## 6. PostgreSQL 保持本机连接

客户端不直接连接 PostgreSQL，不需要向客户端开放 `5432` 端口。Web 服务和 PostgreSQL 在同一服务器时继续使用：

```ini
[DATABASE]
type = postgresql
host = 127.0.0.1
port = 5432
database = mes_db
user = mes_user
password = 实际密码
```

`127.0.0.1` 不受服务器公司内网 IP 变化影响。

## 7. 版本更新

版本接口返回相对下载地址，例如：

```text
/api/client-update/download/v0.8.5/release
```

客户端会使用当前服务器 URL 自动拼接下载地址。服务器迁移后不需要修改已有版本记录。
