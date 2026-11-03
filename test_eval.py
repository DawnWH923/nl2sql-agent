"""
test_eval.py — 20 条黄金问题评测
断言：
  - 危险问题全部被只读守卫拦截（写操作 0 执行）
  - 正常问题全部产出非空回答
用法：py test_eval.py            # 全量跑（调 LLM）
      py test_eval.py --mock    # 只跑危险问题（不调 LLM 的部分也少）
"""
import json
import sys
import time

from agent import run_agent


def main() -> int:
    data = json.load(open("eval_questions.json", encoding="utf-8"))
    only_dangerous = "--mock" in sys.argv
    cases = [("dangerous", q) for q in data["dangerous"]]
    if not only_dangerous:
        cases += [("normal", q) for q in data["normal"]]

    passed, failed = 0, []
    for kind, q in cases:
        t0 = time.time()
        r = run_agent(q)
        cost = time.time() - t0
        if kind == "dangerous":
            ok = bool(r["error"]) and "拦截" in r["answer"]
        else:
            ok = bool(r["answer"]) and not r["error"]
        passed += ok
        if not ok:
            failed.append((kind, q, r["answer"][:80]))
        print(f"[{'PASS' if ok else 'FAIL'}] ({cost:4.1f}s) {kind:9s} | {q}")
        print(f"       SQL: {r['sql'][:80] or '(无)'}")

    total = len(cases)
    print(f"\n结果：{passed}/{total} 通过")
    if failed:
        print("失败用例：")
        for kind, q, ans in failed:
            print(f"  - [{kind}] {q}\n    {ans}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
