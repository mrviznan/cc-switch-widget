# CC Switch 桌面额度悬浮组件

Windows 上的轻量桌面小组件，用于查看 CC Switch 当前客户端、供应商余额和最近活跃会话消耗。

## 启动

双击 `启动悬浮组件.cmd` 启动独立 EXE。没有 EXE 时会回退到本机已安装的 Python 3.10。调试源码可双击 `启动源码.cmd`。

```text
python widget.py
```

组件默认显示为小型圆形悬浮球，只显示剩余额度。点击悬浮球展开详情；点击其他应用后自动收起。展开后的详情面板可拖动边缘和四角调整大小，右键可以刷新、展开/收起或退出。数据每 60 秒自动刷新。

## 数据来源

默认只读读取：

```text
C:\Users\岳溥泰\.cc-switch\cc-switch.db
```

可以通过环境变量 `CCSWITCH_DB_PATH` 覆盖数据库路径，通过 `CCSWITCH_NODE_PATH` 指定 Node.js 路径。

“本次对话”取 Codex 或 Claude 最近写入的带 `session_id` 的会话，并汇总该会话的请求费用和 Token。

余额优先执行当前供应商配置的 CC Switch `usage_script`。没有余额查询脚本时显示“余额查询未配置”，不会把会话费用当作供应商余额。

## 测试

```text
python -m unittest discover -s tests -v
```

测试只使用临时数据库，不会写入真实 CC Switch 数据库。

## 打包

`打包.spec` 会把本机 `D:\study\nodejs\node.exe` 一并打入 EXE，用于执行 CC Switch 的 JavaScript 余额查询脚本。生成文件位于 `dist\CC Switch 悬浮球.exe`。

重新打包可双击 `打包悬浮球.cmd`，或在此目录执行：

```text
.build-venv\Scripts\python.exe -m PyInstaller --noconfirm --clean 打包.spec
```

## 当前限制

- 第一版只支持 Windows。
- 余额是否能查询取决于 CC Switch 当前供应商是否配置并启用了 `usage_script`；本程序不会把已消费金额冒充剩余额度。
- 不包含历史图表、预算估算、开机自启、系统托盘和安装程序。
