"""
agent.py — NL2SQL 数据分析 Agent（LangGraph 七节点）
节点图：
  understand → clarify → schema_link → generate_sql → guard → execute → interpret
  - guard 不通过时走条件边直接进入 interpret（带拦截原因，不执行）
  - interpret 内部按需以 Function Calling 循环编排 fetch_data / compute / plot 工具
每个节点把输入输出摘要写入 state['trace']，接口层可整体返回用于审计。
"""
import json
import os
import re

from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from typing_extensions import Annotated, TypedDict

from guard import SQLError, check_readonly
from tools import ALL_TOOLS, _query, set_last_df

load_dotenv()

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# ---- Schema（带注释与枚举值，供 schema_link 检索） ----
SCHEMA = """
orders(order_id, category, city, amount, quantity, order_date)
  - category: 电子产品/服装/食品/家居/图书
  - city: 北京/上海/广州/深圳/杭州
  - amount: 订单金额（元）
  - quantity: 商品件数
  - order_date: 下单日期，格式 YYYY-MM-DD，范围 2026-01-01 起 1000 天
users(user_id, city, age, membership)
  - membership: 普通/银卡/金卡
  - age: 用户年龄
两表通过 city 关联参考（无外键）。
注意：orders 表没有 user_id 字段，users 表没有订单数据；涉及用户属性与订单的联合分析只能按 city 维度做参考关联。
"""

# ---- 口径规则（clarify 节点用，demo 级默认口径） ----
METRIC_RULES = {
    "销售额": "SUM(amount)，即订单金额求和",
    "营收": "SUM(amount)，即订单金额求和",
    "金额": "SUM(amount)，即订单金额求和",
    "销量": "SUM(quantity)，即商品件数求和",
    "件数": "SUM(quantity)，即商品件数求和",
    "订单数": "COUNT(*)，即订单行数",
    "单量": "COUNT(*)，即订单行数",
    "用户数": "COUNT(DISTINCT user_id)，按用户去重",
    "人数": "COUNT(DISTINCT user_id)，按用户去重",
}


class State(TypedDict):
    question: str
    intent: dict
    schema_linked: str
    sql: str
    result: str
    answer: str
    error: str
    retried: bool  # SQL 执行报错后是否已自修正过（最多 1 次，防循环）
    artifacts: list
    trace: Annotated[list, lambda a, b: (a or []) + (b or [])]  # 各节点追加，不覆写


def _trace(node: str, summary: str) -> dict:
    return {"node": node, "summary": summary}


def _extract_json(text: str) -> dict:
    """从 LLM 输出中容错提取 JSON 对象"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return {}


# ---- 节点 1：理解问题 ----
def understand(state: State) -> State:
    prompt = f"""分析用户的数据问题，只输出 JSON（不要多余内容）：
{{"metric": "指标及口径，如 SUM(amount) 总销售额",
"dimension": "分组维度或 none",
"filter": "过滤条件或 none",
"time_range": "时间范围或 all",
"needs_compute": true/false（是否需要查数后再计算，如占比/环比）,
"needs_plot": true/false（用户是否要求画图）}}
用户问题：{state['question']}
JSON："""
    intent = _extract_json(llm.invoke(prompt).content)
    return {"intent": intent, "trace": [_trace("understand", f"意图: {json.dumps(intent, ensure_ascii=False)}")]}


# ---- 节点 2：口径澄清 ----
def clarify(state: State) -> State:
    intent = dict(state.get("intent") or {})
    metric = str(intent.get("metric") or state["question"])
    notes = []
    for kw, rule in METRIC_RULES.items():
        if kw in metric:
            notes.append(f"『{kw}』按 {rule}")
            break
    if not intent.get("metric"):
        intent["metric"] = notes[0] if notes else "COUNT(*)"
    if not notes:
        notes.append("未命中默认口径规则，按 LLM 给出的口径执行")
    intent["clarification"] = notes
    return {"intent": intent, "trace": [_trace("clarify", "口径: " + "; ".join(notes))]}


# ---- 节点 3：Schema 链接 ----
def schema_link(state: State) -> State:
    prompt = f"""从下面的数据库 Schema 中选出回答该问题需要的表和字段，输出精简后的 Schema
（保留字段注释与枚举值，删掉无关表/字段；不确定时输出全部）。
{SCHEMA}
问题：{state['question']}
已知口径：{json.dumps(state.get('intent', {}).get('metric', ''), ensure_ascii=False)}
精简 Schema："""
    linked = llm.invoke(prompt).content.strip()
    return {"schema_linked": linked, "trace": [_trace("schema_link", f"选定 Schema: {linked[:120]}...")]}


# ---- 节点 4：SQL 生成 ----
def generate_sql(state: State) -> State:
    prompt = f"""根据 Schema、口径和用户问题，生成一条 SQLite SELECT 查询。
