"""금·달러·채권 ETF를 지금 30종목에 더하면 수익률과 낙폭이 좋아지는지 확인합니다.   실행: python compare_assets.py
- 후보는 '결과를 보기 전에' 정한 기준으로 골랐어요: 자산군마다 한국·미국에서 거래가 가장 활발한 대표 ETF (지금 잘 오른 것을 고른 게 아님)
    금: GLD(미국), KODEX 골드선물(H)   달러: UUP(미국), KODEX 미국달러선물   채권: TLT(미국 장기채), KODEX 국고채3년
- 지금 실제 매매 설정(손절·추적 손절·갭 필터·5종목 제한·비용) 그대로 비교. 한국 ETF는 매도 거래세가 없으므로 0으로 계산해요.
- 미국 ETF는 원화로 환산한 가격이라 환율 변동도 포함돼요.
- 옵션:  --start=2016-01-01  더 긴 기간   --split=2022-01-01  이 날짜 전/후를 따로 보기"""
import sys

import numpy as np
import pandas as pd

import config
import market
from backtest import live_options, metrics, prepare, simulate

ASSETS = {   # 코드: (이름, 자산군)
    "GLD": ("GLD(금, 미국)", "금"), "132030": ("KODEX 골드선물(H)", "금"),
    "UUP": ("UUP(달러, 미국)", "달러"), "261240": ("KODEX 미국달러선물", "달러"),
    "TLT": ("TLT(미국 장기채)", "채권"), "114260": ("KODEX 국고채3년", "채권"),
}
SHORT, LONG, STOP = config.SHORT_MA, config.LONG_MA, config.STOP_LOSS_PCT


def pad(text, width):
    return text + " " * max(0, width - len(text) - sum(1 for ch in text if ord(ch) > 127))


