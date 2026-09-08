"""한국어 일정 파서 단위 테스트.

기준 시각은 2026-09-02(수) 13:30으로 고정한다.  "내일"·"금요일"이 무엇인지가
오늘 날짜에 따라 흔들리면 테스트가 아니라 점괘가 된다.
"""

from datetime import datetime
import unittest

from alert_notes.ko_schedule_parser import parse


NOW = datetime(2026, 9, 2, 13, 30)


def read(text, base=None, base_end=None):
    return parse(text, now=NOW, base=base, base_end=base_end)


class ParseDateTest(unittest.TestCase):
    def assert_range(self, text, start, end, title=None):
        parsed = read(text)
        self.assertEqual(parsed.start, start, text)
        self.assertEqual(parsed.end, end, text)
        if title is not None:
            self.assertEqual(parsed.title, title, text)

    def test_day_words(self):
        self.assert_range("오늘 16시 코드리뷰", datetime(2026, 9, 2, 16), datetime(2026, 9, 2, 17), "코드리뷰")
        self.assert_range("내일 오후 3시 팀 회의", datetime(2026, 9, 3, 15), datetime(2026, 9, 3, 16), "팀 회의")
        self.assert_range("모레 9시 검진", datetime(2026, 9, 4, 9), datetime(2026, 9, 4, 10), "검진")
        self.assert_range("글피 10시 면담", datetime(2026, 9, 5, 10), datetime(2026, 9, 5, 11), "면담")

    def test_relative_days_and_weeks(self):
        self.assert_range("3일 뒤 15시30분 계약서 검토", datetime(2026, 9, 5, 15, 30), datetime(2026, 9, 5, 16, 30), "계약서 검토")
        self.assert_range("2주 후 10시 점검", datetime(2026, 9, 16, 10), datetime(2026, 9, 16, 11), "점검")

    def test_weekday_rolls_forward_when_already_past(self):
        # 수요일에 "화요일"이라고 하면 지난 화요일이 아니라 다음 화요일이다.
        self.assert_range("화요일 10시 치과", datetime(2026, 9, 8, 10), datetime(2026, 9, 8, 11), "치과")
        self.assert_range("금요일 저녁 7시 저녁약속", datetime(2026, 9, 4, 19), datetime(2026, 9, 4, 20), "저녁약속")

    def test_explicit_week_prefix(self):
        self.assert_range("다음주 화요일 10시 치과", datetime(2026, 9, 8, 10), datetime(2026, 9, 8, 11), "치과")
        self.assert_range("담주 목요일 점심 12시 팀 점심", datetime(2026, 9, 10, 12), datetime(2026, 9, 10, 13), "팀 점심")
        self.assert_range("이번주 금요일 11시 정산", datetime(2026, 9, 4, 11), datetime(2026, 9, 4, 12), "정산")

    def test_absolute_dates(self):
        self.assert_range("9월 10일 14시 월간보고", datetime(2026, 9, 10, 14), datetime(2026, 9, 10, 15), "월간보고")
        self.assert_range("2026-09-25 9시 반 건강검진", datetime(2026, 9, 25, 9, 30), datetime(2026, 9, 25, 10, 30), "건강검진")
        self.assert_range("10/15 14시 출장", datetime(2026, 10, 15, 14), datetime(2026, 10, 15, 15), "출장")

    def test_past_month_day_rolls_to_next_year(self):
        parsed = read("1월 5일 10시 신년회")
        self.assertEqual(parsed.start, datetime(2027, 1, 5, 10))

    def test_invalid_date_is_not_a_date(self):
        parsed = read("2월 30일 회의")
        self.assertIsNone(parsed.start)
        self.assertEqual(parsed.title, "2월 30일 회의")


