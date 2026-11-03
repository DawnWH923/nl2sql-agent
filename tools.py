"""
tools.py — Function Calling 工具集
取数 / 计算 / 绘图三类工具，供解读阶段的 LLM 循环编排调用：
- fetch_data：取数（复用 guard 只读校验，与主链路同等安全级别）
- compute：计算（sandbox 受限执行 pandas/numpy）
- plot：绘图（sandbox 受限执行 matplotlib，Agg 后端落盘 out/）
"""
import sqlite3

import pandas as pd
from langchain_core.tools import tool

from guard import SQLError, check_readonly
from sandbox import run as sandbox_run

DB = "business.db"

_last_df: pd.DataFrame | None = None  # 最近一次取数结果，沙箱内以 df 变量可见


def _query(sql: str) -> pd.DataFrame:
    """经只读守卫后执行查询，返回 DataFrame"""
    safe_sql = check_readonly(sql)
    conn = sqlite3.connect(DB)
    try:
        return pd.read_sql_query(safe_sql, conn)
    finally:
        conn.close()


def set_last_df(df: pd.DataFrame | None) -> None:
    """主链路 execute 节点把查询结果放入沙箱可见的共享状态"""
    global _last_df
    _last_df = df


def get_last_df() -> pd.DataFrame | None:
    return _last_df


@tool
def fetch_data(sql: str) -> str:
    """执行只读 SQL 查询获取数据。只允许单条 SELECT 语句，会经安全校验。"""
    global _last_df
    try:
        df = _query(sql)
    except SQLError as e:
        return f"取数被拒绝：{e}"
    _last_df = df
    return f"共 {len(df)} 行，列：{list(df.columns)}\n前5行预览：\n{df.head().to_string()}"


@tool
def compute(code: str) -> str:
    """在沙箱中执行 pandas/numpy 计算代码。df 变量是最近一次取数结果的 DataFrame，用 print 输出结果。
    注意：pd/numpy(按 np)/df 已预置，代码中不要写 import 语句。"""
    result = sandbox_run(code, df=_last_df)
    if result["error"]:
        return f"计算出错：{result['error']}"
    return result["stdout"] or "计算完成（无输出，请在代码里 print 结果）"


@tool
def plot(code: str) -> str:
    """在沙箱中用 matplotlib 对 df 绘图。plt.savefig 会自动保存图片并返回路径，无需指定目录。
    注意：pd/np/plt/df 已预置，代码中不要写 import 语句，例如：
    plt.bar(df['city'], df['sales']); plt.savefig('chart.png')"""
    result = sandbox_run(code, df=_last_df)
    if result["error"]:
        return f"绘图出错：{result['error']}"
    if result["artifacts"]:
        return "图片已保存：" + ", ".join(result["artifacts"])
    return "未检测到 savefig 调用，请在代码末尾调用 plt.savefig('name.png')"


ALL_TOOLS = [fetch_data, compute, plot]