def main():
    split = "2022-01-01"
    for a in sys.argv[1:]:
        if a.startswith("--start="):
            config.BACKTEST_START = a.split("=", 1)[1]
        elif a.startswith("--split="):
            split = a.split("=", 1)[1]
    orig_tax = config.sell_tax_rate
    config.sell_tax_rate = lambda c: 0.0 if c in ASSETS else orig_tax(c)   # ETF 는 매도 거래세 없음
    for c, (_, kind) in ASSETS.items():
        config.SECTORS[c] = kind

    frames = {}
    for code, name in config.SYMBOLS.items():
        frames[code] = market.load_prices(code, config.BACKTEST_START)
    got = []
    for code, (name, kind) in ASSETS.items():
        try:
            frames[code] = market.load_prices(code, config.BACKTEST_START)
            got.append(code)
            print(f"[{name}] {len(frames[code])}일치 데이터 ({frames[code].index[0].date()}~)")
        except Exception as e:
            print(f"[{name}] 시세를 받지 못해 제외합니다: {str(e)[:80]}")
    if not got:
        print("ETF 시세를 하나도 받지 못했어요.")
        return
    idx, data = prepare(frames, [SHORT, LONG])
    n = len(idx)
    stocks = [c for c in config.SYMBOLS]
    kinds = {k: [c for c in got if ASSETS[c][1] == k] for k in ("금", "달러", "채권")}
    START = LONG + 1
    r0 = int(idx.searchsorted(pd.Timestamp(split)))
    opts = live_options()

    def run(codes):
        return simulate(n, {c: data[c] for c in codes}, SHORT, LONG, STOP, **opts)

    def line(name, curve):
        a = metrics(curve[START:], idx[START:])
        b = metrics(curve[r0:], idx[r0:]) if r0 > START + 60 else a
        c1 = round(a["cagr"] / abs(a["mdd"]), 2) if a["mdd"] else 0
        c2 = round(b["cagr"] / abs(b["mdd"]), 2) if b["mdd"] else 0
        return {"name": name, "cagr": a["cagr"], "mdd": a["mdd"], "cal": c1, "cagr2": b["cagr"], "mdd2": b["mdd"], "cal2": c2}

    cases = [("지금 30종목", stocks)]
    for k, cs in kinds.items():
        if cs:
            cases.append((f"30종목 + {k} ETF ({len(cs)}개)", stocks + cs))
    cases.append((f"30종목 + 금·달러·채권 전부 ({len(got)}개)", stocks + got))
    cases.append((f"ETF {len(got)}개만 (참고)", got))
    rows, results = [], {}
    for name, codes in cases:
        curve, trades = run(codes)
        results[name] = (curve, trades)
        rows.append(line(name, curve))

    print(f"\n[1] 구성별 성과  전체={idx[START].date()}~{idx[-1].date()}  /  뒤 구간={idx[r0].date()}~")
    print(f"{pad('구성', 34)}{'연%':>7}{'낙폭':>8}{'CAL':>6}{'  | 뒤 구간 연%':>14}{'낙폭':>8}{'CAL':>6}")
    for r in rows:
        print(f"{pad(r['name'], 34)}{r['cagr']:>7}{r['mdd']:>8}{r['cal']:>6}{r['cagr2']:>14}{r['mdd2']:>8}{r['cal2']:>6}")

    allname = cases[-2][0]
    ys = sorted({d.year for d in idx[START:]})
    print("\n[2] 연도별 수익률 %  (지금 30종목 vs 전부 추가)")
    print(f"{pad('구성', 34)}" + "".join(f"{y:>8}" for y in ys))
    for nm in (cases[0][0], allname):
        s = pd.Series(results[nm][0], index=idx)
        out = []
        for y in ys:
            sy = s[s.index.year == y]
            prev = s[s.index.year < y]
            base = prev.iloc[-1] if len(prev) and y > ys[0] else sy.iloc[0]
            out.append(round((sy.iloc[-1] / base - 1) * 100, 1))
        print(f"{pad(nm, 34)}" + "".join(f"{v:>8}" for v in out))

    print("\n[3] ETF 개별 특성 (전략이 실제로 매매한 결과는 '전부 추가' 구성 기준)")
    print(f"{pad('ETF', 22)}{'데이터일':>8}{'보유시 연%':>10}{'자체낙폭':>9}{'주식과 상관':>11}{'거래':>5}{'승률%':>7}{'누적손익(만)':>12}")
    ret_stock = pd.DataFrame({c: pd.Series(data[c]["close"], index=idx).pct_change() for c in stocks}).mean(axis=1)
    tr = results[allname][1]
    for c in got:
        close = pd.Series(data[c]["close"], index=idx).dropna()
        yrs = max((close.index[-1] - close.index[0]).days / 365.25, 0.1)
        own_cagr = ((close.iloc[-1] / close.iloc[0]) ** (1 / yrs) - 1) * 100
        own_mdd = (close / close.cummax() - 1).min() * 100
        corr = close.pct_change().corr(ret_stock)
        ts = [t for t in tr if t["code"] == c]
        wins = sum(t["pnl"] > 0 for t in ts)
        print(f"{pad(ASSETS[c][0], 22)}{len(close):>8}{own_cagr:>10.1f}{own_mdd:>9.1f}{corr:>11.2f}{len(ts):>5}{(wins / len(ts) * 100 if ts else 0):>7.0f}{sum(t['pnl'] for t in ts) / 1e4:>12.0f}")

    base, full = rows[0], rows[-2]
    print("\n[자동 해석]")
    ok_all = full["cal"] > base["cal"] and full["cal2"] > base["cal2"] and full["mdd"] >= base["mdd"] - 2
    if ok_all:
        print("- 금·달러·채권을 모두 더하면 전체와 뒤 구간 모두에서 수익 대비 낙폭(CAL)이 좋아지고 낙폭도 크게 나빠지지 않아요. 매매 종목에 추가해 볼 만해요.")
    else:
        print("- 전체와 뒤 구간 모두에서 분명히 좋아진다고 말하기는 어려워요. 한쪽만 좋아졌다면 우연일 수 있으니 바로 넣지 마세요.")
    best = max(rows[1:-2], key=lambda r: r["cal"]) if len(rows) > 3 else None
    if best and best["cal"] > base["cal"]:
        print(f"- 자산군별로 보면 '{best['name']}' 가 가장 좋았어요. 다만 결과를 본 뒤에 고르는 것이라 선택 편향이 생길 수 있어요.")
    print("- 상관이 0에 가깝거나 음수인 ETF일수록 주식이 빠질 때 낙폭을 줄여줄 가능성이 커요 (표 [3]의 '주식과 상관').")
    print("- 이 실험은 과거 데이터라, 특히 금은 최근 크게 올라서 좋아 보일 수 있어요. 한 번의 결과로 결론내지 마세요.")
    config.DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(config.DATA_DIR / "compare_assets.csv", index=False, encoding="utf-8-sig")
    print("결과는 data/compare_assets.csv 에도 저장했어요.")


if __name__ == "__main__":
    main()
