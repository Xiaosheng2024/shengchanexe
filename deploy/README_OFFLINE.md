# 离线部署说明

适用于客户现场无法访问外网的情况。

## 一、开发电脑提前准备

开发电脑需要能访问外网。执行：

```bat
deploy\download_offline_deps.bat
```

执行后会生成：

```text
offline_wheels\
```

这个目录里保存了离线安装需要的 Python 依赖包。

## 二、复制到客户电脑

把整个项目目录复制到 U 盘，再复制到客户电脑。

建议至少包含：

```text
main.py
web_admin.py
desktop_app\
web_admin_app\
shared\
requirements-client.txt
requirements-dev.txt
offline_wheels\
deploy\
```

## 三、客户电脑离线安装依赖

客户电脑需要先安装 Python。然后执行：

```bat
deploy\install_offline_deps.bat
```

该命令不会联网，只从 `offline_wheels` 安装依赖。

## 四、一键启动服务

启动网页后台服务：

```bat
deploy\start_web_service.bat
```

浏览器打开：

```text
http://127.0.0.1:8000
```

同时启动网页后台和桌面端：

```bat
deploy\start_all.bat
```

## 五、离线打包 exe

如果客户电脑不希望安装 Python，可在开发电脑或有 Python 的打包电脑上执行：

```bat
deploy\build_all_windows_offline.bat
```

生成：

```text
dist\QualityControlSystem.exe
dist\WebAdminService.exe
```

把 `dist` 目录复制给客户即可。客户双击：

```text
WebAdminService.exe
QualityControlSystem.exe
```

也可以继续使用：

```bat
deploy\start_all.bat
```
