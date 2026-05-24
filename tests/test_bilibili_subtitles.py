from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_bilibili_subtitles


class BilibiliSubtitleTests(unittest.TestCase):
    def test_parse_bvid_and_page_from_url(self) -> None:
        ref = fetch_bilibili_subtitles.parse_video_ref(
            "https://www.bilibili.com/video/BV1YtZcBKESW/?p=2&spm_id_from=333.1387"
        )

        self.assertEqual(ref.bvid, "BV1YtZcBKESW")
        self.assertEqual(ref.page, 2)

    def test_select_cid_uses_requested_page(self) -> None:
        info = {
            "aid": 123,
            "cid": 10,
            "pages": [
                {"page": 1, "cid": 10},
                {"page": 2, "cid": 20},
            ],
        }

        self.assertEqual(fetch_bilibili_subtitles.select_cid(info, page=2), 20)

    def test_extract_subtitle_tracks_accepts_both_api_shapes(self) -> None:
        payloads = [
            {"data": {"subtitle": {"subtitles": [{"lan": "ai-en", "subtitle_url": "//example.com/en.json"}]}}},
            {"data": {"subtitle": {"list": [{"lan": "zh-CN", "url": "https://example.com/zh.json"}]}}},
        ]

        tracks = []
        for payload in payloads:
            tracks.extend(fetch_bilibili_subtitles.extract_subtitle_tracks(payload))

        self.assertEqual([track.language for track in tracks], ["ai-en", "zh-CN"])
        self.assertEqual(tracks[0].url, "https://example.com/en.json")

    def test_choose_subtitle_prefers_chinese_then_falls_back(self) -> None:
        tracks = [
            fetch_bilibili_subtitles.SubtitleTrack(
                language="ai-en",
                language_doc="英语",
                url="https://example.com/en.json",
            ),
            fetch_bilibili_subtitles.SubtitleTrack(
                language="ai-ja",
                language_doc="日语",
                url="https://example.com/ja.json",
            ),
        ]

        selected = fetch_bilibili_subtitles.choose_subtitle_track(
            tracks,
            preferred_languages=["zh-CN", "zh"],
            fallback_any=True,
        )

        self.assertEqual(selected.language, "ai-en")

    def test_render_markdown_and_srt_use_float_seconds(self) -> None:
        result = fetch_bilibili_subtitles.SubtitleResult(
            bvid="BV1YtZcBKESW",
            aid=116469866241004,
            cid=37843175694,
            title="调色教程",
            language="ai-en",
            language_doc="英语",
            body=[
                {"from": 7.5, "to": 9.26, "content": "Hi, I'm Qingshan."},
                {"from": 9.59, "to": 11.176, "content": "Summer is coming."},
            ],
            subtitle_url="https://example.com/subtitle.json",
        )

        markdown = fetch_bilibili_subtitles.render_markdown(result)
        srt = fetch_bilibili_subtitles.render_srt(result)

        self.assertIn("## 00:07", markdown)
        self.assertIn("Hi, I'm Qingshan.", markdown)
        self.assertIn("00:00:07,500 --> 00:00:09,260", srt)
        self.assertIn("00:00:09,590 --> 00:00:11,176", srt)

    def test_write_output_uses_safe_filename(self) -> None:
        result = fetch_bilibili_subtitles.SubtitleResult(
            bvid="BV1YtZcBKESW",
            aid=1,
            cid=2,
            title='调色/教程:*?"',
            language="zh-CN",
            language_doc="中文",
            body=[{"from": 1.0, "to": 2.0, "content": "内容"}],
            subtitle_url="https://example.com/subtitle.json",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = fetch_bilibili_subtitles.write_output(
                result,
                output_dir=Path(directory),
                output_format="markdown",
            )

            self.assertTrue(path.exists())
            self.assertNotIn("/", path.name)
            self.assertTrue(path.name.endswith(".transcript.md"))

    def test_subtitle_track_fetch_uses_wbi_player_endpoint(self) -> None:
        called_urls = []

        def fake_fetch_json(url: str, **_kwargs: object) -> dict[str, object]:
            called_urls.append(url)
            return {"code": 0, "data": {"subtitle": {"subtitles": []}}}

        original = fetch_bilibili_subtitles.fetch_json
        fetch_bilibili_subtitles.fetch_json = fake_fetch_json
        try:
            fetch_bilibili_subtitles.fetch_subtitle_tracks(
                fetch_bilibili_subtitles.VideoRef("BV1YtZcBKESW"),
                aid=116469866241004,
                cid=37843175694,
            )
        finally:
            fetch_bilibili_subtitles.fetch_json = original

        self.assertIn("/x/player/wbi/v2?", called_urls[0])
        self.assertNotIn("/x/player/v2?", called_urls[0])


if __name__ == "__main__":
    unittest.main()
