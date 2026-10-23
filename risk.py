"""보유 종목 위험 알림: 손절선·추적손절선에 가까워지거나 전일 대비 급락하면 한 번 미리 알려드립니다.
같은 종목의 같은 경고는 하루에 한 번만 보냅니다. (장중 감시 monitor.py 가 사용)"""
import config

NEAR = 0.7          # 손절 기준의 70% 만큼 내려오면 '근접' (손절 -7% 이면 -4.9%)
DROP = -0.05        # 전일 종가 대비 -5% 이하이면 급락


def check(code, name, price, avg, peak, prev_close, seen):
    """새로 알려야 할 경고 목록을 돌려주고, seen(집합)에 기록합니다."""
    out = []

    def add(kind, text):
        if (code, kind) not in seen:
            seen.add((code, kind))
            out.append({"code": code, "name": name, "kind": kind, "text": text})

    ret = price / avg - 1
    if config.STOP_LOSS_PCT and ret <= config.STOP_LOSS_PCT * NEAR and ret > config.STOP_LOSS_PCT:
        add("stop", f"매입가 대비 {ret * 100:+.1f}%로, 손절 기준({config.STOP_LOSS_PCT * 100:.0f}%)까지 {abs(ret - config.STOP_LOSS_PCT) * 100:.1f}%p 남았습니다.")
    if config.TRAIL_STOP_PCT and peak and price > avg:
        dd = price / peak - 1
        if dd <= -config.TRAIL_STOP_PCT * NEAR and dd > -config.TRAIL_STOP_PCT:
            add("trail", f"최고가 대비 {dd * 100:.1f}%로, 추적 손절 기준(-{config.TRAIL_STOP_PCT * 100:.0f}%)에 가까워졌습니다.")
    if prev_close:
        d = price / prev_close - 1
        if d <= DROP:
            add("drop", f"전일 종가 대비 {d * 100:.1f}% 급락했습니다.")
    return out
