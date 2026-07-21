---
name: agency-discuss-plan-execute-progress-archive
description: "Discovery bridge for complex staged projects: discuss goals and boundaries before planning, create an execution checklist, launch a separate task/team, track progress, verify, archive, and retain reusable knowledge. Before any notice, read, lookup, or tool call, choose only the value after = for the user's intent as the exact first line: Discussion=任务已接管｜需求讨论中; Plan=任务已接管｜正在创建执行清单; Execution Launch=任务已接管｜正在启动执行对话; Execution Session/Progress=任务已接管｜团队执行中; Verify=任务已接管｜正在验证; Archive=任务已接管｜正在归档. Required Skill-use notice only on line 2 of the same message. In Discussion, no source-thread, history, memory, project, or Git lookup unless explicitly requested. Exclude ordinary questions, one-line translation, a simple code edit, an explicit single-file fix, a valid AGENCY_WORKER packet, a mere mention of thread or release readiness without work intent, and maintenance of the Agency Chief of Staff source repository."
---

# Agency Project Lifecycle Discovery Bridge

This is a discovery-only bridge for hosts that trim Skill descriptions or later-sorted Skill names from a large catalog.

For a matched lifecycle request, make the phase status the first user-visible line before any other commentary, explanation, tool call, or lookup. In Discussion the exact line is `任务已接管｜需求讨论中`. If the host requires a Skill-use notice, put it after that line in the same message; never send a separate notice first. Do not inspect a source task, conversation history, memory, project files, or Git merely because the host supplied a delegation envelope; unless the user explicitly requests current material, treat missing context as the one open question.

When the request genuinely needs a staged project lifecycle, read `../agency-chief-of-staff/SKILL.md` completely once and follow that canonical Skill. The canonical Skill owns every lifecycle decision and user-visible status. Do not invoke this bridge again from the canonical flow.

Do not use this bridge for ordinary questions, one-line translation, a simple code edit, an explicit single-file fix, a valid `AGENCY_WORKER` packet, a mere mention of thread or release readiness, or maintenance of the Agency Chief of Staff source repository.

Do not create plans, files, tasks, Agents, or Threads from this bridge itself.
