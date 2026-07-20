from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContentFirstPolicyTests(unittest.TestCase):
    def test_main_skill_stays_a_small_routing_map(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 160)
        self.assertLessEqual(len(re.findall(r"\S+", text)), 750)
        self.assertIn("解锁项目判断、协调真实并行、证明当前结果", text)
        self.assertIn("若不读取某个 reference 也能安全完成任务，就不要读取它", text)
        self.assertNotIn("所有普通主会话必须", text)
        self.assertNotIn("三个以上步骤", text)

    def test_direct_path_has_zero_governance_default(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        direct = next(line for line in text.splitlines() if line.startswith("| Direct |"))
        self.assertIn("不写 `.agency`", direct)
        self.assertIn("不建团队或 Thread", direct)
        self.assertIn("Direct/Focused 不要求固定", text)
        self.assertIn("单一研究、单一文档、普通单文件修改", text)

    def test_durable_assets_are_lazy_and_model_resolution_is_launch_only(self) -> None:
        lifecycle = (ROOT / "references/task-lifecycle.md").read_text(encoding="utf-8")
        self.assertIn("task-plan.json", lifecycle)
        self.assertIn("TASK_EXECUTION_CHECKLIST.md", lifecycle)
        self.assertIn("不写占位文件", lifecycle)
        self.assertIn("模型请求不属于 Plan 必填项", lifecycle)
        self.assertIn("complete_task.py", lifecycle)

    def test_behavior_suite_measures_outcomes_and_overhead(self) -> None:
        cases = {
            case["id"]: case
            for case in json.loads(
                (ROOT / "evals/behavior_cases.json").read_text(encoding="utf-8")
            )
        }
        for case_id in (
            "explicit-small-direct",
            "content-first-explicit-small-write",
            "lifecycle-small-task-exclusion",
        ):
            case = cases[case_id]
            self.assertEqual(case["max_collab_spawns"], 0)
            self.assertEqual(case["max_management_files"], 0)
        self.assertEqual(
            cases["content-first-explicit-small-write"]["expected_file_content"],
            'LABEL = "the"\n',
        )
        self.assertEqual(
            cases["invalid-reserved-worker-packet"]["must_contain"],
            ["INVALID_PACKET"],
        )

    def test_plan_smoke_forbids_eager_runtime_files(self) -> None:
        cases = json.loads((ROOT / "evals/behavior_cases.json").read_text(encoding="utf-8"))
        plan = next(case for case in cases if case["id"] == "lifecycle-plan-creation")
        absent = set(plan["expected_absent_artifacts"])
        for name in (
            "TEAM_PLAN.json",
            "PROGRESS.md",
            "progress.jsonl",
            "execution-session.json",
            "EXECUTION_LAUNCH_PROMPT.md",
        ):
            self.assertTrue(any(path.endswith(name) for path in absent), name)


if __name__ == "__main__":
    unittest.main()
