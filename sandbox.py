"""
sandbox.py — 受限 Python 执行沙箱
计算与绘图代码在这里执行：
- 清空 __builtins__，只暴露白名单对象（pandas/numpy/matplotlib/上游查询结果 df）
- matplotlib 强制 Agg 无显示后端；savefig 进程级 patch：任何绘图产物重定向到 out/ 并记录
- 禁止 import（__import__ 不在白名单 + 预处理剥掉 import 行），杜绝沙箱内引入 os/sys 等危险模块
"""
import io
import os
import re
import uuid
from contextlib import redirect_stdout

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")  # 无显示环境绘图
import matplotlib.pyplot as plt  # noqa: E402

OUT_DIR = "out"
_artifacts: list[str] = []

# 进程级 patch 一次：savefig 强制落盘 out/ 并记录产物（Agg 后端本进程专用，无副作用）
_orig_savefig = plt.savefig


def _safe_savefig(*args, **kwargs):
    fname = f"plot_{uuid.uuid4().hex[:8]}.png"
    full = os.path.join(OUT_DIR, fname)
    _orig_savefig(full, **kwargs)
    _artifacts.append(full)
    return None


plt.savefig = _safe_savefig

_WHITELIST = {
    "pd": pd, "np": np, "plt": plt,
    "len": len, "range": range, "float": float, "int": int,
    "round": round, "sorted": sorted, "sum": sum, "min": min,
    "max": max, "abs": abs, "list": list, "dict": dict,
    "str": str, "print": print, "True": True, "False": False,
}

_IMPORT_RE = re.compile(r"^\s*(?:import\s+.+|from\s+.+\s+import\s+.+)$", re.M)


def _strip_imports(code: str) -> str:
    """剥掉 import 行：白名单模块（pd/np/plt）已预置，LLM 习惯性写的 import 等价于无操作；
    白名单外的 import 本就无法通过 __import__ 执行，提前剥掉避免报 ImportError。"""
    return _IMPORT_RE.sub("", code)


def run(code: str, df: pd.DataFrame | None = None, user_id: str = "") -> dict:
    """在受限命名空间执行代码。
    沙箱内变量 df 是最近一次取数结果的 DataFrame（无取数则为 None）。
    返回 {stdout, error, artifacts}；artifacts 是生成的图片路径列表。
    """
    env = dict(_WHITELIST)
    env["df"] = df
    env["__builtins__"] = {}  # 关闭内建：无法 import / open / eval / exec
    _artifacts.clear()

    buf = io.StringIO()
    error = None
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        with redirect_stdout(buf):
            exec(_strip_imports(code), env, env)  # noqa: S102 — 沙箱命名空间已锁定
    except Exception as e:  # 沙箱内任何异常都转成字符串返回，不中断主流程
        error = f"{type(e).__name__}: {e}"
        plt.close("all")

    return {"stdout": buf.getvalue().strip(), "error": error,
            "artifacts": list(_artifacts)}
