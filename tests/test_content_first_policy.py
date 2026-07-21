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

    def test_durable_execution_has_a_no_spelunking_fast_path(self) -> None:
        lifecycle = (ROOT / "references/task-lifecycle.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Execution Root 快速路径", lifecycle)
        self.assertIn("--event-type work_started", lifecycle)
        self.assertIn("--event-type work_completed", lifecycle)
        self.assertIn("`PROGRESS.md` 在首个真实事件前可能尚不存在", lifecycle)
        self.assertIn("不运行 `--help`", lifecycle)
        self.assertIn("不读取 helper 源码", lifecycle)
        self.assertIn("--criterion-evidence-item", lifecycle)
        self.assertIn("文本本身含 `::`", lifecycle)
        self.assertIn("--validation-item", lifecycle)
        self.assertIn("--review-evidence", lifecycle)
        self.assertIn("high/critical risk", lifecycle)
        self.assertIn("review/release", lifecycle)
        self.assertIn("--cleanup-status closed", lifecycle)
        self.assertIn("--cleanup-status cleanup_blocked", lifecycle)
        self.assertIn("按单个 argv 传入", lifecycle)
        self.assertIn("不得使用 `eval`", lifecycle)

    def test_archive_has_one_command_fast_path_with_optional_deposit(self) -> None:
        archive = (ROOT / "references/knowledge-archiving.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Archive 快速路径", archive)
        self.assertIn("没有长期知识候选时", archive)
        self.assertIn("--knowledge-candidates", archive)
        self.assertIn("--deposit-knowledge", archive)
        self.assertIn("不是一个原子事务", archive)
        self.assertIn("`destination`", archive)
        self.assertIn("validate_task_archive.py", archive)
        self.assertIn("不先单独调用 `deposit_knowledge.py`", archive)
        self.assertIn("不通过手改 `task-index.json`", archive)
        self.assertIn("按单个 argv 传入", archive)
        fast_path = archive.split("## Archive 快速路径", 1)[1]
        base_command = fast_path.split("只有经过检查、确有可沉淀候选时", 1)[0]
        self.assertNotIn("--knowledge-candidates", base_command)
        self.assertNotIn("--deposit-knowledge", base_command)
        self.assertNotIn("`archive_dir`", fast_path)

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
