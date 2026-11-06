# 只读守卫测试用例（guard.py 三层防护）

## 防护层次

| 层 | 手段 | 防什么 |
|----|------|--------|
| 1 | `sqlglot.parse` 语句数 > 1 拒绝 | `SELECT 1; DROP TABLE users` 多语句拼接 |
| 2 | 每条语句 AST 根节点必须是 `select` | 大小写混淆、注释包裹、子查询夹带写操作 |
| 3 | 词边界黑名单（INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/PRAGMA/ATTACH/...） | SQLite 特有危险语句兜底（\b 防误杀 `created_at` 等字段名） |

放行后统一注入 `LIMIT 200`（已有 LIMIT 不重复加）；执行层 `_query` 再跑一次 `check_readonly`，纵深防御。

## 用例表

| # | 输入 SQL | 预期 | 命中层 |
|---|----------|------|--------|
| 1 | `SELECT * FROM orders` | 放行（自动加 LIMIT） | - |
| 2 | `SELECT count(*) FROM orders; DROP TABLE users` | 拒绝：检测到 2 条语句 | 层1 |
| 3 | `/*comment*/ DELETE FROM orders WHERE 1=1` | 拒绝：AST 根为 delete | 层2 |
| 4 | `select * from orders where id = 1 or 1=1; --` 单条 | 放行（单条 select，注释不改变 AST 根） | - |
| 5 | `WITH t AS (UPDATE users SET ...) SELECT * FROM t` | 拒绝：CTE 内写操作，AST 校验捕获 | 层2 |
| 6 | `PRAGMA database_list` | 拒绝：黑名单 PRAGMA | 层3 |
| 7 | `ATTACH DATABASE 'x.db' AS x` | 拒绝：黑名单 ATTACH | 层3 |
| 8 | `select created_at from orders` | 放行（\b 词边界不误杀 created_at） | - |
| 9 | `DeLeTe FrOm` 大小写混淆变体 | 拒绝（AST 不受大小写影响） | 层2 |
| 10 | `SELECT * FROM orders LIMIT 50` | 放行（不重复注入 LIMIT） | - |

## 设计原则

字符串黑名单永远可以被构造绕过，所以**以 AST 校验为主、黑名单为兜底**；所有拦截在"执行前"发生，拦截即零副作用。
