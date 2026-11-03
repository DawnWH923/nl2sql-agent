# NL2SQL 数据分析 Agent

用自然语言查询数据库，自动生成 SQL、只读校验、执行并解读结果。基于 LangGraph + DeepSeek。

## 功能
- 自然语言 → SQL 自动生成
- 双重只读保护：sqlglot AST 解析 + 关键字黑名单
- SQL 执行后自动用中文解读结果
- 全程可审计

## 架构
```
理解问题 → 生成SQL → 只读守卫 → 执行查询 → 中文解读
```

## 技术栈
- LangGraph（节点图编排）
- DeepSeek-Chat（SQL 生成与解读）
- sqlglot（SQL AST 校验）
- SQLite（示例数据库）

## 快速开始
```bash
pip install langchain-openai langgraph sqlglot python-dotenv
python build_db.py    # 建示例数据库
python agent.py       # 测试三个问题
```

## 示例
```
你：每个城市的总销售额是多少？
SQL：SELECT city, SUM(amount) FROM orders GROUP BY city;
回答：上海 217,552、北京 201,484、广州 185,902...
```

## 安全机制
- sqlglot 解析 AST，只允许 SELECT
- INSERT/UPDATE/DELETE/DROP 等关键字直接拦截
- 写操作 0 执行

## 作者
吴晗 | [GitHub](https://github.com/DawnWH923)
