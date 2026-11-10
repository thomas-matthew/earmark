import numpy as np
import pytest

from earmark.audio.voice import MAX_CHUNK_CHARS, chunks, level
from earmark.llm import prompts, relevance, writer
from earmark.llm.claude import ClaudeError
from earmark.llm.script import check, parse


def test_script_parsing_keeps_untagged_text_as_narration():
    script = parse("T: A title\nN: Hello there.\n\nQ: I tried it and it worked.\nstray line\nN:   ")
    assert script.title == "A title"
    assert [(l.voice, l.text) for l in script.lines] == [("N", "Hello there."), ("Q", "I tried it and it worked."), ("N", "stray line")]


def test_check_flags_quotes_not_in_sources_and_untagged_lines():
    sources = "[comment 1] I tried it, and it WORKED!\n[comment 2] Something else."
    findings = check("N: Intro.\nQ: I tried it and it worked\nQ: Words nobody said.\nloose", sources)
    kinds = [f["kind"] for f in findings]
    assert kinds.count("misquoted") == 1 and "Words nobody said." in findings[-1]["script_text"]
    assert kinds.count("format") == 1


@pytest.mark.parametrize("reply,include,said", [
    ('{"decision": "skip", "confidence": "high", "reason": "a deal"}', False, "skip"),
    ('Sure: {"decision": "skip", "confidence": "low", "reason": "maybe"}', True, "skip"),
    ('{"decision": "include", "confidence": "high", "reason": "ideas"}', True, "include"),
])
def test_low_confidence_skip_becomes_include(reply, include, said):
    decision = relevance.parse(reply)
    assert decision.include is include and decision.model_said == said


def test_relevance_reply_must_be_json():
    with pytest.raises(ClaudeError):
        relevance.parse("I think you should include it")


def test_writer_prompt_has_no_unfilled_placeholders():
    plain = writer.system_prompt("Reddit", None)
    with_media = writer.system_prompt("X", {"title": "A talk", "seconds": 600})
    for text in (plain, with_media):
        assert "{" not in text and "}" not in text
    assert "A talk" in with_media and "10 minutes" in with_media
    assert "Fix every issue" in prompts.FIX


def test_images_are_shrunk_before_the_writer_sees_them():
    from pathlib import Path

    from earmark.llm.tools import MAX_IMAGE_SIDE, shrink

    cover = (Path(__file__).parents[1] / "src/earmark/delivery/assets/cover.png").read_bytes()
    data, kind = shrink(cover, "image/png")
    assert kind == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n"
    width = int.from_bytes(data[16:20], "big")  # PNG header holds the width
    assert width <= MAX_IMAGE_SIDE


def test_chunks_respect_the_model_limit_and_keep_every_word():
    text = ("This is a sentence that goes on. " * 40) + ("word " * 200).strip() + "."
    pieces = chunks(text)
    assert all(len(p) <= MAX_CHUNK_CHARS for p in pieces)
    assert " ".join(pieces).split() == text.split()


def test_level_matches_loudness_and_leaves_silence_alone():
    loud = np.sin(np.linspace(0, 100, 24000)).astype(np.float32)
    assert abs(float(np.sqrt(np.mean(level(loud) ** 2))) - 0.06) < 1e-3
    quiet = np.zeros(100, dtype=np.float32)
    assert np.array_equal(level(quiet), quiet)
