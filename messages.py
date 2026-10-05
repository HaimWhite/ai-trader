"""디스코드 알림 문구 (AI 비서 보고 말투). 말투를 바꾸고 싶으면 이 파일만 고치면 됩니다."""
import config

BOSS = "하임님"   # 비서가 부르는 호칭 (원하는 호칭으로 바꾸세요)


def _report_title(now=None):
    """보고하는 시각에 맞는 제목: 장 마감 후에만 '장 마감 보고'라고 합니다."""
    from datetime import datetime, time as dtime
    now = now or datetime.now()
    if now.weekday() >= 5:
        return "휴장일 점검"
    if now.time() < dtime(9, 0):
        return "개장 전 점검"
    if now.time() < dtime(15, 30):
        return "장중 점검"
    return "오늘 장 마감"


def _report_note(now=None):
    title = _report_title(now)
    if title == "장중 점검":
        return "\n아직 장이 끝나지 않아 현재가 기준입니다."
    if title in ("개장 전 점검", "휴장일 점검"):
        return "\n새 시세가 없어 마지막 종가 기준입니다."
    return ""


def plain_reason(reason):
    if reason == "손절":
        return f"매입가 대비 {abs(config.STOP_LOSS_PCT) * 100:.0f}% 이상 하락해 손절 기준에 도달했습니다."
    if reason == "추적손절":
        return f"최고가 대비 {(config.TRAIL_STOP_PCT or 0) * 100:.0f}% 이상 하락해 추적 손절 기준에 도달했습니다."
    if "상승 추세" in reason:
        return "단기 평균이 장기 평균 위로 올라와 상승 흐름으로 판단했습니다."
    if "하락 추세" in reason:
        return "단기 평균이 장기 평균 아래로 내려와 하락 흐름으로 판단했습니다."
    return reason


LABEL = {2: "큰 호재", 1: "호재", 0: "중립", -1: "악재", -2: "큰 악재"}


def _news_lines(news, blocked, warnings):
    if not news:
        return []
    lines = [""]
    if all(not n["ok"] for n in news):
        lines.append("뉴스 분석에 실패해 이번에는 뉴스를 반영하지 못했습니다.")
        return lines
    notable = [n for n in news if n["ok"] and n["score"] != 0]
    if notable:
        lines.append("뉴스도 함께 확인했습니다.")
        for n in notable:
            lines.append(f"• {n['name']}: {LABEL[n['score']]} - {n['summary']}")
    else:
        lines.append("뉴스는 특이사항이 없었습니다.")
    for name in blocked:
        lines.append(f"{name}는 매수 신호가 있었지만 악재 뉴스가 있어 매수를 보류했습니다.")
    for w in warnings:
        lines.append(w)
    return lines


def daily_message(equity, return_pct, cash, trades, failed, news=None, news_blocked=None, warnings=None):
    if return_pct > 0:
        mood = f"시작 금액 대비 {return_pct}% 높은 수준입니다."
    elif return_pct < 0:
        mood = f"시작 금액 대비 {abs(return_pct)}% 낮은 수준입니다."
    else:
        mood = "시작 금액과 동일한 수준입니다."
    lines = [
        f"{BOSS}, {_report_title()} 보고드립니다." + _report_note(),
        f"총 자산은 {equity:,.0f}원이며, {mood} (현금 {cash:,.0f}원)",
        "",
    ]

    if trades:
        lines.append(f"오늘 매매는 {len(trades)}건 진행했습니다.")
        for t in trades:
            if t["side"] == "BUY":
                lines.append(f"• {t['name']} {t['qty']}주를 {t['price']:,}원에 매수했습니다. {plain_reason(t['reason'])}")
            else:
                result = f"{abs(t['pnl']):,.0f}원 {'수익' if t['pnl'] >= 0 else '손실'}"
                lines.append(f"• {t['name']} {t['qty']}주를 {t['price']:,}원에 매도했습니다. {plain_reason(t['reason'])} 이번 거래는 {result}입니다.")
    else:
        lines.append("오늘은 매매 없이 시장을 계속 지켜봤습니다. 특이사항은 없습니다.")

    lines += _news_lines(news, news_blocked or [], warnings or [])

    if failed:
        lines.append("")
        lines.append(f"한 가지 더 보고드립니다. {', '.join(failed)} 시세를 가져오지 못했습니다. 확인이 필요합니다.")
    return "\n".join(lines)


