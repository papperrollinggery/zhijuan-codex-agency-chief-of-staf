from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from protocol_contract import (  # noqa: E402
    EXECUTION_SESSION_DUTY,
    EXECUTION_SESSION_STOP,
    InvalidAgencyPacket,
    classify_agency_packet,
)


class ProtocolRecursionTests(unittest.TestCase):
    def test_malformed_reserved_worker_packet_fails_closed(self) -> None:
        with self.assertRaisesRegex(InvalidAgencyPacket, r"INVALID_PACKET \(worker\)"):
            classify_agency_packet(
                "AGENCY_WORKER: true\n"
                "委派目标：读取 README。\n"
                "读取范围：README.md。"
            )

    def test_malformed_reserved_execution_packet_fails_closed(self) -> None:
        packet = self.execution_packet(depth="1")
        with self.assertRaisesRegex(
            InvalidAgencyPacket, r"INVALID_PACKET \(execution_session\)"
        ):
            classify_agency_packet(packet)

    def test_valid_execution_root_is_depth_zero(self) -> None:
        kind, fields = classify_agency_packet(self.execution_packet(depth="0"))
        self.assertEqual(kind, "execution_session")
        self.assertIsNotNone(fields)
        self.assertEqual(fields["编排深度"], "0")

    def test_ordinary_text_does_not_enter_packet_parser(self) -> None:
        self.assertEqual(classify_agency_packet("请分析项目内容。"), ("ordinary", None))

    def test_reserved_marker_after_blank_line_fails_closed(self) -> None:
        with self.assertRaisesRegex(InvalidAgencyPacket, "exact first line"):
            classify_agency_packet("\nAGENCY_WORKER: true\n委派目标：x")

    def test_inline_marker_mention_remains_ordinary_text(self) -> None:
        text = "下面只是正文引用 `AGENCY_WORKER: true`，不是 packet。"
        self.assertEqual(classify_agency_packet(text), ("ordinary", None))

    def test_padded_or_bom_worker_markers_fail_closed(self) -> None:
        for marker in (
            " AGENCY_WORKER: true",
            "AGENCY_WORKER: true ",
            "\ufeffAGENCY_WORKER: true",
            "agency_worker : true",
        ):
            with self.subTest(marker=marker):
                with self.assertRaisesRegex(
                    InvalidAgencyPacket, r"INVALID_PACKET \(worker\)"
                ):
                    classify_agency_packet(marker + "\n委派目标：x")

    def test_indented_execution_marker_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            InvalidAgencyPacket, r"INVALID_PACKET \(execution_session\)"
        ):
            classify_agency_packet("  " + self.execution_packet(depth="0"))

    def test_execution_paths_must_bind_to_packet_task_id(self) -> None:
        valid = self.execution_packet(depth="0")
        replacements = (
            (
                ".agency/tasks/active/task-recursion-001/task-plan.json",
                ".agency/tasks/active/task-other-001/task-plan.json",
            ),
            (
                ".agency/tasks/active/task-recursion-001/TEAM_PLAN.json",
                "docs/not-a-team.json",
            ),
            (
                ".agency/tasks/active/task-recursion-001/PROGRESS.md",
                "README.md",
            ),
        )
        for before, after in replacements:
            with self.subTest(path=after):
                with self.assertRaisesRegex(InvalidAgencyPacket, "bound to task"):
                    classify_agency_packet(valid.replace(before, after))

    @staticmethod
    def execution_packet(*, depth: str) -> str:
        return "\n".join(
            [
                "AGENCY_EXECUTION_SESSION: true",
                "任务 ID：task-recursion-001",
                f"编排深度：{depth}",
                "项目根目录：/tmp/project",
                "任务清单：.agency/tasks/active/task-recursion-001/task-plan.json",
                "团队计划：.agency/tasks/active/task-recursion-001/TEAM_PLAN.json",
                "进度文件：.agency/tasks/active/task-recursion-001/PROGRESS.md",
                "执行模型请求：GPT-5.6 Sol",
                "推理强度请求：ultra",
                f"执行职责：{EXECUTION_SESSION_DUTY}",
                f"停止条件：{EXECUTION_SESSION_STOP}",
            ]
        )


if __name__ == "__main__":
    unittest.main()
