"""Execute a CC Switch usage_script through the local Node.js runtime."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cc_switch_reader import Provider, find_node


@dataclass(frozen=True)
class QuotaResult:
    status: str
    remaining: Any = None
    unit: str = "USD"
    message: str = ""


def resource_path(name: str) -> Path:
    bundled_root = getattr(sys, "_MEIPASS", "")
    if bundled_root:
        return Path(bundled_root) / name
    return Path(__file__).with_name(name)


def query_quota(provider: Provider, node_path: str | None = None) -> QuotaResult:
    script = provider.usage_script
    if not script:
        return QuotaResult("unconfigured", message="余额查询未配置")
    node = node_path or find_node()
    if not node:
        return QuotaResult("error", message="未找到 Node.js，无法执行余额查询")

    payload = json.dumps(
        {
            "script": script,
            "settingsConfig": provider.settings_config,
        },
        ensure_ascii=False,
    )
    runner = resource_path("quota_query.js")
    timeout = max(3, min(int(script.get("timeout", 10) or 10), 30)) + 2
    try:
        completed = subprocess.run(
            [node, str(runner)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return QuotaResult("error", message="余额查询超时")
    except OSError:
        return QuotaResult("error", message="无法启动余额查询进程")

    try:
        output = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return QuotaResult("error", message="余额接口返回格式无法识别")
    if not output.get("ok"):
        return QuotaResult("error", message=str(output.get("error") or "余额查询失败"))
    result = output.get("result") or {}
    if not isinstance(result, dict) or result.get("remaining") is None:
        return QuotaResult("error", message="余额接口未返回剩余额度")
    if result.get("isValid") is False:
        return QuotaResult("error", message="余额凭据无效或已失效")
    return QuotaResult("ok", remaining=result.get("remaining"), unit=str(result.get("unit") or "USD"))
