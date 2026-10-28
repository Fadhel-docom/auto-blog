# Mandatory Agent Preflight — Home Organization Ideas

Before any task in this repository, ChatGPT and any collaborating agent MUST:

1. Open and read the current description and newest comments of operations issue [#109](https://github.com/Fadhel-docom/auto-blog/issues/109). Do not rely on memory, old summaries, or detached reports first.
2. Extract the latest verified state, completed owner actions, active work, constraints, and unresolved questions. Never ask the owner to repeat an action without checking the log and current evidence.
3. Verify claims against the relevant live source before saying a task is missing, completed, fixed, or tested. If verification is unavailable, say "UNVERIFIED" and do not guess.
4. If issue #109 cannot be read, STOP project work and report that access/verification failed; do not proceed from assumptions.
5. After material work, add a concise update to issue #109 with what changed, evidence/tests, what remains unverified, and the next safe step.
6. Do not modify the legacy GitHub Pages URL/configuration or purchase/use a custom domain unless the owner explicitly changes the existing project constraints.

## Required preflight note

At the start of each project task, internally confirm:
- [ ] Read latest #109 comments in this session
- [ ] Recorded owner actions already completed
- [ ] Checked current branch/PR/live state relevant to the task
- [ ] Defined a testable completion condition

This file is a persistent repository instruction, not an automatic enforcement mechanism. Agents must still perform the checks; where possible, future CI/PR checks should enforce testable requirements.
