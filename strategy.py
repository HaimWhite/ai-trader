import math

import pandas as pd
import config


def long_list():
    """매매 판단에 쓰는 장기선 목록 (기본: LONG_MA 하나)"""
    return tuple(config.LONG_MAS) if config.LONG_MAS else (config.LONG_MA,)


def need_bull(n):
    """장기선 n개 중 단기선이 몇 개 위에 있어야 '상승'인지"""
    if config.LONG_RULE == "any":
        return 1
    if config.LONG_RULE == "majority":
        return n // 2 + 1
    return n


def analyze(df):
    """이동평균을 계산해서 'BUY'(상승 추세) 또는 'SELL'(하락 추세) 상태를 돌려줍니다."""
    close = df["Close"]
    s = config.SHORT_MA
    longs = long_list()
    short_ma = close.rolling(s).mean().iloc[-1]
    lmas = {n: close.rolling(n).mean().iloc[-1] for n in sorted(set(longs) | set(config.SHOW_MAS) | {config.LONG_MA})}
    mas = {str(s): round(float(short_ma), 1) if not pd.isna(short_ma) else None}
    for n, v in lmas.items():
        mas[str(n)] = None if pd.isna(v) else round(float(v), 1)

    if any(pd.isna(lmas[n]) for n in longs) or pd.isna(short_ma):
        return {"signal": "HOLD", "reason": "데이터 부족", "short_ma": None, "long_ma": None, "mas": mas, "rank": 0}

    ups = [n for n in longs if short_ma > lmas[n]]
    bull = len(ups) >= need_bull(len(longs))
    long_ma = lmas[config.LONG_MA] if config.LONG_MA in lmas else lmas[longs[-1]]
    rank = float(sum(short_ma / lmas[n] for n in longs) / len(longs))
    if len(longs) == 1:
        n = longs[0]
        reason = (f"{s}일선({short_ma:,.0f}) > {n}일선({lmas[n]:,.0f}) 상승 추세" if bull
                  else f"{s}일선({short_ma:,.0f}) <= {n}일선({lmas[n]:,.0f}) 하락 추세")
    else:
        names = "·".join(str(n) for n in longs)
        rule = {"all": "모두", "majority": "과반", "any": "하나라도"}[config.LONG_RULE]
        reason = (f"{s}일선이 {names}일선 중 {len(ups)}/{len(longs)}개 위({rule} 기준) " + ("상승 추세" if bull else "하락 추세"))
    return {
        "signal": "BUY" if bull else "SELL",
        "reason": reason,
        "short_ma": round(float(short_ma), 1),
        "long_ma": round(float(long_ma), 1),
        "mas": mas,
        "rank": rank,
    }


def trend_sell_price(df):
    """내일 종가가 이 가격 이하로 마감하면 '하락 추세'로 바뀌어 매도 신호가 나는 가격 (이동평균 공식으로 역산).
    장기선이 여러 개면 설정한 규칙(모두/과반/하나라도)에 맞춰 계산합니다. 계산할 수 없으면 None."""
    close = df["Close"].dropna()
    s = config.SHORT_MA
    longs = long_list()
    if len(close) < max(longs):
        return None
    s_sum = float(close.iloc[-(s - 1):].sum())
    xs = []
    for n in longs:
        l_sum = float(close.iloc[-(n - 1):].sum())
        if n == s:
            continue
        # 단기선 <= 장기선 이 되는 조건: (n - s) * x <= s * l_sum - n * s_sum
        xs.append((s * l_sum - n * s_sum) / (n - s))
    if not xs:
        return None
    # 매도: 상승 조건을 못 채우는 장기선이 (n - 필요개수 + 1)개 이상일 때
    fail_needed = len(xs) - need_bull(len(xs)) + 1
    x = sorted(xs, reverse=True)[max(fail_needed, 1) - 1]
    return x if x > 0 and not math.isnan(x) else None
