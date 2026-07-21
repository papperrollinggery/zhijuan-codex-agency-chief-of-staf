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
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "这件事比较复杂，先跟我把目标和边界聊清楚，之后再做执行计划",
            "先讨论需求",
            "先把需求聊清楚",
            "根据以上讨论创建执行清单",
            "整理成任务清单",
            "开一个新对话执行",
            "单独创建任务执行",
            "安排团队来做",
            "安排几个专业角色",
            "持续更新进度",
            "归档任务",
            "沉淀长期资产",
            "总结到已有文档",
        ):
            self.assertIn(phrase, skill)
        description = skill.splitlines()[2]
        self.assertIn("choose only the value after =", description)
        for phase, status in (
            ("Discussion", "任务已接管｜需求讨论中"),
            ("Plan", "任务已接管｜正在创建执行清单"),
            ("Execution Launch", "任务已接管｜正在启动执行对话"),
            ("Execution Session/Progress", "任务已接管｜团队执行中"),
            ("Verify", "任务已接管｜正在验证"),
            ("Archive", "任务已接管｜正在归档"),
        ):
            self.assertIn(f"{phase}={status}", description)
        self.assertIn("notice only on line 2", description)
        self.assertIn("choose only the value after =", description)
        canonical_description = validate_package.parse_frontmatter(ROOT / "SKILL.md")[
            "description"
        ]
        self.assertLessEqual(
            len(canonical_description.strip()),
            validate_package.MAX_SKILL_DESCRIPTION_CHARS,
        )

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
            self.assertIn(exclusion, description)
        self.assertIn("thread or release readiness without work intent", description)
        for phase, status in (
            ("Discussion", "任务已接管｜需求讨论中"),
            ("Plan", "任务已接管｜正在创建执行清单"),
            ("Execution Launch", "任务已接管｜正在启动执行对话"),
            ("Execution Session/Progress", "任务已接管｜团队执行中"),
            ("Verify", "任务已接管｜正在验证"),
            ("Archive", "任务已接管｜正在归档"),
        ):
            self.assertIn(f"{phase}={status}", description)
        self.assertIn("notice only on line 2", description)
        bridge_description = validate_package.parse_frontmatter(
            bridge_root / "SKILL.md", install_skill.DISCOVERY_SKILL_NAME
        )["description"]
        self.assertLessEqual(
            len(bridge_description.strip()),
            validate_package.MAX_SKILL_DESCRIPTION_CHARS,
        )
        self.assertIn("no source-thread, history, memory, project, or Git lookup", description)
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
