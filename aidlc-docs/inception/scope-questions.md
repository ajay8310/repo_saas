# AI-DLC Scope Questions

You asked to "Use AI-DLC". This is an existing, fully-built codebase (multi-tenant SaaS document
repository). AI-DLC is a workflow for planning and building a change; it needs a goal to drive it.
Please answer the questions below by filling in the letter after each `[Answer]:` tag, then tell me
you're done.

## Question 1
What do you want AI-DLC to do for this project?

A) Reverse-engineer the existing codebase into AI-DLC documentation (architecture, components, APIs, interaction diagrams, tech stack) — no code changes

B) Plan and implement a NEW feature or change (describe it in Question 2) using the full adaptive workflow

C) Formalize the existing `.kiro/specs/` content into the AI-DLC document structure (requirements, design, units) without new code

D) Run the complete AI-DLC lifecycle end-to-end on this repo as a demonstration (reverse-engineering → requirements → planning → construction)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2
IF you chose B (or a variant), briefly describe the feature/change you want built. Otherwise leave blank.

[Answer]: 

## Question 3
How deep should the work go?

A) Minimal — just the essential artifacts/steps for the chosen goal

B) Standard — normal depth with the key documents and checkpoints

C) Comprehensive — full detail, diagrams, traceability, and all applicable stages

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question: Security Extensions
Should security extension rules be enforced for this project?

A) Yes — enforce all SECURITY rules as blocking constraints (recommended for production-grade applications)

B) No — skip all SECURITY rules (suitable for PoCs, prototypes, and experimental projects)

X) Other (please describe after [Answer]: tag below)

[Answer]: No

## Question: Resiliency Extensions
Should the resiliency baseline be applied to this project? (Directional design-time best practices
from the AWS Well-Architected Reliability Pillar — a starting point, not a production-readiness guarantee.)

A) Yes — apply the resiliency baseline as directional best practices and design-time guidance

B) No — skip the resiliency baseline (suitable for PoCs, prototypes, and experimental projects)

X) Other (please describe after [Answer]: tag below)

[Answer]: Yes

## Question: Property-Based Testing Extension
Should property-based testing (PBT) rules be enforced for this project?

A) Yes — enforce all PBT rules as blocking constraints (recommended for business logic, data transformations, serialization, stateful components)

B) Partial — enforce PBT rules only for pure functions and serialization round-trips

C) No — skip all PBT rules (suitable for simple CRUD, UI-only, or thin integration layers)

X) Other (please describe after [Answer]: tag below)

[Answer]: A
