import pytest

from multimodal_studio.ai import TranscriptSegment, segments_to_srt


def test_segments_to_srt_produces_standard_timestamps():
    rendered = segments_to_srt(
        [
            TranscriptSegment(0.0, 1.25, "Hello"),
            TranscriptSegment(61.0, 62.5, "World"),
        ]
    )
    assert "00:00:00,000 --> 00:00:01,250" in rendered
    assert "00:01:01,000 --> 00:01:02,500" in rendered


def test_segments_to_srt_rejects_invalid_segment():
    with pytest.raises(ValueError):
        segments_to_srt([TranscriptSegment(2, 1, "bad")])
