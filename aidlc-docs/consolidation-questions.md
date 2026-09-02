# Documentation Consolidation — Questions

You asked to merge the two documentation sets into one. There are two sets today:

- **`.kiro/specs/generic-document-repository-saas/`** — Kiro spec: requirements.md (194), design.md (894),
  tasks.md (453), tasks.meta.json (335), .config.kiro. Read by Kiro's Spec panel.
- **`aidlc-docs/`** — AI-DLC: reverse-engineering artifacts + aidlc-state.md + audit.md.

Please answer, then tell me you're done.

## Question 1
Which should be the single source of truth?

A) `aidlc-docs/` — fold the Kiro spec into the AI-DLC structure (requirements → inception/requirements, design → inception/application-design, tasks → construction/plans). AI-DLC becomes canonical.

B) `.kiro/specs/...` — fold the AI-DLC reverse-engineering artifacts into the Kiro spec folder. The Kiro Spec panel stays canonical.

X) Other (please describe after [Answer]: tag below)

[Answer]: 

## Question 2
For the source location after consolidation, should I:

A) MOVE files (remove originals) and leave a short pointer/README in the old location noting where content now lives

B) MOVE files and delete the old folder entirely (no pointer)

C) COPY files (keep both physical copies; originals remain but are marked superseded)

X) Other (please describe after [Answer]: tag below)

[Answer]: 

## Question 3
Note: If the source of truth becomes `aidlc-docs/` (Q1=A), Kiro's **Spec panel will no longer show**
this spec (it only reads `.kiro/specs/`). Is that acceptable?

A) Yes — I'm using AI-DLC docs now; losing the Spec-panel view is fine

B) No — keep it visible in the Kiro Spec panel (favor Q1=B, or keep a copy under .kiro/specs)

X) Other (please describe after [Answer]: tag below)

[Answer]: 
