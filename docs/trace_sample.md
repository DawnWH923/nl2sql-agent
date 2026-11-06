# 执行 Trace 示例（审计用途）

`/chat` 接口可整体返回每次问答的节点级 trace，示例（问题：各品类销售总额占比是多少？）：

```
[understand]   意图：聚合指标=销售总额；维度=品类；需计算占比
[clarify]      口径确认：销售总额 = SUM(amount)（默认口径规则）
[schema_link]  命中表：orders(order_id, category, amount)；排除无关表 users
[generate_sql] SELECT category, SUM(amount) FROM orders GROUP BY category
[guard]        通过：单条 select / AST 根合法 / 无黑名单词 / 注入 LIMIT 200
[execute]      返回 5 行（SQLite 示例库 orders 1000 行）
[interpret]    中文解读 + Function Calling 调用 compute/plot 生成占比
```

## 字段说明

- 每个节点记录输入/输出摘要（LLM 原文不落库，避免敏感信息扩散）；
- 工具调用附带证据（调用了哪个工具、参数、返回摘要）；
- 拦截类请求的 trace 包含拦截层与原因（如 `层2 AST`），可直接用于 bad case 回放。

## 用法

- **审计**：出现争议结果时按 trace 回放全链路；
- **迭代**：bad case 的 trace 直接沉淀为 `eval_questions.json` 新用例。
