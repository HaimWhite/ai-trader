"""종목 목록(symbols.csv)을 명령어로 관리합니다 (엑셀로 열면 코드 앞의 0이 사라질 수 있어서 이 도구를 추천해요).
  python symbols_tool.py list
  python symbols_tool.py add 051910 LG화학 KR 화학      (시장: KR=코스피, KQ=코스닥, US=미국)
  python symbols_tool.py add TSM 티에스엠씨 US 반도체
  python symbols_tool.py remove 051910                  (코드 또는 이름)"""
import csv
import sys
from datetime import datetime, timedelta

import config
from broker import PaperBroker

PATH = config.BASE_DIR / "symbols.csv"


def read():
    rows = []
    if PATH.exists():
        text = PATH.read_text(encoding="utf-8-sig")
        for r in csv.DictReader(text.splitlines()):
            code = r["code"].strip()
            r["code"] = code.zfill(6) if code.isdigit() else code.upper()
            rows.append(r)
    return rows


def write(rows):
    with open(PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "market", "sector"])
        w.writeheader()
        w.writerows(rows)


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("list", "add", "remove"):
        print(__doc__)
        return
    rows = read()
    if args[0] == "list":
        for r in rows:
            print(f"{r['code']:<8}{r['name']:<12}{r['market']:<4}{r.get('sector', '')}")
        print(f"총 {len(rows)}종목")
        return
    if args[0] == "add":
        if len(args) < 4:
            print(__doc__)
            return
        code = args[1].zfill(6) if args[1].isdigit() else args[1].upper()
        name, market, sector = args[2], args[3].upper(), (args[4] if len(args) > 4 else "")
        if market not in ("KR", "KQ", "US"):
            print("시장은 KR(코스피), KQ(코스닥), US(미국) 중 하나여야 해요.")
            return
        if any(r["code"] == code for r in rows):
            print("이미 있는 종목이에요.")
            return
        if (market == "US") != code.isalpha():
            print("미국 종목은 영문 티커(예: NVDA), 한국 종목은 숫자 6자리 코드여야 해요.")
            return
        import market as mk
        try:
            df = mk.load_prices(code, (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"))
            print(f"확인 완료: {name} 최근 종가 {df['Close'].iloc[-1]:,.0f}원 (최근 {len(df)}일 데이터)")
        except Exception as e:
            print("시세를 조회하지 못해서 추가하지 않았어요:", str(e)[:100])
            return
        rows.append({"code": code, "name": name, "market": market, "sector": sector})
        write(rows)
        print(f"추가했어요. 현재 {len(rows)}종목. 다음 실행부터 반영돼요.")
        return
    key = args[1] if len(args) > 1 else ""
    hit = [r for r in rows if r["code"] == (key.zfill(6) if key.isdigit() else key.upper()) or r["name"] == key]
    if not hit:
        print("종목을 찾지 못했어요.")
        return
    held = PaperBroker().account["positions"]
    if hit[0]["code"] in held:
        print(f"{hit[0]['name']}은(는) 지금 보유 중이에요. 먼저 매도한 뒤(python adjust.py {hit[0]['name']} =0) 제거하세요.")
        return
    write([r for r in rows if r is not hit[0]])
    print(f"{hit[0]['name']}을(를) 제거했어요. 현재 {len(rows) - 1}종목.")


if __name__ == "__main__":
    main()
