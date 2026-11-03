# NL2SQL 数据分析 Agent

用自然语言查询数据库：自动理解意图、澄清口径、生成 SQL、只读校验、执行并解读结果，全程带执行 trace 审计。基于 LangGraph + DeepSeek + sqlglot。

## 功能
- 🧠 七节点 LangGraph 编排：理解 → 口径澄清 → Schema 链接 → SQL 生成 → 只读守卫 → 执行 → 结果解读
- 🛡️ 双重只读校验：sqlglot AST 解析（多语句检测 + 语法树根校验）+ 词边界关键字黑名单，执行前统一注入 LIMIT
- 🔧 Function Calling 编排取数 / 计算 / 绘图工具（占比、环比、图表等延伸分析）
- 🔒 Python 沙箱隔离执行计算与绘图：清空 `__builtins__`、白名单命名空间、禁 `import`
- 📋 全程执行 trace：每个节点的输入输出摘要 + 工具调用证据，API 可整体返回用于审计
- 🌐 FastAPI 封装 `/chat` 对话接口

## 架构
```
用户问题
  └─ understand    LLM 结构化意图（指标/维度/过滤/是否需要计算或绘图）
      └─ clarify   口径澄清（"销售额"→SUM(amount) 等默认口径规则）
          └─ schema_link   从完整 Schema 中选出相关表字段
              └─ generate_sql   生成 SQLite SELECT
                  └─ guard   只读守卫（多语句 + AST + 黑名单 + LIMIT 注入）
                      ├─ 通过 → execute   执行查询（执行前二次校验，纵深防御）
                      │            ├─ 成功 → interpret   中文解读 + Function Calling
                      │            │            工具循环（fetch_data / compute / plot）
                      │            └─ 报错 → regenerate   错误信息回填 LLM 自修正
                      │                     （仅 1 次，修正后再过守卫执行）
                      └─ 拦截 → interpret   返回拦截说明（不执行）
```

## 技术栈
- LangGraph（七节点图编排 + 条件边）
- DeepSeek-Chat（意图理解 / SQL 生成 / 结果解读）
- sqlglot 30.x（SQL AST 解析校验）
- pandas / matplotlib（沙箱内计算与绘图）
- FastAPI + Uvicorn（REST 接口）
- SQLite（示例业务库：orders 1000 行 + users 200 行，`build_db.py` 一键重建）

## 只读守卫：为什么三层
| 层 | 手段 | 防什么 |
|---|---|---|
| 1 | `sqlglot.parse` 返回语句数 > 1 即拒绝 | `SELECT 1; DROP TABLE users` 多语句拼接 |
| 2 | 每条语句 AST 根节点必须是 `select` | 大小写混淆、注释、嵌套子查询里的写操作 |
| 3 | 词边界黑名单（PRAGMA/ATTACH/...） | SQLite 特有危险语句兜底 |

执行层再做一次守卫（`_query` 复用 `check_readonly`），加上统一 `LIMIT 200` 注入——纵深防御。

## 快速开始
```bash
pip install -r requirements.txt

# 1. 配置 .env
echo DEEPSEEK_API_KEY=your_key > .env

# 2. 构建示例数据库（如已有 business.db 可跳过）
python build_db.py

# 3a. 命令行演示（含危险 SQL 拦截示例）
python agent.py

# 3b. 启动 API
uvicorn api:app --port 8001
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "各品类销售总额占比是多少？"}'

# 4. 跑 20 条黄金问题评测（16 正常 + 4 危险）
python test_eval.py
```

## 项目结构
```
nl2sql-agent/
├── agent.py            # LangGraph 七节点主流程 + Function Calling 工具循环
├── guard.py            # 只读守卫：多语句检测 + AST 校验 + 词边界黑名单 + LIMIT 注入
├── sandbox.py          # 受限 Python 沙箱（清空 __builtins__ + 白名单 + Agg 绘图落盘）
├── tools.py            # Function Calling 工具：fetch_data / compute / plot
├── api.py              # FastAPI /chat（返回 answer + trace 审计记录）
├── build_db.py         # 构建示例 SQLite 业务库
├── eval_questions.json # 20 条黄金问题（16 正常 + 4 危险）
├── test_eval.py        # 批量评测：危险问题全拦截、正常问题全回答
└── requirements.txt
```

## 评测结果
`python test_eval.py` 实测 **20/20 通过**：
- 4 条危险问题（DROP / UPDATE / INSERT / PRAGMA）**全部被拦截，写操作 0 执行**
- 16 条正常问题全部产出非空中文回答，含：
  - 占比类问题（`compute` 沙箱计算）
  - "画一张各城市销售额的柱状图"（`plot` 工具真实生成 PNG 到 `out/`）
  - Schema 幻觉导致的 JOIN 报错由 `regenerate` 自修正后成功执行