def error_message(tb):
    return (f"{BOSS}, 보고드릴 문제가 있습니다.\n"
            "프로그램 실행 중 오류가 발생해 오늘 매매가 정상 처리되지 않았을 수 있습니다. 확인 부탁드립니다.\n"
            "```\n" + tb[-1200:] + "\n```")


def _mood(return_pct):
    if return_pct > 0:
        return f"시작 금액 대비 {return_pct}% 높은 수준입니다."
    if return_pct < 0:
        return f"시작 금액 대비 {abs(return_pct)}% 낮은 수준입니다."
    return "시작 금액과 동일한 수준입니다."


def midday_message(now_text, equity, return_pct, cash, holdings, failed, closed=False):
    if closed:
        return (f"{BOSS}, 오늘은 휴장이거나 실시간 시세가 아직 반영되지 않아 중간 보고를 생략합니다.\n"
                "오후 4시에 다시 보고드리겠습니다.")
    lines = [
        f"{BOSS}, 점심 중간 보고드립니다. ({now_text} 기준)",
        f"총 자산은 {equity:,.0f}원이며, {_mood(return_pct)} (현금 {cash:,.0f}원)",
        "",
    ]
    if holdings:
        lines.append("보유 종목 현황입니다.")
        for h in holdings:
            r = (h["price"] / h["avg"] - 1) * 100
            lines.append(f"• {h['name']} {h['qty']}주: 현재가 {h['price']:,.0f}원 (매입가 대비 {r:+.2f}%)")
    else:
        lines.append("현재 보유 중인 종목은 없습니다.")
    if failed:
        lines.append("")
        lines.append(f"{', '.join(failed)} 시세를 가져오지 못해 매입가 기준으로 계산했습니다.")
    lines.append("")
    lines.append("매매는 오후 4시 마감 후 최종 판단하여 보고드리겠습니다.")
    return "\n".join(lines)


def _trade_line(t):
    if t["side"] == "BUY":
        return f"• {t['name']} {t['qty']}주를 {t['price']:,}원에 매수했습니다. {plain_reason(t['reason'])}"
    result = f"{abs(t['pnl']):,.0f}원 {'수익' if t['pnl'] >= 0 else '손실'}"
    return f"• {t['name']} {t['qty']}주를 {t['price']:,}원에 매도했습니다. {plain_reason(t['reason'])} 이번 거래는 {result}입니다."


def trade_alert(trades):
    return "\n".join([f"{BOSS}, 장중 매매가 발생해 바로 보고드립니다."] + [_trade_line(t) for t in trades])


def open_message(now_text, equity, return_pct, cash, holdings):
    lines = [
        f"{BOSS}, 장이 열렸습니다. ({now_text} 기준)",
        f"총 자산은 {equity:,.0f}원이며, {_mood(return_pct)} (현금 {cash:,.0f}원)",
        "",
    ]
    if holdings:
        lines.append("보유 종목 현황입니다.")
        for h in holdings:
            chg = (h["price"] / h["prev"] - 1) * 100
            lines.append(f"• {h['name']} {h['qty']}주: 현재가 {h['price']:,.0f}원 (전일 대비 {chg:+.2f}%)")
    else:
        lines.append("현재 보유 중인 종목은 없습니다.")
    lines += ["", "장중에는 5분마다 시세를 확인하겠습니다. 손절 기준에 닿거나 매매가 일어나면 바로 보고드리고, 그 외에는 조용히 지켜보겠습니다."]
    return "\n".join(lines)


def no_data_message():
    return f"{BOSS}, 오늘은 휴장이거나 시세가 아직 반영되지 않아 장중 감시를 쉬겠습니다. 오후 4시 정기 점검은 그대로 진행합니다."
