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


def change_line(equity, prev):
    """전 영업일 마감 대비 총 자산 변동 한 줄 (prev = (날짜, 총 평가금액))"""
    if not prev or not prev[1]:
        return None
    d, e = prev
    diff = equity - e
    pct = diff / e * 100
    if round(diff) == 0:
        return f"전 영업일({d[5:].replace('-', '/')}) 마감과 같은 수준입니다."
    word = "늘었습니다" if diff > 0 else "줄었습니다"
    return f"전 영업일({d[5:].replace('-', '/')}) 마감 대비 {abs(diff):,.0f}원({pct:+.2f}%) {word}."


def _day_lines(holdings):
    """보유 종목별 전일 대비 변동 (holdings: name, qty, price, prev)"""
    out = []
    for h in holdings or []:
        prev = h.get("prev")
        chg = f"전일 대비 {(h['price'] / prev - 1) * 100:+.2f}%" if prev else "전일 대비 확인 불가"
        out.append(f"• {h['name']} {h['qty']}주: {h['price']:,.0f}원 ({chg})")
    return out


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


def daily_message(equity, return_pct, cash, trades, failed, news=None, news_blocked=None, warnings=None, pending=None, prev=None, holdings=None):
    if return_pct > 0:
        mood = f"시작 금액 대비 {return_pct}% 높은 수준입니다."
    elif return_pct < 0:
        mood = f"시작 금액 대비 {abs(return_pct)}% 낮은 수준입니다."
    else:
        mood = "시작 금액과 동일한 수준입니다."
    lines = [
        f"{BOSS}, {_report_title()} 보고드립니다." + _report_note(),
        f"총 자산은 {equity:,.0f}원이며, {mood} (현금 {cash:,.0f}원)",
    ]
    cl = change_line(equity, prev)
    if cl:
        lines.append(cl)
    lines.append("")
    if holdings:
        lines.append("보유 종목의 전일 대비 변동입니다.")
        lines += _day_lines(holdings)
        lines.append("")

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

    if pending:
        buys = [p["name"] for p in pending if p["side"] == "BUY"]
        sells = [p["name"] for p in pending if p["side"] == "SELL"]
        lines.append("")
        lines.append("내일 장 시작(시가)에 체결할 주문을 예약해 두었습니다. 보유 자리와 업종 한도에 따라 일부는 체결되지 않을 수 있습니다.")
        if buys:
            lines.append("• 매수 예정: " + ", ".join(buys[:8]) + (f" 외 {len(buys) - 8}종목" if len(buys) > 8 else ""))
        if sells:
            lines.append("• 매도 예정: " + ", ".join(sells[:8]))

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


def midday_message(now_text, equity, return_pct, cash, holdings, failed, closed=False, prev=None):
    if closed:
        return (f"{BOSS}, 오늘은 휴장이거나 실시간 시세가 아직 반영되지 않아 중간 보고를 생략합니다.\n"
                "오후 4시에 다시 보고드리겠습니다.")
    lines = [
        f"{BOSS}, 점심 중간 보고드립니다. ({now_text} 기준)",
        f"총 자산은 {equity:,.0f}원이며, {_mood(return_pct)} (현금 {cash:,.0f}원)",
    ]
    cl = change_line(equity, prev)
    if cl:
        lines.append(cl)
    lines.append("")
    if holdings:
        lines.append("보유 종목 현황입니다.")
        for h in holdings:
            r = (h["price"] / h["avg"] - 1) * 100
            day = f", 전일 대비 {(h['price'] / h['prev'] - 1) * 100:+.2f}%" if h.get("prev") else ""
            lines.append(f"• {h['name']} {h['qty']}주: 현재가 {h['price']:,.0f}원 (매입가 대비 {r:+.2f}%{day})")
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


def open_message(now_text, equity, return_pct, cash, holdings, prev=None):
    lines = [
        f"{BOSS}, 장이 열렸습니다. ({now_text} 기준)",
        f"총 자산은 {equity:,.0f}원이며, {_mood(return_pct)} (현금 {cash:,.0f}원)",
    ]
    cl = change_line(equity, prev)
    if cl:
        lines.append(cl)
    lines.append("")
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


_TUNE_NAMES = {
    "STOP_LOSS_PCT": ("손절선", lambda v: f"{v * 100:.0f}%"),
    "TRAIL_STOP_PCT": ("추적 손절", lambda v: f"{v * 100:.0f}%"),
    "MAX_POSITIONS": ("동시 보유 종목 수", lambda v: f"{v:.0f}종목"),
    "GAP_DAYS": ("갭 건너뜀 기준", lambda v: f"{v:.0f}회"),
}


def advisor_message(entry, applied=False):
    lines = [f"{BOSS}, 설정 점검 결과를 보고드립니다."]
    if not entry["changes"]:
        lines.append("지금 설정을 그대로 유지하는 것이 좋다고 판단했습니다.")
    else:
        lines.append("다음과 같이 조정해 적용했습니다." if applied else "다음과 같이 조정하는 것을 제안드립니다.")
        for k, c in entry["changes"].items():
            name, fmt = _TUNE_NAMES[k]
            lines.append(f"• {name}: {fmt(c['from'])} → {fmt(c['to'])}")
    if entry.get("reason"):
        lines.append(f"이유: {entry['reason']}")
    if entry["changes"] and not applied:
        lines.append("적용하려면 PC에서 python advisor.py --apply 를 실행해 주세요. (거절은 --reject)")
    return "\n".join(lines)


def weekly_message(d):
    lines = [f"{BOSS}, 이번 주 보고드립니다. ({d['start']} ~ {d['end']})"]
    sign = "+" if d["change"] >= 0 else "-"
    lines.append(f"총 자산은 {d['equity']:,.0f}원으로, 지난주 대비 {sign}{abs(d['change']):,.0f}원 ({d['change_pct']:+.2f}%)입니다.")
    if d["index"]:
        lines.append("같은 기간 " + ", ".join(f"{k} {v:+.2f}%" for k, v in d["index"].items()) + "였습니다.")
    lines.append("")
    if d["buys"] or d["sells"]:
        lines.append(f"거래는 매수 {d['buys']}건, 매도 {d['sells']}건이었습니다.")
        if d["sells"]:
            pnl = f"{abs(d['pnl']):,.0f}원 {'수익' if d['pnl'] >= 0 else '손실'}"
            lines.append(f"매도한 거래 중 이익 {d['wins']}건, 손실 {d['sells'] - d['wins']}건이고, 합계는 {pnl}입니다.")
    else:
        lines.append("이번 주에는 거래가 없었습니다.")
    if d["holdings"]:
        lines.append("")
        lines.append("보유 종목 현황입니다.")
        for h in d["holdings"]:
            lines.append(f"• {h['name']} {h['qty']}주: 매입가 대비 {h['ret']:+.2f}%")
    for t in d["tuning"]:
        lines.append("")
        lines.append(f"설정 점검: {t}")
    return "\n".join(lines)
