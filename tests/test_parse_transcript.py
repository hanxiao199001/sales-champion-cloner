"""手动转写稿解析的单元测试（纯函数，无外部依赖）。"""

from app.main import _parse_manual_transcript


def test_labeled_lines():
    text = "销售：您好，看房吗\n客户：想看看两居室"
    segments = _parse_manual_transcript(text)
    assert len(segments) == 2
    assert segments[0]["speaker"] == "boss"
    assert segments[0]["text"] == "您好，看房吗"
    assert segments[1]["speaker"] == "client"


def test_plain_text_defaults_to_boss():
    segments = _parse_manual_transcript("这是一段没有标签的话")
    assert len(segments) == 1
    assert segments[0]["speaker"] == "boss"


def test_blank_lines_skipped():
    segments = _parse_manual_transcript("A: 第一句\n\n\nB: 第二句\n")
    assert len(segments) == 2
    assert segments[1]["speaker"] == "client"


def test_unknown_label_kept_as_boss_full_line():
    segments = _parse_manual_transcript("旁白：背景音")
    assert segments[0]["speaker"] == "boss"
    assert segments[0]["text"] == "旁白：背景音"
