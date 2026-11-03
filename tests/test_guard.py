"""
test_guard.py — 只读守卫单元测试（不依赖 LLM/API，可进 CI）
覆盖：多语句拼接、大小写混淆、危险关键字、空输入、LIMIT 注入、词边界不误杀
"""
import pytest

from guard import SQLError, check_readonly

PASS_CASES = [
    ("SELECT city, SUM(amount) FROM orders GROUP BY city", "基础聚合"),
    ("  SELECT 1", "前导空白"),
    ("select city from orders where created_at > '2024-01-01'", "小写 + created_at 不误杀"),
    ('SELECT * FROM orders WHERE note LIKE "%created%"', "LIKE 中含 create 不误杀"),
    ("SELECT * FROM orders LIMIT 10", "自带 LIMIT"),
]

REJECT_CASES = [
    ("SELECT 1; DROP TABLE users", "多语句拼接"),
    ("SELECT * FROM users; INSERT INTO orders VALUES (1)", "SELECT+INSERT 拼接"),
    ("DELETE FROM orders", "DELETE"),
    ("DrOp TaBlE orders", "大小写混淆 DROP"),
    ("UPDATE orders SET amount = 0", "UPDATE"),
    ("TRUNCATE TABLE orders", "TRUNCATE"),
    ("PRAGMA database_list", "PRAGMA"),
    ("ATTACH DATABASE 'x.db' AS x", "ATTACH"),
    ("", "空 SQL"),
    ("not a valid sql here", "非法语句"),
]


@pytest.mark.parametrize("sql,desc", PASS_CASES)
def test_pass(sql, desc):
    out = check_readonly(sql)
    assert out.upper().startswith("SELECT")
    assert "LIMIT" in out.upper(), "通过校验的 SQL 必须带 LIMIT"


@pytest.mark.parametrize("sql,desc", REJECT_CASES)
def test_reject(sql, desc):
    with pytest.raises(SQLError):
        check_readonly(sql)


def test_limit_injected_once():
    """没有 LIMIT 的查询被注入默认 LIMIT；已有 LIMIT 不重复包裹"""
    injected = check_readonly("SELECT * FROM orders")
    assert injected.endswith("LIMIT 200")
    untouched = check_readonly("SELECT * FROM orders LIMIT 10")
    assert "SELECT * FROM (SELECT" not in untouched, "已有 LIMIT 不应再包一层"
