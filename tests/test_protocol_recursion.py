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
    classify_transport_source_prompt,
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

    def test_exact_codex_delegation_envelope_carries_execution_root(self) -> None:
        source = "019f7a4e-f1be-7771-9f67-38fcde417f49"
        kind, fields = classify_agency_packet(
            self.codex_envelope(self.execution_packet(depth="0"), source=source)
        )
        self.assertEqual(kind, "execution_session")
        self.assertEqual(fields["任务 ID"], "task-recursion-001")

    def test_codex_delegation_envelope_fails_closed_when_malformed(self) -> None:
        valid = self.execution_packet(depth="0")
        invalid_envelopes = (
            self.codex_envelope(valid, source="not-a-task-id"),
            " " + self.codex_envelope(valid),
            "\n" + self.codex_envelope(valid),
            "transport follows\n" + self.codex_envelope(valid),
            self.codex_envelope(valid).replace(
                "<codex_delegation>", '<codex_delegation version="1">', 1
            ),
            self.codex_envelope(valid).replace(
                "<codex_delegation>", "<codex_delegation >", 1
            ),
            self.codex_envelope(valid).replace(
                "<codex_delegation>", "<codex_delegation/>", 1
            ),
            self.codex_envelope(valid).replace("<codex_delegation>\n", "<codex_delegation"),
            self.codex_envelope(valid).replace("\n", "\r\n"),
            self.codex_envelope(valid + "\n</input>"),
            self.codex_envelope(
                "AGENCY_WORKER: true\n委派目标：x\n读取范围：x\n"
                "期望产物：ROLE、SUMMARY、ARTIFACTS、VERIFICATION、BLOCKERS\n"
                "验证要求：读取当前结果\n停止条件：返回证据后停止，不得继续派发。"
            ),
        )
        for envelope in invalid_envelopes:
            with self.subTest(envelope=envelope[:80]):
                with self.assertRaises(InvalidAgencyPacket):
                    classify_agency_packet(envelope)

    def test_ordinary_text_does_not_enter_packet_parser(self) -> None:
        self.assertEqual(classify_agency_packet("请分析项目内容。"), ("ordinary", None))

    def test_reserved_marker_after_blank_line_fails_closed(self) -> None:
        with self.assertRaisesRegex(InvalidAgencyPacket, "exact first line"):
            classify_agency_packet("\nAGENCY_WORKER: true\n委派目标：x")

    def test_inline_marker_mention_remains_ordinary_text(self) -> None:
        text = "下面只是正文引用 `AGENCY_WORKER: true`，不是 packet。"
        self.assertEqual(classify_agency_packet(text), ("ordinary", None))

    def test_transport_source_allows_later_protocol_examples_in_user_text(self) -> None:
        text = (
            "请维护协议文档，不要启动 Runtime。\n\n"
            "示例：\n"
            "AGENCY_EXECUTION_SESSION: true\n"
            "执行 Skill：$agency-chief-of-staff\n"
            "<codex_delegation>"
        )
        with self.assertRaises(InvalidAgencyPacket):
            classify_agency_packet(text)
        self.assertEqual(
            classify_transport_source_prompt(text), ("ordinary", None)
        )

    def test_transport_source_still_rejects_first_line_protocol_sessions(self) -> None:
        kind, _ = classify_transport_source_prompt(
            self.execution_packet(depth="0")
        )
        self.assertEqual(kind, "execution_session")
        worker = "\n".join(
            (
                "AGENCY_WORKER: true",
                "委派目标：读取 README",
                "读取范围：README.md",
                "写入范围：无",
                "期望产物：WORKER_RESULT，均填实际读回值",
                "验证要求：读取当前 README 并回传",
                "停止条件：返回唯一终态；不启动、不派发。",
            )
        )
        worker_kind, _ = classify_transport_source_prompt(worker)
        self.assertEqual(worker_kind, "worker")

        malformed = (
            "AGENCY_EXECUTION_SESSION: true\nnot a valid packet",
            "AGENCY_EXECUTION_SESSION: true # launch",
            "AGENCY_WORKER: true example",
            "AGENCY_WORKER: false",
            "AGENCY_EXECUTION_SESSION true",
            "AGENCY_EXECUTION_SESSION protocol example",
            "AGENCY_WORKER",
            "AGENCY_WORKER=true",
            "AGENCY_EXECUTION_SESSION=true",
            "AGENCY_WORKER：true",
            "AGENCY_WORKER/true",
            "AGENCY_WORKER#true",
            "AGENCY_WORKER.true",
            self.codex_envelope(self.execution_packet(depth="0")).replace(
                "<codex_delegation>",
                '<codex_delegation version="1">',
                1,
            ),
        )
        for prompt in malformed:
            with self.subTest(prompt=prompt.splitlines()[0]):
                with self.assertRaises(InvalidAgencyPacket):
                    classify_transport_source_prompt(prompt)

        for ordinary in (
            "AGENCY_WORKER_EXTRA is an application constant.",
            "AGENCY_WORKERISH is not a reserved namespace.",
            "AGENCY_EXECUTION_SESSION2 is not a reserved namespace.",
        ):
            with self.subTest(ordinary=ordinary):
                self.assertEqual(
                    classify_transport_source_prompt(ordinary),
                    ("ordinary", None),
                )

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
                "执行 Skill：$agency-chief-of-staff",
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

    @staticmethod
    def codex_envelope(
        packet: str,
        *,
        source: str = "019f7a4e-f1be-7771-9f67-38fcde417f49",
    ) -> str:
        return (
            "<codex_delegation>\n"
            f"  <source_thread_id>{source}</source_thread_id>\n"
            f"  <input>{packet}</input>\n"
            "</codex_delegation>"
        )


if __name__ == "__main__":
    unittest.main()
