"""시세 조회. 미국 종목(티커)은 달러 시세를 원화로 환산해서 돌려줍니다.
FinanceDataReader 가 실패하면 잠깐 뒤 다시 시도하고, 그래도 안 되면 yfinance 로 대체합니다."""
import time

import FinanceDataReader as fdr

import config

_fx_cache = {}


def _yf_symbol(code):
    if config.is_us(code):
        return code
    return code + (".KQ" if code in config.KOSDAQ_CODES else ".KS")


def _yf_history(symbol, start):
    import yfinance as yf
    df = yf.Ticker(symbol).history(start=start, auto_adjust=False)
    if df is None or len(df) == 0:
        raise ValueError("yfinance 가 빈 데이터를 돌려줌")
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = df.index.tz_localize(None).normalize() if df.index.tz is not None else df.index.normalize()
    return df


def _fetch(fdr_symbol, yf_symbol, start):
    last = None
    for attempt in range(2):
        try:
            df = fdr.DataReader(fdr_symbol, start)
            if df is not None and len(df):
                return df
            last = ValueError("빈 데이터")
        except Exception as e:
            last = e
        time.sleep(1)
    print(f"[시세] {fdr_symbol} 기본 출처 실패({str(last)[:60]}) -> yfinance 로 대체 시도")
    try:
        return _yf_history(yf_symbol, start)
    except Exception as e2:
        raise RuntimeError(f"시세 조회 실패: {str(last)[:60]} / 대체 출처도 실패: {str(e2)[:60]}")


def load_fx(start):
    if start not in _fx_cache:
        _fx_cache[start] = _fetch("USD/KRW", "KRW=X", start)["Close"].dropna()
    return _fx_cache[start]


def load_prices(code, start):
    """일봉 데이터(Open, Close 등)를 원화 기준으로 돌려줍니다."""
    df = _fetch(code, _yf_symbol(code), start).dropna(subset=["Close"])
    if config.is_us(code):
        fx = load_fx(start).reindex(df.index, method="ffill").bfill()
        df = df.copy()
        for col in ("Open", "High", "Low", "Close"):
            if col in df.columns:
                df[col] = df[col] * fx
    return df
