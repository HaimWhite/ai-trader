import pandas as pd
import config


def analyze(df):
    """이동평균을 계산해서 'BUY'(상승 추세) 또는 'SELL'(하락 추세) 상태를 돌려줍니다."""
    close = df["Close"]
    short_ma = close.rolling(config.SHORT_MA).mean().iloc[-1]
    long_ma = close.rolling(config.LONG_MA).mean().iloc[-1]

    if pd.isna(long_ma):
        return {"signal": "HOLD", "reason": "데이터 부족", "short_ma": None, "long_ma": None}

    if short_ma > long_ma:
        signal = "BUY"
        reason = f"{config.SHORT_MA}일선({short_ma:,.0f}) > {config.LONG_MA}일선({long_ma:,.0f}) 상승 추세"
    else:
        signal = "SELL"
        reason = f"{config.SHORT_MA}일선({short_ma:,.0f}) <= {config.LONG_MA}일선({long_ma:,.0f}) 하락 추세"

    return {
        "signal": signal,
        "reason": reason,
        "short_ma": round(float(short_ma), 1),
        "long_ma": round(float(long_ma), 1),
    }
