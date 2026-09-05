from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install_skill  # noqa: E402
import validate_package  # noqa: E402


class ActivationLifecycleTests(unittest.TestCase):
    def test_canonical_description_covers_natural_lifecycle_intents(self) -> None:
        description = validate_package.parse_frontmatter(ROOT / "SKILL.md")["description"]
        for phrase in (
            "需求讨论", "执行清单", "独立任务", "模型路由", "进度", "验证", "归档",
            "普通问答", "简单代码修改", "AGENCY_WORKER", "源码维护不触发",
        ):
            self.assertIn(phrase, description)
        self.assertLessEqual(len(description), 150)

    def test_host_metadata_describes_the_staged_lifecycle(self) -> None:
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn(
            'short_description: "讨论需求、建立执行清单、启动执行团队并沉淀长期资产"',
            metadata,
        )
        self.assertIn(
            "先和我讨论需求；确认后建立任务执行清单，再创建独立执行对话推进任务、更新进度",
            metadata,
        )

    def test_action_named_discovery_bridge_is_lightweight_and_exclusion_safe(self) -> None:
        bridge_root = ROOT / "activation" / "agency-discuss-plan-execute-progress-archive"
        skill = (bridge_root / "SKILL.md").read_text(encoding="utf-8")
        metadata = (bridge_root / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("name: agency-discuss-plan-execute-progress-archive", skill)
        self.assertIn("../agency-chief-of-staff/SKILL.md", skill)
        self.assertIn("discovery-only bridge", skill)
        description = skill.splitlines()[2]
        for exclusion in (
            "ordinary questions",
            "one-line translation",
            "a simple code edit",
            "an explicit single-file fix",
            "AGENCY_WORKER",
            "maintenance of the Agency Chief of Staff source repository",
        ):
            self.assertIn(exclusion, skill)
        for phase in ("discuss", "plan", "launch", "progress", "verify", "archive"):
            self.assertIn(phase, description)
        self.assertIn("small tasks and source maintenance", description)
        bridge_description = validate_package.parse_frontmatter(
            bridge_root / "SKILL.md", install_skill.DISCOVERY_SKILL_NAME
        )["description"]
        self.assertLessEqual(len(bridge_description), 150)
        self.assertIn("Do not inspect a source task", skill)
        self.assertIn("before any other commentary", skill)
        self.assertIn("delegation envelope", skill)
        self.assertIn("Do not invoke this bridge again", skill)
        self.assertIn("allow_implicit_invocation: true", metadata)

    def test_durable_statuses_are_in_the_core_skill_contract(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for status in (
            "任务已接管｜需求讨论中",
            "任务已接管｜正在创建执行清单",
            "任务已接管｜正在启动执行对话",
            "任务已接管｜团队执行中",
            "任务已接管｜正在验证",
            "任务已接管｜正在归档",
        ):
            self.assertIn(status, skill)
        self.assertIn("source ID 不是读取授权", skill)
        self.assertIn("信息不足就把缺口作为唯一问题", skill)

    def test_canonical_and_legacy_implicit_policies_are_opposite(self) -> None:
        canonical = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        legacy = install_skill.render_runtime_bytes(
            ROOT, "agents/openai.yaml", install_skill.LEGACY_SKILL_NAME
        ).decode("utf-8")
        self.assertIn("allow_implicit_invocation: true", canonical)
        self.assertNotIn("allow_implicit_invocation: false", canonical)
        self.assertIn("allow_implicit_invocation: false", legacy)
        self.assertNotIn("allow_implicit_invocation: true", legacy)

    def test_lifecycle_intents_include_exclusions_and_all_four_phases(self) -> None:
        value = json.loads((ROOT / "assets/lifecycle-intents.json").read_text(encoding="utf-8"))
        self.assertEqual(set(value["phases"]), {"discussion", "plan", "execution_launch", "archive"})
        exclusions = "\n".join(value["exclusions"])
        for marker in (
            "单句翻译",
            "单文件明确修复",
            "普通信息问答",
            "合法 AGENCY_WORKER packet",
            "自身源码维护",
        ):
            self.assertIn(marker, exclusions)

    def test_repository_maintenance_is_not_a_runtime_activation_mechanism(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Repository Self-Maintenance Mode", agents)
        self.assertIn("不得加入 Runtime Bundle", agents)
        self.assertNotIn("AGENTS.md", install_skill.RUNTIME_FILES)

    def test_team_advice_stays_lightweight_but_uses_stable_position_names(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Direct/Focused 的团队咨询", skill)
        self.assertIn("不显示 Durable 阶段状态", skill)
        self.assertIn("不写 `.agency`、不创建 Agent/Task/Thread", skill)
        self.assertIn("稳定的用户可见职位名", skill)
        self.assertIn("没有结构化 Work Item 时不要为了咨询运行规划脚本", skill)


if __name__ == "__main__":
    unittest.main()
