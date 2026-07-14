from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "scripts"))
from validate_visualization_data import validate_payload  # noqa: E402


class VisualizationDataTests(unittest.TestCase):
    def test_task_stage_requires_one_current_stage(self) -> None:
        payload = {
            "surface": "task-stage",
            "data": {
                "title": "交付准备",
                "goal": "完成当前修改",
                "next_step": "验证",
                "stages": [
                    {"label": "研究", "state": "completed"},
                    {"label": "实现", "state": "current"},
                    {"label": "验证", "state": "pending"},
                ],
            },
        }
        self.assertEqual(validate_payload(payload), "task-stage")
        payload["data"]["stages"][2]["state"] = "current"
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate_payload(payload)

    def test_decision_rejects_more_than_three_choices(self) -> None:
        payload = {
            "surface": "decision",
            "data": {
                "title": "选择",
                "summary": "一项会改变结果的选择",
                "recommended_index": 0,
                "choices": [
                    {"label": "A", "tradeoff": "慢"},
                    {"label": "B", "tradeoff": "快"},
                    {"label": "C", "tradeoff": "稳"},
                    {"label": "D", "tradeoff": "额外"},
                ],
            },
        }
        with self.assertRaisesRegex(ValueError, "2-3"):
            validate_payload(payload)

    def test_impact_requires_three_grounded_downstream_items_and_both_states(self) -> None:
        payload = {
            "surface": "impact",
            "data": {
                "title": "协议变更影响",
                "changed_item": "reviewer evidence binding",
                "next_review": "发布前复核",
                "downstream_items": [
                    {"item": "CLI reviewer", "disposition": "preserved", "impact": "接口不变"},
                    {"item": "native receipt", "disposition": "revisit", "impact": "补强绑定"},
                    {"item": "tests", "disposition": "revisit", "impact": "增加反例"},
                ],
            },
        }
        self.assertEqual(validate_payload(payload), "impact")
        payload["data"]["downstream_items"] = payload["data"]["downstream_items"][:2]
        with self.assertRaisesRegex(ValueError, "3-12"):
            validate_payload(payload)
        payload["data"]["downstream_items"] = [
            {"item": f"item-{index}", "disposition": "preserved", "impact": "unchanged"}
            for index in range(3)
        ]
        with self.assertRaisesRegex(ValueError, "both preserved and revisit"):
            validate_payload(payload)

    def test_numeric_trend_requires_real_units_and_dimensions(self) -> None:
        payload = {
            "surface": "numeric-trend",
            "data": {
                "title": "成本变化",
                "source_definition": "同一构建命令",
                "observations": [
                    {"name": "build-1", "value": 9.2, "unit": "seconds", "dimension": "run"}
                ],
            },
        }
        self.assertEqual(validate_payload(payload), "numeric-trend")
        del payload["data"]["observations"][0]["unit"]
        with self.assertRaisesRegex(ValueError, "unit"):
            validate_payload(payload)
        payload["data"]["observations"][0]["unit"] = "seconds"
        for non_finite in (float("nan"), float("inf"), float("-inf")):
            payload["data"]["observations"][0]["value"] = non_finite
            with self.assertRaisesRegex(ValueError, "finite"):
                validate_payload(payload)

    def test_image_review_requires_verified_regular_current_file_and_mount_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "current.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            payload = {
                "surface": "image-review",
                "data": {
                    "title": "当前图审阅",
                    "image_path": str(image),
                    "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                    "alt_text": "当前版本预览",
                    "review_target": "标题区域",
                    "region_findings": [{"region": "标题区", "finding": "对比度足够"}],
                },
                "mount_readback": {
                    "surface": "image-review",
                    "mount_id": "mount-1",
                    "rendered": True,
                    "image_path": str(image),
                    "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                },
            }
            self.assertEqual(
                validate_payload(payload, require_mount_readback=True), "image-review"
            )
            payload["data"]["verified_current"] = True
            mount_readback = payload.pop("mount_readback")
            with self.assertRaisesRegex(ValueError, "mount_readback is required"):
                validate_payload(payload)
            payload["mount_readback"] = mount_readback
            payload["mount_readback"]["rendered"] = False
            with self.assertRaisesRegex(ValueError, "rendered"):
                validate_payload(payload, require_mount_readback=True)
            with self.assertRaisesRegex(ValueError, "rendered"):
                validate_payload(payload)
            payload["mount_readback"]["rendered"] = True
            payload["mount_readback"]["image_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "mount_readback image_sha256"):
                validate_payload(payload)
            payload["mount_readback"]["image_sha256"] = payload["data"]["image_sha256"]
            payload["data"]["image_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "image_sha256"):
                validate_payload(payload)
            image.write_bytes(b"not an image")
            payload["data"]["image_sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
            payload["mount_readback"]["image_sha256"] = payload["data"]["image_sha256"]
            with self.assertRaisesRegex(ValueError, "supported image signature"):
                validate_payload(payload)


if __name__ == "__main__":
    unittest.main()
