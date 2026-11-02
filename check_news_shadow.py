"""Ollama 뉴스 판단이 키워드 판단보다 나은지 비교합니다.   실행: python check_news_shadow.py
기록(data/news_shadow.json)된 날짜별 판단 뒤 5거래일 동안 그 종목이 실제로 얼마나 움직였는지(시장 평균 대비 아님, 종목 자체 수익률)를 점수 그룹별로 보여줘요.
악재(-1·-2)라고 한 종목이 그 뒤에 더 떨어지면 판단이 쓸모 있다는 뜻이에요. 기록이 몇 주 쌓이기 전에는 결론을 내지 마세요."""
import json
from datetime import datetime

import config

H = 5


def load(name, default):
    p = config.DATA_DIR / name
    return json.load(open(p, encoding="utf-8")) if p.exists() else default


def fwd(prices, code, day, h=H):
    p = prices.get(code)
    if not p:
        return None
    d, c = p["dates"], p["close"]
    i = max((k for k, x in enumerate(d) if x <= day), default=None)
    if i is None or i + h >= len(d):
        return None
    return (c[i + h] / c[i] - 1) * 100


def group(score):
    return "악재(-1·-2)" if score <= -1 else "호재(+1·+2)" if score >= 1 else "중립(0)"


def main():
    log, prices = load("news_shadow.json", []), load("prices.json", {})
    if not log:
        print("아직 기록이 없어요. 16:00 점검이 몇 번 돈 뒤에 다시 실행하세요. (Ollama 가 켜져 있어야 기록돼요)")
        return
    days = sorted({e["date"] for e in log})
    print(f"기록 {len(log)}건 ({days[0]} ~ {days[-1]}, 모델 {log[-1].get('model', '?')})")
    agree = sum(1 for e in log if group(e["kw"]) == group(e["ollama"]))
    print(f"키워드와 Ollama 의 판단이 같은 비율: {agree / len(log) * 100:.0f}%")
    for who, key in (("키워드", "kw"), ("Ollama", "ollama")):
        print(f"\n[{who}] 판단 뒤 {H}거래일 수익률")
        print(f"{'구분':<14}{'건수':>6}{'평균%':>8}{'하락 비율%':>11}")
        for g in ("악재(-1·-2)", "중립(0)", "호재(+1·+2)"):
            rs = [fwd(prices, e["code"], e["date"]) for e in log if group(e[key]) == g]
            rs = [r for r in rs if r is not None]
            if rs:
                print(f"{g:<14}{len(rs):>6}{sum(rs) / len(rs):>8.2f}{sum(1 for r in rs if r < 0) / len(rs) * 100:>11.0f}")
            else:
                print(f"{g:<14}{0:>6}{'-':>8}{'-':>11}")
    print("\n악재 그룹의 평균이 중립·호재보다 뚜렷하게 낮아야 '쓸 만한 판단'이에요. 건수가 적으면(그룹당 30건 미만) 우연일 수 있어요.")
    diff = [e for e in log if group(e["kw"]) != group(e["ollama"])][-8:]
    if diff:
        print("\n판단이 달랐던 최근 사례:")
        for e in diff:
            print(f"  {e['date']} {e['name']}: 키워드 {e['kw']:+d} / Ollama {e['ollama']:+d} - {e['summary']}")


if __name__ == "__main__":
    main()
