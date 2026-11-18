import io

import pytest

from hp_scanner.prompt import MAX_ATTEMPTS, QuickChoices, prompt_choices


def answers(*replies):
    """A fake ``input`` returning ``replies`` in order, recording the questions asked."""
    it = iter(replies)
    asked = []

    def read(question):
        asked.append(question)
        reply = next(it)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    read.asked = asked
    return read


def test_enter_everywhere_gives_defaults():
    read = answers("", "", "")
    assert prompt_choices(read, io.StringIO()) == QuickChoices("pdf", "medium", None)
    assert read.asked == [
        "Type (pdf/jpg/png) [pdf]: ",
        "Quality (low/medium/high) [medium]: ",
        "File name prefix [none]: ",
    ]


def test_answers_are_used_and_normalized():
    read = answers("JPG", " High ", "  receipts ")
    assert prompt_choices(read, io.StringIO()) == QuickChoices("jpg", "high", "receipts")


def test_invalid_answer_is_reasked():
    out = io.StringIO()
    read = answers("tiff", "png", "ultra", "low", "../etc", "ok")
    assert prompt_choices(read, out) == QuickChoices("png", "low", "ok")
    text = out.getvalue()
    assert "Invalid type" in text and "Invalid quality" in text and "Invalid prefix" in text


def test_gives_up_after_max_attempts():
    read = answers(*(["nope"] * MAX_ATTEMPTS))
    with pytest.raises(ValueError, match="No valid answer"):
        prompt_choices(read, io.StringIO())


def test_eof_accepts_defaults():
    read = answers(EOFError(), EOFError(), EOFError())
    assert prompt_choices(read, io.StringIO()) == QuickChoices()
