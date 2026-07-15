from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_URL = (
    "https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf"
)


class RepositoryDiscoveryTests(unittest.TestCase):
    def test_llms_index_has_spec_shape_and_existing_source_links(self) -> None:
        path = ROOT / "llms.txt"
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertEqual(lines[0], "# Agency Chief of Staff for Codex")
        self.assertTrue(any(line.startswith("> ") for line in lines[1:5]))
        self.assertIn("emerging `llms.txt` proposal", text)
        self.assertIn("does not", text)
        self.assertIn("Unreleased", text)
        self.assertIn("Claude and Fable", text)
        self.assertLess(len(text.encode("utf-8")), 12_000)

        links = re.findall(r"\[[^]]+\]\((https://[^)]+)\)", text)
        self.assertGreaterEqual(len(links), 12)
        prefix = REPOSITORY_URL + "/blob/main/"
        for link in links:
            if link == REPOSITORY_URL + "/releases":
                continue
            self.assertTrue(link.startswith(prefix), link)
            relative = link.removeprefix(prefix)
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_discovery_metadata_is_bounded_and_linked(self) -> None:
        guide = (ROOT / "docs" / "REPOSITORY_DISCOVERY.md").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")

        self.assertIn("does not apply GitHub settings", guide)
        self.assertIn("not a ranking guarantee", guide)
        self.assertIn("fresh maintainer authorization", guide)
        self.assertIn("[LLM 索引](llms.txt)", readme)
        self.assertIn(
            "[Repository discovery and release metadata](REPOSITORY_DISCOVERY.md)",
            docs_index,
        )

        topic_section = guide.split("Suggested topics:\n", 1)[1].split(
            "\nThese values", 1
        )[0]
        topics = re.findall(r"^- `([^`]+)`$", topic_section, flags=re.MULTILINE)
        self.assertGreaterEqual(len(topics), 8)
        self.assertLessEqual(len(topics), 20)
        self.assertEqual(len(topics), len(set(topics)))
        for topic in topics:
            self.assertRegex(topic, r"^[a-z0-9-]{1,50}$")


if __name__ == "__main__":
    unittest.main()
