from __future__ import annotations

from app.agent.confirmation import _has_question, has_competing_signal


def test_clean_confirm_no_competing() -> None:
    assert has_competing_signal("yes") is False
    assert has_competing_signal("确认") is False
    assert has_competing_signal("confirm") is False


def test_clean_deny_no_competing() -> None:
    assert has_competing_signal("no") is False
    assert has_competing_signal("取消") is False


def test_mixed_confirm_change_competing() -> None:
    assert has_competing_signal("嗯行吧不过换成 express") is True
    assert has_competing_signal("yes but change to express") is True


def test_question_with_signal_competing() -> None:
    assert has_competing_signal("确认，退款多少？") is True
    assert has_competing_signal("yes, how much is the refund?") is True


def test_question_alone_no_signal_no_competing() -> None:
    # 提问但无 confirm/deny/change 信号 → 不算 competing
    assert has_competing_signal("退款多少？") is False


def test_has_question_chinese() -> None:
    assert _has_question("退款多少") is True
    assert _has_question("怎么取消") is True


def test_has_question_english() -> None:
    assert _has_question("how much?") is True
    assert _has_question("what is the status") is True


def test_has_question_none() -> None:
    assert _has_question("yes") is False
    assert _has_question("帮我取消订单") is False
