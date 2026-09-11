# CC Switch 桌面额度悬浮球

Windows 上的轻量桌面小组件，用于查看 [CC Switch](https://github.com/farion1231/cc-switch) 当前客户端、供应商余额和最近活跃会话消耗。

## 下载使用（推荐）

无需安装 Python 或 Node.js，直接从 [Releases](../../releases) 下载最新的 `CC-Switch-Ball.exe`，双击即可运行。

> 首次运行时 Windows SmartScreen 可能提示"未知发布者"，点击"更多信息 → 仍要运行"即可。这是未签名程序的正常提示。

## 从源码运行

需要已安装 Python 3（含 Tkinter）。双击 `启动悬浮组件.cmd` 启动：优先启动 EXE，没有 EXE 时回退到本机 Python。调试源码可双击 `启动源码.cmd`。

```text
python widget.py
```

组件默认显示为小型圆形悬浮球，只显示剩余额度。点击悬浮球展开详情；点击其他应用后自动收起。展开后的详情面板可拖动边缘和四角调整大小，右键可以刷新、展开/收起或退出。数据每 60 秒自动刷新。

## 数据来源

默认只读读取当前用户目录下的 CC Switch 数据库：

```text
%USERPROFILE%\.cc-switch\cc-switch.db
```

可以通过环境变量 `CCSWITCH_DB_PATH` 覆盖数据库路径，通过 `CCSWITCH_NODE_PATH` 指定 Node.js 路径。

"本次对话"取 Codex 或 Claude 最近写入的带 `session_id` 的会话，并汇总该会话的请求费用和 Token。

余额优先执行当前供应商配置的 CC Switch `usage_script`。没有余额查询脚本时显示"余额查询未配置"，不会把会话费用当作供应商余额。

## 测试

```text
python -m unittest discover -s tests -v
```

测试只使用临时数据库，不会写入真实 CC Switch 数据库。

## 打包

打包时 PyInstaller 会自动探测本机 Node.js（环境变量 `CCSWITCH_NODE_PATH` → PATH → `C:\Program Files\nodejs`），一并打入 EXE，用于执行 CC Switch 的 JavaScript 余额查询脚本。生成文件位于 `dist\CC-Switch-Ball.exe`。

重新打包可双击 `打包悬浮球.cmd`，或在此目录执行：

```text
.build-venv\Scripts\python.exe -m PyInstaller --noconfirm --clean 打包.spec
```

推送 `v*` 格式的标签（或手动触发）时，GitHub Actions 会在云端自动完成打包并把 EXE 上传到对应 Release。

> 注：GitHub Release 附件的文件名不支持中文和空格，因此对外发布的文件统一命名为 `CC-Switch-Ball.exe`（程序界面仍是中文）。

## 当前限制

- 只支持 Windows。
- 余额是否能查询取决于 CC Switch 当前供应商是否配置并启用了 `usage_script`；本程序不会把已消费金额冒充剩余额度。
- 程序按当前 CC Switch 的数据库结构（`providers`、`proxy_request_logs` 表）编写；CC Switch 后续大版本若更改表结构，可能需要同步更新本工具。
- 不包含历史图表、预算估算、开机自启、系统托盘和安装程序。