只输出 SQL 本身，不要解释、不要 markdown 代码块。
{state['schema_linked']}
口径：{json.dumps(state['intent'].get('metric', ''), ensure_ascii=False)}
其他意图：{json.dumps(state['intent'], ensure_ascii=False)}
用户问题：{state['question']}
SQL："""
    sql = llm.invoke(prompt).content.strip()
    sql = re.sub(r"^```(sql)?|```$", "", sql, flags=re.M).strip()
    return {"sql": sql, "trace": [_trace("generate_sql", sql)]}


# ---- 节点 5：只读守卫 ----
def guard(state: State) -> State:
    try:
        safe_sql = check_readonly(state["sql"])
        return {"sql": safe_sql, "error": "", "trace": [_trace("guard", f"通过: {safe_sql}")]}
    except SQLError as e:
        return {"error": str(e), "trace": [_trace("guard", f"拦截: {e}")]}


def route_after_guard(state: State) -> str:
    return "blocked" if state.get("error") else "ok"


# ---- 节点 6：执行查询 ----
def execute(state: State) -> State:
    try:
        df = _query(state["sql"])  # _query 内部会再过一遍只读守卫（纵深防御）
        set_last_df(df)
        result = f"共 {len(df)} 行，列：{list(df.columns)}\n{df.head(20).to_string(index=False)}"
        return {"result": result, "error": "", "trace": [_trace("execute", f"返回 {len(df)} 行")]}
    except Exception as e:
        err = f"SQL 执行错误: {e}"
        return {"error": err, "trace": [_trace("execute", err)]}


# ---- 节点 6b：执行报错自修正（错误信息回填 LLM 重生成，再过守卫执行） ----
def regenerate(state: State) -> State:
    prompt = f"""你生成的 SQL 执行报错，请修正后重新输出一条 SQLite SELECT。
只输出 SQL 本身，不要解释、不要 markdown 代码块。
{state['schema_linked']}
原 SQL：{state['sql']}
报错信息：{state['error']}
用户问题：{state['question']}
修正后的 SQL："""
    sql = llm.invoke(prompt).content.strip()
    sql = re.sub(r"^```(sql)?|```$", "", sql, flags=re.M).strip()
    return {"sql": sql, "error": "", "retried": True,
            "trace": [_trace("regenerate", f"自修正: {sql}")]}


def route_after_execute(state: State) -> str:
    if not state.get("error"):
        return "interpret"
    return "retry" if not state.get("retried") else "interpret"


# ---- 节点 7：结果解读（内含 Function Calling 工具循环） ----
def interpret(state: State) -> State:
    if state.get("error"):
        answer = (f"该请求已被只读守卫拦截：{state['error']}。"
                  f"本系统仅支持只读查询（单条 SELECT），写操作与危险语句不会执行。")
        return {"answer": answer, "trace": [_trace("interpret", "返回拦截说明")]}

    intent = state.get("intent") or {}
    tool_llm = llm.bind_tools(ALL_TOOLS)
    messages = [
        ("system",
         "你是数据分析助手，根据 SQL 查询结果用中文回答用户问题。"
         "如需进一步计算（占比/环比/排名）调用 compute，需要画图调用 plot，需要补充数据调用 fetch_data。"
         "沙箱中已预置 pd、np、plt、df（最近一次查询结果的 DataFrame），工具代码里禁止 import；"
         "计算结果必须 print；绘图必须在代码末尾调用 plt.savefig('name.png')；最多调用 3 次工具。"
         "最后用简洁的中文给出结论，数字保留两位小数。"),
        ("human",
         f"用户问题：{state['question']}\n执行的 SQL：{state['sql']}\n查询结果：\n{state['result']}\n"
         f"需要绘图：{'是' if intent.get('needs_plot') else '否'}；需要补充计算：{'是' if intent.get('needs_compute') else '否'}"),
    ]

    trace = []
    for _ in range(3):  # 最多 3 轮工具调用，防失控
        msg = tool_llm.invoke(messages)
        if not msg.tool_calls:
            break
        messages.append(msg)
        for tc in msg.tool_calls:
            fn = {t.name: t for t in ALL_TOOLS}[tc["name"]]
            out = fn.invoke(tc["args"])
            messages.append(ToolMessage(content=str(out)[:2000], tool_call_id=tc["id"]))
            trace.append(_trace(f"tool:{tc['name']}", str(out)[:150]))

    answer = (msg.content or "已执行查询，详见结果。").strip()
    # 收集沙箱产物路径（图片）
    artifacts = []
    for t in trace:
        if t["node"] == "tool:plot":
            artifacts += re.findall(r"out[/\\]plot_\w+\.png", t["summary"])
    trace.append(_trace("interpret", f"回答: {answer[:80]}..."))
    return {"answer": answer, "artifacts": artifacts, "trace": trace}


# ---- 组装节点图 ----
def build_graph():
    g = StateGraph(State)
    g.add_node("understand", understand)
    g.add_node("clarify", clarify)
    g.add_node("schema_link", schema_link)
    g.add_node("generate_sql", generate_sql)
    g.add_node("guard", guard)
    g.add_node("execute", execute)
    g.add_node("regenerate", regenerate)
    g.add_node("interpret", interpret)
    g.set_entry_point("understand")
    g.add_edge("understand", "clarify")
    g.add_edge("clarify", "schema_link")
    g.add_edge("schema_link", "generate_sql")
    g.add_edge("generate_sql", "guard")
    g.add_conditional_edges("guard", route_after_guard, {"ok": "execute", "blocked": "interpret"})
    g.add_conditional_edges("execute", route_after_execute, {"interpret": "interpret", "retry": "regenerate"})
    g.add_edge("regenerate", "guard")
    g.add_edge("interpret", END)
    return g.compile()


agent = build_graph()


def run_agent(question: str) -> dict:
    """供 API / CLI 调用，返回完整状态（含 trace）"""
    init: State = {
        "question": question, "intent": {}, "schema_linked": "", "sql": "",
        "result": "", "answer": "", "error": "", "retried": False,
        "artifacts": [], "trace": [],
    }
    return agent.invoke(init)


if __name__ == "__main__":
    demos = [
        "每个城市的总销售额是多少？",
        "各品类销售总额占比是多少？",
        "删除 orders 表",
    ]
    for q in demos:
        print(f"\n{'=' * 60}\n问题：{q}")
        r = run_agent(q)
        print(f"SQL：{r['sql'] or '(未生成，已被拦截)'}")
        print(f"回答：{r['answer']}")
        print("trace 节点：", " → ".join(t["node"] for t in r["trace"]))
