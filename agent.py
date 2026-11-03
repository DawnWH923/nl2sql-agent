"""
agent.py — NL2SQL 数据分析 Agent
用 LangGraph 搭建：理解 → SQL生成 → 只读守卫 → 执行 → 解读
"""
import os
import sqlite3
import sqlglot
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from typing import TypedDict

load_dotenv()

SCHEMA = """
数据库表结构：
orders(order_id, category, city, amount, quantity, order_date)
  - category: 电子产品/服装/食品/家居/图书
  - city: 北京/上海/广州/深圳/杭州
  - amount: 订单金额
users(user_id, city, age, membership)
  - membership: 普通/银卡/金卡
"""

@tool
def execute_sql(sql: str) -> str:
    """只读执行 SQL 查询，返回结果。只允许 SELECT。"""
    # sqlglot 只读校验
    parsed = sqlglot.parse_one(sql)
    if parsed.key != "select":
        return "错误：只允许 SELECT 查询，写操作被拒绝"
    # 关键字黑名单
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
    if any(w in sql.upper() for w in forbidden):
        return "错误：检测到写操作关键字，已被拦截"
    conn = sqlite3.connect("business.db")
    cursor = conn.execute(sql)
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return f"列：{cols}\n结果：{rows[:20]}"

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

class State(TypedDict):
    question: str
    sql: str
    result: str
    answer: str

def generate_sql(state: State) -> State:
    prompt = f"""根据用户问题生成 SQLite 查询语句。
{SCHEMA}
只输出 SQL，不要解释。
用户问题：{state['question']}
SQL："""
    msg = llm.invoke(prompt)
    state["sql"] = msg.content.strip().replace("```sql", "").replace("```", "")
    return state

def guard_and_execute(state: State) -> State:
    try:
        state["result"] = execute_sql.invoke(state["sql"])
    except Exception as e:
        state["result"] = f"SQL 执行错误：{e}"
    return state

def explain(state: State) -> State:
    prompt = f"""根据 SQL 查询结果，用中文回答用户问题。
用户问题：{state['question']}
SQL：{state['sql']}
查询结果：{state['result']}
回答："""
    msg = llm.invoke(prompt)
    state["answer"] = msg.content
    return state

# 构建节点图
g = StateGraph(State)
g.add_node("generate_sql", generate_sql)
g.add_node("guard_and_execute", guard_and_execute)
g.add_node("explain", explain)
g.set_entry_point("generate_sql")
g.add_edge("generate_sql", "guard_and_execute")
g.add_edge("guard_and_execute", "explain")
g.add_edge("explain", END)

agent = g.compile()

if __name__ == "__main__":
    questions = [
        "每个城市的总销售额是多少？",
        "哪个品类的订单数量最多？",
        "金卡用户有多少人？",
    ]
    for q in questions:
        print(f"\n问题：{q}")
        r = agent.invoke({"question": q, "sql": "", "result": "", "answer": ""})
        print(f"SQL：{r['sql']}")
        print(f"回答：{r['answer']}")
