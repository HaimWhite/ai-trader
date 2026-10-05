"""시세 조회. 미국 종목(티커)은 달러 시세를 원화로 환산해서 돌려줍니다."""
import FinanceDataReader as fdr

import config

_fx_cache = {}


def load_fx(start):
    if start not in _fx_cache:
        _fx_cache[start] = fdr.DataReader("USD/KRW", start)["Close"].dropna()
    return _fx_cache[start]


def load_prices(code, start):
    """일봉 데이터(Open, Close 등)를 원화 기준으로 돌려줍니다."""
    df = fdr.DataReader(code, start).dropna(subset=["Close"])
    if config.is_us(code):
        fx = load_fx(start).reindex(df.index, method="ffill").bfill()
        df = df.copy()
        for col in ("Open", "High", "Low", "Close"):
            if col in df.columns:
                df[col] = df[col] * fx
    return df
