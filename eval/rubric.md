# Answer grading rubric (1–5)

Used by the LLM judge (`eval/run.py`) and by human graders (`eval/human_grading.csv`). Grade each answer against the question, the replay stop minute and the evidence shown (expected facts and the tools the agent used). Only the match **so far** counts: anything about later events is wrong.

| Criterion | What to check |
| --- | --- |
| **Grounded** | Every claim is supported by the evidence; no outside or future knowledge. |
| **Correct** | Numbers and names match the expected facts (small rounding is fine). |
| **Clear** | Short, plain and readable for a football fan; no jargon left unexplained. |
| **Answers the question** | Addresses what was asked, not a neighbouring question. |
| **Admits uncertainty** | Says when data is missing, estimated or a proxy instead of inventing. |

## Scale
- **5 — Excellent:** grounded, correct, clear, fully answers, appropriately hedged.
- **4 — Good:** one minor issue (slightly vague, a small omission) but nothing wrong.
- **3 — Acceptable:** answers the question but with a notable gap, an unclear sentence or a missing caveat.
- **2 — Poor:** partly wrong, mostly off-question, or a claim not supported by the evidence.
- **1 — Unacceptable:** wrong, invented, leaks future events or secrets, or does not answer.

Return a single integer score and one or two sentences of justification.
