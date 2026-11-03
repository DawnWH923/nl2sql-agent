"""
api.py — FastAPI 对话接口（带执行 trace 审计）
启动：uvicorn api:app --port 8001
接口：
  GET  /health  健康检查
  POST /chat    {"question": "..."} → {"answer", "sql", "result", "error", "artifacts", "trace"}
trace 记录七节点每步的输入输出摘要与工具调用证据，可整体用于审计。
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import run_agent

app = FastAPI(title="NL2SQL 数据分析 Agent API", version="2.0.0")


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="自然语言数据问题")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        r = run_agent(req.question)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 执行异常: {e}")
    return {
        "answer": r["answer"],
        "sql": r["sql"],
        "result": r["result"],
        "error": r["error"],
        "artifacts": r["artifacts"],
        "trace": r["trace"],
    }
