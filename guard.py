"""
guard.py — SQL 只读守卫（三层防护）
1. 多语句检测：sqlglot.parse 返回语句列表，>1 条直接拒绝（防止 SELECT;DROP 拼接）
2. AST 校验：每条语句解析后的语法树根必须是 select（字符串匹配可被大小写/注释/嵌套绕过，AST 不会）
3. 词边界黑名单：PRAGMA/ATTACH 等 SQLite 特有危险语句的兜底拦截
最后统一注入 LIMIT，限制返回行数。
"""
import re

import sqlglot

FORBIDDEN = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "PRAGMA", "ATTACH", "DETACH", "VACUUM", "REPLACE", "REINDEX",
]
DEFAULT_LIMIT = 200


class SQLError(Exception):
    """守卫不通过的 SQL"""


def check_readonly(sql: str) -> str:
    """校验 SQL 只读；通过则返回加了 LIMIT 的安全 SQL，不通过抛 SQLError"""
    sql = (sql or "").strip().rstrip(";")

    # 1. 多语句检测：sqlglot.parse 返回每条语句的 AST，>1 即拼接攻击
    try:
        stmts = sqlglot.parse(sql, dialect="sqlite")
    except sqlglot.errors.ParseError as e:
        raise SQLError(f"SQL 解析失败: {e}")
    stmts = [s for s in stmts if s is not None]
    if not stmts:
        raise SQLError("空 SQL")
    if len(stmts) > 1:
        raise SQLError(f"检测到 {len(stmts)} 条语句，只允许单条 SELECT")

    # 2. AST 校验：语法树根节点必须是 select（真正理解结构，不受大小写/注释/嵌套影响）
    for stmt in stmts:
        if stmt.key != "select":
            raise SQLError(f"只允许 SELECT 查询，检测到 {stmt.key.upper()} 写操作")

    # 3. 词边界黑名单：兜底拦 SQLite 特有语句（\b 保证不误杀 created_at 这类字段名）
    upper = sql.upper()
    for word in FORBIDDEN:
        if re.search(rf"\b{word}\b", upper):
            raise SQLError(f"检测到危险关键字 {word}，已被拦截")

    # 4. 注入 LIMIT 限制返回行数（已有 LIMIT 则不重复加）
    if not re.search(r"\bLIMIT\s+\d+\b", upper):
        sql = f"SELECT * FROM ({sql}) LIMIT {DEFAULT_LIMIT}"
    return sql
