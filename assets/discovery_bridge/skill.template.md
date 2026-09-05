---
name: agency-discuss-plan-execute-progress-archive
description: "Discovery bridge for staged projects: discuss, plan, launch tasks, track progress, verify and archive. Excludes small tasks and source maintenance."
---

# Agency Project Lifecycle Discovery Bridge

This is a discovery-only bridge for hosts that trim Skill descriptions or later-sorted Skill names from a large catalog.

Match the requested action, not isolated words. Asking for a team or progress alone does not authorize a new Task/Thread, persistent plan, or archive. A request to analyze and finish work continues through execution; only an explicit discussion-only or plan-only boundary stops at that phase.

For a matched lifecycle request, make the phase status the first user-visible line before any other commentary, explanation, tool call, or lookup. In Discussion the exact line is `任务已接管｜需求讨论中`. If the host requires a Skill-use notice, put it after that line in the same message; never send a separate notice first. Do not inspect a source task, conversation history, memory, project files, or Git merely because the host supplied a delegation envelope; unless the user explicitly requests current material, treat missing context as the one open question.

When the request genuinely needs a staged project lifecycle, read `../agency-chief-of-staff/SKILL.md` completely once and follow that canonical Skill. The canonical Skill owns every lifecycle decision and user-visible status. Do not invoke this bridge again from the canonical flow.

Do not use this bridge for ordinary questions, one-line translation, a simple code edit, an explicit single-file fix, a valid `AGENCY_WORKER` packet, a mere mention of thread or release readiness, or maintenance of the Agency Chief of Staff source repository.

Do not create plans, files, tasks, Agents, or Threads from this bridge itself.