class ParseTimeTest(unittest.TestCase):
    def test_bare_hour_uses_business_convention(self):
        # 표시 없는 1~6시는 오후, 7~12시는 적은 그대로.
        self.assertEqual(read("오늘 3시 회의").start, datetime(2026, 9, 2, 15))
        self.assertEqual(read("오늘 9시 회의").start, datetime(2026, 9, 2, 9))
        self.assertEqual(read("오늘 14시 회의").start, datetime(2026, 9, 2, 14))

    def test_meridiem_words(self):
        self.assertEqual(read("오늘 오전 11시 회의").start, datetime(2026, 9, 2, 11))
        self.assertEqual(read("오늘 아침 9시 회의").start, datetime(2026, 9, 2, 9))
        self.assertEqual(read("오늘 점심 12시 회의").start, datetime(2026, 9, 2, 12))
        self.assertEqual(read("오늘 저녁 7시 회의").start, datetime(2026, 9, 2, 19))
        self.assertEqual(read("오늘 밤 9시 회의").start, datetime(2026, 9, 2, 21))
        self.assertEqual(read("오늘 오전 12시 회의").start, datetime(2026, 9, 2, 0))

    def test_minutes_and_half(self):
        self.assertEqual(read("오늘 9시 반 회의").start, datetime(2026, 9, 2, 9, 30))
        self.assertEqual(read("오늘 15시30분 회의").start, datetime(2026, 9, 2, 15, 30))
        self.assertEqual(read("오늘 14:05 회의").start, datetime(2026, 9, 2, 14, 5))

    def test_range_and_duration(self):
        parsed = read("9월 10일 14시~16시 월간보고")
        self.assertEqual(parsed.start, datetime(2026, 9, 10, 14))
        self.assertEqual(parsed.end, datetime(2026, 9, 10, 16))
        self.assertEqual(parsed.title, "월간보고")
        parsed = read("오늘 14시부터 16시까지 워크숍")
        self.assertEqual(parsed.end, datetime(2026, 9, 2, 16))
        self.assertEqual(parsed.title, "워크숍")
        parsed = read("오늘 16시 1시간 코드리뷰")
        self.assertEqual(parsed.end, datetime(2026, 9, 2, 17))
        self.assertEqual(parsed.title, "코드리뷰")
        parsed = read("오늘 16시 30분간 스탠드업")
        self.assertEqual(parsed.end, datetime(2026, 9, 2, 16, 30))

    def test_all_day(self):
        parsed = read("모레 종일 워크숍")
        self.assertTrue(parsed.all_day)
        self.assertEqual(parsed.start, datetime(2026, 9, 4, 0, 0))
        self.assertEqual(parsed.end, datetime(2026, 9, 4, 23, 59))
        self.assertEqual(parsed.title, "워크숍")

    def test_time_only_keeps_the_dragged_day_and_length(self):
        base = datetime(2026, 9, 20, 14, 0)
        parsed = read("내일 회의", base=base, base_end=datetime(2026, 9, 20, 15, 30))
        # 시각을 말하지 않았으면 끌어 둔 시각과 길이를 지킨다.
        self.assertEqual(parsed.start, datetime(2026, 9, 3, 14, 0))
        self.assertEqual(parsed.end, datetime(2026, 9, 3, 15, 30))


class ParseMarkerTest(unittest.TestCase):
    def test_category_marker(self):
        parsed = read("내일 10시 치과 #개인")
        self.assertEqual(parsed.category, "mint")
        self.assertEqual(parsed.title, "치과")

    def test_unknown_tag_stays_in_the_title(self):
        parsed = read("내일 10시 배포 #릴리스")
        self.assertIsNone(parsed.category)
        self.assertEqual(parsed.title, "배포 #릴리스")

    def test_reminder_marker(self):
        parsed = read("9월 10일 14시 월간보고 #업무 !30분전")
        self.assertEqual(parsed.category, "sky")
        self.assertEqual(parsed.reminders, (30,))
        self.assertEqual(parsed.title, "월간보고")
        self.assertEqual(read("내일 9시 발표 !1시간전").reminders, (60,))
        self.assertEqual(read("내일 9시 발표 !10 !30").reminders, (10, 30))

    def test_recurrence(self):
        parsed = read("매주 월요일 9시 주간회의 #업무")
        self.assertEqual(parsed.recurrence["frequency"], "weekly")
        self.assertEqual(parsed.recurrence["weekdays"], [0])
        # 첫 회차도 말한 요일에 놓인다.
        self.assertEqual(parsed.start, datetime(2026, 9, 7, 9))
        self.assertEqual(parsed.title, "주간회의")
        self.assertEqual(read("매일 8시 스트레칭").recurrence["frequency"], "daily")
        self.assertEqual(read("매달 1일 10시 정산").recurrence["frequency"], "monthly")


class SafeSideTest(unittest.TestCase):
    """오인식보다 미인식을 택한 자리들."""

    def test_bare_month_is_not_a_date(self):
        parsed = read("9월 매출 정리")
        self.assertIsNone(parsed.start)
        self.assertTrue(parsed.is_empty)
        self.assertEqual(parsed.title, "9월 매출 정리")

    def test_numbers_after_the_first_words_are_left_alone(self):
        parsed = read("보고서 3시 버전 정리")
        self.assertIsNone(parsed.start)
        self.assertEqual(parsed.title, "보고서 3시 버전 정리")

    def test_plain_title_is_untouched(self):
        parsed = read("사무실 정리")
        self.assertTrue(parsed.is_empty)
        self.assertEqual(parsed.title, "사무실 정리")
        self.assertIsNone(parsed.category)
        self.assertEqual(parsed.reminders, ())

    def test_quantity_words_are_not_durations(self):
        parsed = read("3분기 계획 정리")
        self.assertIsNone(parsed.start)
        self.assertEqual(parsed.title, "3분기 계획 정리")


class SpanTest(unittest.TestCase):
    def test_spans_point_at_the_original_text(self):
        text = "다음주 화요일 10시 치과 #개인"
        parsed = read(text)
        for span in parsed.spans:
            self.assertEqual(text[span.start:span.end], span.text)
        kinds = [span.kind for span in parsed.spans]
        self.assertEqual(kinds, ["date", "time", "category"])

    def test_spans_do_not_overlap(self):
        parsed = read("9월 10일 14시~16시 월간보고 #업무 !30분전")
        edges = [(span.start, span.end) for span in parsed.spans]
        for (_, first_end), (second_start, _) in zip(edges, edges[1:]):
            self.assertLessEqual(first_end, second_start)


if __name__ == "__main__":
    unittest.main()
