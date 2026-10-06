"""설치·설정 점검: 어디가 빠져 있는지 한눈에 확인합니다. 실행: python check_setup.py
  --online   시세 조회까지 확인     --dm   디스코드 테스트 DM 보내기     --claude   Claude API 호출 1회 시험(소액 과금)"""
import importlib
import subprocess
import sys

import config
from notify import _env

OK, NO = "[OK]", "[확인 필요]"


def line(ok, text, hint=""):
    print(f"{OK if ok else NO} {text}" + (f"  -> {hint}" if hint and not ok else ""))


def run(cmd):
    try:
        r = subprocess.run(cmd, cwd=config.BASE_DIR, capture_output=True, text=True, timeout=20)
        return r.returncode, (r.stdout or r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def main():
    print(f"== 점검 시작 (Python {sys.version.split()[0]}) ==")
    for mod, need, hint in (("pandas", True, "pip install pandas"), ("numpy", True, "pip install numpy"),
                            ("FinanceDataReader", True, "pip install finance-datareader"),
                            ("yfinance", False, "pip install yfinance (배당·실적·시세 대체용)")):
        try:
            importlib.import_module(mod)
            line(True, f"라이브러리 {mod}")
        except ImportError:
            line(not need, f"라이브러리 {mod} 없음" + ("" if need else " (선택)"), hint)

    print("\n-- 비밀 설정 (.env, 값은 표시하지 않아요) --")
    for key, need, hint in (("DISCORD_BOT_TOKEN", True, "디스코드 봇 토큰"), ("DISCORD_USER_ID", True, "내 디스코드 사용자 ID"),
                            ("DISCORD_WEBHOOK_URL", False, "웹훅(봇 DM 실패 시 대체)"), ("ANTHROPIC_API_KEY", False, "Claude 뉴스·설정 점검용")):
        line(bool(_env(key)) or not need, f"{key} {'있음' if _env(key) else '없음'}" + ("" if need else " (선택)"), hint)
    code, _ = run(["git", "check-ignore", "-q", ".env"])
    line(code == 0, ".env 가 .gitignore 로 보호됨", ".gitignore 에 .env 를 추가하세요")

    print("\n-- GitHub --")
    code, out = run(["git", "remote", "get-url", "origin"])
    line(code == 0, f"원격 저장소 {out if code == 0 else '없음'}")
    code, out = run(["git", "ls-remote", "--heads", "origin"])
    line(code == 0 and "refs/heads/live" in out, "live 브랜치(장중 실시간 대시보드용)", "python monitor.py --once 를 한 번 실행하세요")

    print("\n-- 데이터 파일 --")
    for name in ("account", "latest", "history", "trades", "prices", "indices", "backtest", "dividends", "status"):
        line((config.DATA_DIR / f"{name}.json").exists(), f"data/{name}.json", "python main.py / backtest.py 를 실행하면 생겨요")
    src = "symbols.csv" if (config.BASE_DIR / "symbols.csv").exists() else "config.py 기본값"
    print(f"[정보] 종목 {len(config.SYMBOLS)}개 (출처: {src})")

    if sys.platform.startswith("win"):
        print("\n-- 자동 실행 작업 (작업 스케줄러) --")
        for name, label in (("AITrader", "평일 16:00 정기 점검"), ("AITraderMidday", "12:30 중간 보고"), ("AITraderMonitor", "장중 5분 감시"),
                            ("AITraderAdvisor", "금요일 설정 점검"), ("AITraderWeekly", "주간 리포트")):
            code, _ = run(["schtasks", "/query", "/tn", name])
            line(code == 0, f"{name} ({label})", "등록 명령은 안내 메시지를 참고하세요" if name != "AITrader" else "")

    if "--online" in sys.argv:
        print("\n-- 시세 조회 시험 --")
        import market
        for code_ in ("005930", "NVDA"):
            try:
                df = market.load_prices(code_, "2026-01-01")
                line(True, f"{code_} 최근 종가 {df['Close'].iloc[-1]:,.0f}원")
            except Exception as e:
                line(False, f"{code_} 조회 실패", str(e)[:80])
    if "--dm" in sys.argv:
        import notify
        line(notify.send("점검용 테스트 메시지입니다.", mention=True), "디스코드 테스트 DM 전송")
    if "--claude" in sys.argv:
        try:
            import news
            r = news._call_claude("테스트", ["[10/01] 테스트 뉴스 제목"])
            line(True, "Claude API 호출 성공")
        except Exception as e:
            line(False, "Claude API 호출 실패", str(e)[:80])


if __name__ == "__main__":
    main()
