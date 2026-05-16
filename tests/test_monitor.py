import unittest

from monitor import (
    ServiceSnapshot,
    ServiceTarget,
    build_notifications,
    is_blocked_response,
    parse_detail_page,
    parse_search_cards,
)


AVAILABLE_DETAIL_HTML = """
<div class="dt_top_box">
  <h4 class="dt_tit1">
    <span class="tit">5월 바비큐존(4인용, 2차:17시~22시) 26년 한강공원 난지캠핑장</span>
  </h4>
  <span class="bd_label status1">접수중</span>
  <ul>
    <li><b class="tit1">이용기간</b>2026.05.01 ~ 2026.05.31</li>
    <li><b class="tit1">접수기간</b>2026.04.15 15:00 ~ 2026.05.31 17:00<br></li>
  </ul>
  <div class="common_btn_box">
    <a href="javascript:fnRevervInsertForm();" class="common_btn blue">예약하기</a>
    <button type="button" class="common_btn white board_pop">공지사항</button>
  </div>
</div><!-- //dt_top_box -->
"""


SOLD_OUT_DETAIL_HTML = """
<div class="dt_top_box">
  <h4 class="dt_tit1">
    <span class="tit">6월 바비큐존(8인용, 2차:17시~22시) 26년 한강공원 난지캠핑장</span>
  </h4>
  <span class="bd_label status5">예약마감</span>
  <ul>
    <li><b class="tit1">이용기간</b>2026.06.01 ~ 2026.06.30</li>
    <li><b class="tit1">접수기간</b>2026.05.15 15:00 ~ 2026.06.30 17:00<br></li>
  </ul>
  <div class="common_btn_box">
    <a href="javascript:void(0);" class="common_btn white">예약마감</a>
    <button type="button" class="common_btn white board_pop">공지사항</button>
  </div>
</div><!-- //dt_top_box -->
"""


SEARCH_HTML = """
<ul class="img_board">
  <li>
    <a href="#" onclick="fnDetailPage('S260428170022623775', '', ''); return false;" title="6월 바비큐존(8인용, 2차:17시~22시) 26년 한강공원 난지캠핑장">
      <span class="bd_label status5">예약마감</span>
      <h4 class="tit1 sch-rslt">6월 바비큐존(8인용, 2차:17시~22시) 26년 한강공원 난지캠핑장</h4>
    </a>
  </li>
  <li>
    <a href="#" onclick="fnDetailPage('S260428142800885312', '', ''); return false;" title="6월 바비큐존(4인용, 1차:11시~16시) 26년 한강공원 난지캠핑장">
      <span class="bd_label status1">접수중</span>
      <h4 class="tit1 sch-rslt">6월 바비큐존(4인용, 1차:11시~16시) 26년 한강공원 난지캠핑장</h4>
    </a>
  </li>
</ul>
"""


class MonitorParsingTests(unittest.TestCase):
    def test_block_detection_ignores_normal_dynapath_configuration_text(self):
        normal_page = """
        <script>
          var dpCnf = {
            d: function() {
              return "/management/ipRedirect.do?threatTt=비정상 접근으로 인한 차단 알림";
            }
          };
        </script>
        <div class="dt_top_box"><span class="tit">정상 상세 페이지</span></div>
        """
        blocked_page = """
        <!--dynapath:error-->
        <h5>비정상 접근으로 인한 차단 알림</h5>
        <pre>정상 접근을 위해서는 인터넷 쿠키를 삭제하고 브라우저 전체를 완전 종료 후 다시 접속하시기 바랍니다.</pre>
        """

        self.assertFalse(is_blocked_response(normal_page))
        self.assertTrue(is_blocked_response(blocked_page))

    def test_parse_detail_page_marks_reservation_button_as_available(self):
        target = ServiceTarget("S260331084257893495", "configured label")

        snapshot = parse_detail_page(AVAILABLE_DETAIL_HTML, target)

        self.assertEqual(snapshot.title, "5월 바비큐존(4인용, 2차:17시~22시) 26년 한강공원 난지캠핑장")
        self.assertEqual(snapshot.status, "접수중")
        self.assertEqual(snapshot.action, "예약하기")
        self.assertTrue(snapshot.available)

    def test_parse_detail_page_marks_sold_out_button_as_unavailable(self):
        target = ServiceTarget("S260428170022623775", "configured label")

        snapshot = parse_detail_page(SOLD_OUT_DETAIL_HTML, target)

        self.assertEqual(snapshot.status, "예약마감")
        self.assertEqual(snapshot.action, "예약마감")
        self.assertFalse(snapshot.available)

    def test_parse_search_cards_filters_to_second_shift_barbecue_targets(self):
        cards = parse_search_cards(SEARCH_HTML)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].target_id, "S260428170022623775")
        self.assertIn("2차:17시~22시", cards[0].title)


class NotificationTests(unittest.TestCase):
    def test_build_notifications_alerts_on_first_available_target(self):
        snapshot = ServiceSnapshot(
            target_id="S260331084257893495",
            title="5월 바비큐존(4인용, 2차:17시~22시)",
            status="접수중",
            action="예약하기",
            available=True,
            url="https://example.test/detail",
        )

        notifications, next_state = build_notifications(
            [snapshot],
            {"version": 1, "targets": {}},
            now="2026-05-16T12:00:00+09:00",
            alert_on_first_available=True,
        )

        self.assertEqual(len(notifications), 1)
        self.assertIn("예약 가능", notifications[0])
        self.assertTrue(next_state["targets"][snapshot.target_id]["notified_available"])

    def test_build_notifications_does_not_repeat_already_notified_available_target(self):
        snapshot = ServiceSnapshot(
            target_id="S260331084257893495",
            title="5월 바비큐존(4인용, 2차:17시~22시)",
            status="접수중",
            action="예약하기",
            available=True,
            url="https://example.test/detail",
        )
        previous_state = {
            "version": 1,
            "targets": {
                snapshot.target_id: {
                    "available": True,
                    "notified_available": True,
                    "action": "예약하기",
                    "status": "접수중",
                    "title": snapshot.title,
                    "url": snapshot.url,
                    "last_changed_at": "2026-05-16T12:00:00+09:00",
                }
            },
        }

        notifications, next_state = build_notifications(
            [snapshot],
            previous_state,
            now="2026-05-16T12:10:00+09:00",
            alert_on_first_available=True,
        )

        self.assertEqual(notifications, [])
        self.assertTrue(next_state["targets"][snapshot.target_id]["notified_available"])
        self.assertEqual(next_state, previous_state)


if __name__ == "__main__":
    unittest.main()
