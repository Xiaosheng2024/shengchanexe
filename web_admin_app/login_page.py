from html import escape


def render_login_page(error=""):
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MES 管理后台登录</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f3f4f6;
      font-family: Arial, "Microsoft YaHei", sans-serif; color: #111827; }}
    .login {{ width: min(420px, calc(100vw - 32px)); background: white; border: 1px solid #d1d5db;
      border-radius: 8px; padding: 28px; box-shadow: 0 12px 30px rgba(0,0,0,.08); }}
    h1 {{ margin: 0 0 24px; font-size: 23px; }}
    label {{ display: block; margin: 14px 0 7px; font-weight: 700; }}
    input {{ width: 100%; height: 42px; border: 1px solid #cbd5e1; border-radius: 6px;
      padding: 8px 10px; font-size: 16px; }}
    button {{ width: 100%; height: 42px; margin-top: 22px; border: 0; border-radius: 6px;
      background: #2563eb; color: white; font-size: 16px; font-weight: 700; cursor: pointer; }}
    .error {{ margin-bottom: 12px; padding: 10px; border-radius: 6px; background: #fee2e2; color: #991b1b; }}
  </style>
</head>
<body>
  <form class="login" method="post" action="/login" autocomplete="on">
    <h1>MES 管理后台登录</h1>
    {error_html}
    <label for="username">账号</label>
    <input id="username" name="username" autocomplete="username" required autofocus>
    <label for="password">密码</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">登录</button>
  </form>
</body>
</html>"""
