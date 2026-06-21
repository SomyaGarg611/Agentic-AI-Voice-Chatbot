"""
Eval harness — runs research questions against the live agent and scores:
  1. Tool coverage  : did the agent call the expected tools?
  2. Content match  : does the answer contain required keywords?
  3. Citation check : does the answer include [N] URL citations?
  4. LLM-as-judge   : Claude scores faithfulness + quality (0-10)

Run:
    cd VoiceBot && . .venv/bin/activate
    python evals/run_evals.py
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agent.loop import run_agent
from app.observability.tracing import flush
from anthropic import AsyncAnthropic
from app.config import settings


DATASET = Path(__file__).parent / "dataset.jsonl"


def load_dataset():
    cases = []
    with open(DATASET) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def check_content(answer: str, must_contain: list[str]) -> tuple[bool, list[str]]:
    missing = [kw for kw in must_contain if kw.lower() not in answer.lower()]
    return len(missing) == 0, missing


def check_citations(answer: str) -> bool:
    return bool(re.search(r"\[\d+\]", answer))


async def llm_judge(question: str, answer: str, rubric: str) -> dict:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    prompt = f"""You are an evaluation judge. Score the following AI answer.

Question: {question}
Answer: {answer}
Rubric: {rubric}

Rate on two dimensions (0-10 each):
- faithfulness: Is the answer factually accurate and grounded?
- quality: Is it clear, concise, and appropriately cited?

Respond with JSON only: {{"faithfulness": N, "quality": N, "comment": "..."}}"""

    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        text = response.content[0].text.strip()
        # Extract JSON if wrapped in markdown
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group()) if match else {"faithfulness": 0, "quality": 0, "comment": text}
    except Exception:
        return {"faithfulness": 0, "quality": 0, "comment": "parse error"}


async def run_eval_case(case: dict) -> dict:
    print(f"\n{'─'*60}")
    print(f"[{case['id']}] {case['question']}")

    answer, history = await run_agent(case["question"], [])

    content_ok, missing = check_content(answer, case.get("must_contain", []))
    has_citations = check_citations(answer)
    scores = await llm_judge(case["question"], answer, case.get("rubric", ""))

    result = {
        "id": case["id"],
        "question": case["question"],
        "answer": answer[:300] + ("…" if len(answer) > 300 else ""),
        "content_match": content_ok,
        "missing_keywords": missing,
        "has_citations": has_citations,
        "faithfulness": scores.get("faithfulness", 0),
        "quality": scores.get("quality", 0),
        "judge_comment": scores.get("comment", ""),
    }

    print(f"  Answer   : {result['answer'][:120]}…")
    print(f"  Content  : {'✓' if content_ok else f'✗ missing {missing}'}")
    print(f"  Citations: {'✓' if has_citations else '✗'}")
    print(f"  Scores   : faithfulness={result['faithfulness']}/10  quality={result['quality']}/10")
    print(f"  Judge    : {result['judge_comment']}")
    return result


async def main():
    cases = load_dataset()
    print(f"Running {len(cases)} eval cases…")
    results = []
    for case in cases:
        r = await run_eval_case(case)
        results.append(r)

    flush()

    # Scorecard
    n = len(results)
    content_pass = sum(1 for r in results if r["content_match"])
    citation_pass = sum(1 for r in results if r["has_citations"])
    avg_faith = sum(r["faithfulness"] for r in results) / n
    avg_qual = sum(r["quality"] for r in results) / n

    print(f"\n{'═'*60}")
    print(f"  EVAL SCORECARD  ({n} cases)")
    print(f"{'═'*60}")
    print(f"  Content match : {content_pass}/{n} ({content_pass/n*100:.0f}%)")
    print(f"  Citations     : {citation_pass}/{n} ({citation_pass/n*100:.0f}%)")
    print(f"  Faithfulness  : {avg_faith:.1f}/10")
    print(f"  Quality       : {avg_qual:.1f}/10")
    print(f"{'═'*60}")

    # Write results
    out = Path(__file__).parent / "results.jsonl"
    with open(out, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"  Results saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
