from __future__ import annotations

from jpnote_app.quiz.service import QuizService, QuizSessionResult, QuizSourceDetails
from jpnote_app.quiz.session_models import (
    AnswerSnapshot,
    GeneratedQuestionSnapshot,
    QuestionChoiceSnapshot,
    QuestionEventSnapshot,
    QuizSessionSnapshot,
    QuizSessionSummary,
)
from jpnote_app.quiz.tui_controller import QuizTuiController
from jpnote_app.study_sources import SourceCatalog


def make_summary(*, pruned: bool = False) -> QuizSessionSummary:
    return QuizSessionSummary(
        session_id="quiz-session:history",
        mode="mixed",
        requested_count=2,
        question_count=2,
        state="completed",
        answered_count=2,
        correct_count=1,
        incorrect_count=1,
        skipped_count=0,
        details_pruned=pruned,
        created_at="2026-07-24T20:00:00+08:00",
        updated_at="2026-07-24T20:02:00+08:00",
        started_at="2026-07-24T20:00:00+08:00",
        ended_at="2026-07-24T20:02:00+08:00",
    )


def make_event(position: int, *, correct: bool) -> QuestionEventSnapshot:
    source_key = "vocab:台風" if position == 1 else "vocab:以上"
    prompt = "「たいふう」的中文意思是？" if position == 1 else "「以上」的讀音是「いじょ」。"
    choices = (
        QuestionChoiceSnapshot("a", "颱風"),
        QuestionChoiceSnapshot("b", "資料"),
    )
    question = GeneratedQuestionSnapshot(
        question_type="vocab_ja_to_zh_mcq",
        generator_version="quiz-v1-generator-1",
        source_kind="vocabulary",
        source_key=source_key,
        prompt=prompt,
        choices=choices,
        correct_answer=AnswerSnapshot("a", "颱風"),
    )
    return QuestionEventSnapshot(
        question_event_id=f"quiz-question:{position}",
        session_id="quiz-session:history",
        position=position,
        question=question,
        user_answer=AnswerSnapshot("a" if correct else "b", "颱風" if correct else "資料"),
        result="correct" if correct else "incorrect",
        answered_at="2026-07-24T20:01:00+08:00",
    )


EVENTS = (make_event(1, correct=True), make_event(2, correct=False))


class Reader:
    def list_entry_snapshots(self, **kwargs):
        return ()

    def get_entry_snapshot(self, key):
        return None

    def list_attempt_replay_sources(self, **kwargs):
        return ()

    def get_attempt_replay_source(self, event_key):
        return None

    def source_catalog(self):
        return SourceCatalog(0, 0, (), ())


class Store:
    def get_session(self, session_id):
        assert session_id == "quiz-session:history"
        return QuizSessionSnapshot(make_summary(), EVENTS)

    def list_recent_sessions(self, *, limit=20, states=None):
        return (make_summary(),)


class FakeTuiService:
    def __init__(self, *, pruned: bool = False) -> None:
        self.pruned = pruned

    def source_catalog(self):
        return SourceCatalog(0, 0, (), ())

    def list_resumable_sessions(self, *, limit=20):
        return ()

    def list_recent_sessions(self, *, limit=20):
        return (make_summary(pruned=self.pruned),)

    def session_result(self, session_id):
        summary = make_summary(pruned=self.pruned)
        return QuizSessionResult(
            summary=summary,
            question_types=(),
            incorrect_questions=() if self.pruned else (EVENTS[1],),
            details_available=not self.pruned,
            questions=() if self.pruned else EVENTS,
        )

    def question_source_details(self, session_id, question_event_id):
        return QuizSourceDetails(
            status="available",
            source_kind="vocabulary",
            source_key="vocab:台風",
            title="台風",
            reading="たいふう",
            level="N4",
            meanings=("颱風",),
            sources=("TRY! N4",),
        )

    def continue_session(self, session_id):
        raise AssertionError

    def start_session(self, **kwargs):
        raise AssertionError

    def decline_resume(self, session_id):
        raise AssertionError

    def mark_interrupted_if_active(self, session_id):
        return None


def test_service_result_exposes_all_immutable_question_events():
    result = QuizService(Reader(), Store()).session_result("quiz-session:history")
    assert result.questions == EVENTS
    assert result.incorrect_questions == (EVENTS[1],)


def test_history_summary_opens_per_question_list_and_details():
    ui = QuizTuiController(FakeTuiService(), seed_factory=lambda: "seed")
    ui.handle_key("H")
    ui.handle_key("ENTER")
    assert ui.state.screen == "history_detail"

    ui.handle_key("p")
    assert ui.state.screen == "history_questions"
    listed = ui.render(100, 30)
    assert any("たいふう" in line and "✓" in line for line in listed.lines)
    assert any("以上" in line and "×" in line for line in listed.lines)

    ui.handle_key("ENTER")
    assert ui.state.screen == "history_question_detail"
    detail = ui.render(100, 40)
    text = "\n".join(detail.lines)
    assert "結果：正確" in text
    assert "你的答案：颱風" in text
    assert "正確答案：颱風" in text
    assert "台風（たいふう）" in text
    assert "JLPT：N4" in text


def test_history_question_detail_moves_between_saved_questions():
    ui = QuizTuiController(FakeTuiService(), seed_factory=lambda: "seed")
    ui.handle_key("H")
    ui.handle_key("ENTER")
    ui.handle_key("p")
    ui.handle_key("ENTER")
    ui.handle_key("DOWN")
    assert ui.state.history_question_event == EVENTS[1]
    text = "\n".join(ui.render(100, 40).lines)
    assert "結果：錯誤" in text
    assert "你的答案：資料" in text


def test_pruned_history_keeps_summary_but_refuses_question_view():
    ui = QuizTuiController(FakeTuiService(pruned=True), seed_factory=lambda: "seed")
    ui.handle_key("H")
    ui.handle_key("ENTER")
    summary_screen = "\n".join(ui.render(100, 30).lines)
    assert "逐題紀錄已清理" in summary_screen
    ui.handle_key("p")
    assert ui.state.screen == "message"
    assert "逐題詳細資料已清理" in ui.state.message
