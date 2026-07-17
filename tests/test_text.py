from __future__ import annotations

import unittest

from codex_gamepad.text import chunk_for_kokoro, clean_for_speech


class SpeechTextTests(unittest.TestCase):
    def test_markdown_cleanup_omits_code_and_urls(self) -> None:
        source = """# Done

- Open [the report](https://example.test/report).
- Run `codex --help`.

```python
secret = 'not spoken'
```
"""
        cleaned = clean_for_speech(source)
        self.assertIn("Open the report.", cleaned)
        self.assertIn("Run codex --help.", cleaned)
        self.assertIn("Code block omitted.", cleaned)
        self.assertNotIn("secret", cleaned)
        self.assertNotIn("https://", cleaned)

    def test_chunks_are_bounded_and_lossless(self) -> None:
        text = " ".join(
            [
                "The first sentence has enough detail to be useful.",
                "The second sentence continues the synthetic explanation.",
                "The third sentence closes the example without private data.",
                "The fourth sentence makes the response a little longer.",
            ]
        )
        chunks = chunk_for_kokoro(text, target_characters=100, max_characters=130)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 130 for chunk in chunks))
        self.assertEqual(" ".join(chunks), text)

    def test_long_unbroken_prose_is_split(self) -> None:
        chunks = chunk_for_kokoro("word " * 200, max_characters=80, target_characters=60)
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 80 for chunk in chunks))

    def test_single_long_token_is_bounded(self) -> None:
        chunks = chunk_for_kokoro("x" * 500, max_characters=80, target_characters=60)
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 80 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
