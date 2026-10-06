"""설치·설정 점검: 어디가 빠져 있는지 한눈에 확인합니다. 실행: python check_setup.py
  --online   시세 조회까지 확인     --dm   디스코드 테스트 DM 보내기     --claude   Claude API 호출 1회 시험(소액 과금)"""
import importlib
import json
import subprocess
import sys
from datetime import datetime

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


def _read(name, default=None):
    p = config.DATA_DIR / name
    return json.load(open(p, encoding="utf-8")) if p.exists() else default


def data_checks():
    acc, latest, hist = _read("account.json"), _read("latest.json"), _read("history.json", [])
    if not acc or not latest:
        line(False, "account.json / latest.json 이 아직 없어요", "python main.py 를 한 번 실행하세요")
        return
    pos = acc["positions"]
    line(acc["cash"] >= 0, f"현금이 음수가 아님 ({acc['cash']:,.0f}원)")
    line(len(pos) <= config.MAX_POSITIONS, f"보유 {len(pos)}종목 (동시 보유 한도 {config.MAX_POSITIONS})", "한도를 줄였다면 일시적일 수 있어요")
    gone = [p["name"] for c, p in pos.items() if c not in config.SYMBOLS]
    line(not gone, "보유 종목이 모두 종목 목록에 있음" if not gone else f"종목 목록에서 빠진 보유 종목: {', '.join(gone)}", "먼저 매도하거나 목록에 다시 추가하세요")
    age = (datetime.now() - datetime.strptime(latest["updated_at"], "%Y-%m-%d %H:%M:%S")).days
    line(age <= 4, f"마지막 정기 점검 {latest['updated_at']} ({age}일 전)", "자동 실행이 멈췄을 수 있어요 (공휴일이면 정상)")
    if hist:
        line(hist[-1]["date"] == latest["updated_at"][:10], f"자산 기록 날짜가 점검 날짜와 같음 ({hist[-1]['date']})")
    prices = _read("prices.json", {})
    miss = [n for c, n in config.SYMBOLS.items() if c not in prices]
    line(not miss, f"주가 기록이 모든 종목({len(config.SYMBOLS)}개)에 있음" if not miss else f"주가 기록이 없는 종목 {len(miss)}개: {', '.join(miss[:5])}", "python main.py 를 다시 실행하세요")
    r = latest.get("rules", {})
    same = r.get("trail_pct") == config.TRAIL_STOP_PCT and r.get("stop_loss_pct") == config.STOP_LOSS_PCT and r.get("max_positions") == config.MAX_POSITIONS
    line(same, "최근 점검에 쓴 설정이 지금 설정과 같음", "설정이 바뀐 뒤 아직 점검을 안 돌렸어요 (python main.py)")
    bt = _read("backtest.json")
    if bt:
        try:
            from backtest import settings_text
            line(bt.get("settings") == settings_text(), "백테스트가 지금 설정으로 계산된 결과임", "python backtest.py 를 다시 실행하세요")
        except Exception as e:
            print("[정보] 백테스트 설정 비교를 건너뜀:", str(e)[:60])
    tun = _read("tuning.json")
    print(f"[정보] 승인된 설정 조정값: {tun if tun else '없음(기본값 사용 중)'}")
    print(f"[정보] 예약된 주문 {len(acc.get('pending', {}))}건 / 뉴스 분석 방식 {latest.get('news_mode', '-')}")


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
        missing = 0
        from register_tasks import TASKS
        for name, bat, days, time, wake, avail, label in TASKS:
            ps = (f"$i = Get-ScheduledTaskInfo -TaskName '{name}'; "
                  "$f = {param($x) if ($x.Year -lt 2000) { '-' } else { $x.ToString('yyyy-MM-dd HH:mm') }}; "
                  "Write-Output ((& $f $i.LastRunTime) + '|' + $i.LastTaskResult + '|' + (& $f $i.NextRunTime))")
            code, out = run(["powershell", "-NoProfile", "-Command", ps])
            if code != 0 or out.count("|") != 2:
                missing += 1
                line(False, f"{name} ({label}) 등록 안 됨", "python register_tasks.py 를 실행하면 한 번에 등록돼요")
                continue
            last, result, nxt = out.split("|")
            meaning = {"0": "정상 종료", "267009": "실행 중", "267011": "아직 실행 전", "267014": "중간에 종료됨"}.get(result.strip(), f"종료 코드 {result.strip()}")
            line(result.strip() in ("0", "267009", "267011"), f"{name} ({label}) | 마지막 실행 {last} ({meaning}) | 다음 실행 {nxt}", "로그 파일을 확인하세요")
        if missing:
            print(f"   -> 등록 안 된 작업이 {missing}개 있어요: python register_tasks.py")

    print("\n-- 로그 파일의 오류 흔적 --")
    for fname in ("run_log.txt", "monitor_log.txt", "advisor_log.txt", "weekly_log.txt"):
        p = config.BASE_DIR / fname
        if not p.exists():
            print(f"[정보] {fname} 없음 (아직 한 번도 실행되지 않았거나 해당 작업이 없어요)")
            continue
        lines = p.read_bytes().decode("cp949", "replace").splitlines()[-2000:]
        heads = [i for i, ln in enumerate(lines) if ln.startswith("=====")]
        if len(heads) >= 3:   # 최근 3번의 실행 기록만 확인 (오래된 오류가 계속 남아 있지 않도록)
            lines = lines[heads[-3]:]
        bad = [i for i, ln in enumerate(lines) if "Traceback" in ln or "Error" in ln or "실패" in ln]
        age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() / 3600
        if bad:
            line(False, f"{fname} (최근 {age:.0f}시간 전 기록) 오류 흔적: {lines[bad[-1]].strip()[:70]}", "해당 부분을 복사해서 보내주세요")
        else:
            line(True, f"{fname} (마지막 기록 {age:.0f}시간 전) 오류 흔적 없음")

    print("\n-- 데이터 정합성 --")
    data_checks()

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
