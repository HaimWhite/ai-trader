"""5분 감시가 왜 멈췄는지 한 번에 점검합니다. 실행: python check_monitor.py
확인하는 것: ① 작업 스케줄러의 감시 작업 설정과 마지막 실행 결과 ② monitor_log.txt 의 마지막 기록·오류
③ 오늘 PC 가 절전/깨어남을 한 일 ④ GitHub 에 올라간 실시간 데이터의 마지막 갱신 시각
결과는 화면에 나오고 check_monitor_report.txt 에도 저장돼요. (문제가 있으면 이 파일 내용을 보내 주세요)"""
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime

import config

OUT = []
try:
    sys.stdout.reconfigure(errors="replace")   # 윈도우 콘솔에서 이모지 때문에 멈추지 않게
except Exception:
    pass


def say(s=""):
    print(s)
    OUT.append(s)


def ps(cmd, timeout=40):
    if not sys.platform.startswith("win"):
        return None
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + cmd],
                           capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace").strip()
    except Exception as e:
        return f"(실행 실패: {e})"


def tasks():
    say("[1] 작업 스케줄러 (AITraderMonitor)")
    out = ps("$t=Get-ScheduledTask AITraderMonitor -ErrorAction SilentlyContinue; if(-not $t){'없음'; exit}; "
             "$s=$t.Settings; $i=Get-ScheduledTaskInfo AITraderMonitor; "
             "\"상태=$($t.State)\"; \"배터리로 전환 시 중지=$($s.StopIfGoingOnBatteries)\"; \"배터리일 때 시작 안 함=$($s.DisallowStartIfOnBatteries)\"; "
             "\"실행 시간 제한=$($s.ExecutionTimeLimit)\"; \"절전 해제 후 실행=$($s.WakeToRun)\"; \"놓친 실행 보충=$($s.StartWhenAvailable)\"; "
             "\"마지막 실행=$($i.LastRunTime)\"; \"마지막 결과 코드=$($i.LastTaskResult)\"; \"다음 실행=$($i.NextRunTime)\"")
    if out is None:
        say("  (윈도우가 아니라 건너뜀)")
        return
    for ln in out.splitlines():
        say("  " + ln)
    if "없음" == out.strip():
        say("  ❌ 감시 작업이 등록돼 있지 않아요 -> python register_tasks.py")
        return
    if "배터리로 전환 시 중지=True" in out:
        say("  ⚠️ 배터리로 전환되면 감시가 멈추는 설정이에요. 고치는 명령은 채팅에서 안내한 Set-ScheduledTask 입니다.")
    if re.search(r"실행 시간 제한=PT[0-3]H|실행 시간 제한=PT\d+M", out):
        say("  ⚠️ 실행 시간 제한이 짧아요. 8시간(PT8H)으로 늘려야 해요.")
    m = re.search(r"마지막 결과 코드=(\d+)", out)
    if m and m.group(1) not in ("0", "267009"):    # 0=성공, 267009=실행 중
        say(f"  ⚠️ 마지막 결과 코드 {m.group(1)} (0이 아니면 비정상 종료예요)")


def log():
    say("\n[2] monitor_log.txt")
    p = config.BASE_DIR / "monitor_log.txt"
    if not p.exists():
        say("  로그 파일이 없어요 (감시가 한 번도 실행된 적 없거나 다른 폴더에서 실행됨)")
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    today = datetime.now().strftime("%Y-%m-%d")
    runs = [i for i, ln in enumerate(lines) if "(monitor) =====" in ln]
    say(f"  로그 {len(lines)}줄, 실행 기록 {len(runs)}회")
    ticks = [ln for ln in lines if re.match(r"\[\d\d:\d\d\] 확인 완료", ln)]
    if ticks:
        say("  마지막 5분 확인: " + ticks[-1])
    if runs:
        say("  마지막 시작: " + lines[runs[-1]].strip("= "))
    errs = [i for i, ln in enumerate(lines) if "Traceback" in ln]
    if errs:
        i = errs[-1]
        say("  ❌ 마지막 오류(Traceback):")
        for ln in lines[i:i + 12]:
            say("     " + ln)
    tail = [ln for ln in lines[-8:] if ln.strip()]
    say("  --- 마지막 줄들 ---")
    for ln in tail:
        say("   " + ln[:160])
    if lines and "장중 감시를 마칩니다" not in "\n".join(lines[-3:]) and ticks:
        say("  ⚠️ 정상 종료 문구가 없어요 -> 도중에 강제로 꺼졌을 가능성이 있어요 (절전·종료·창 닫기·작업 중지)")


def power():
    say("\n[3] 오늘 PC 절전/깨어남 기록 (윈도우 이벤트)")
    today = datetime.now().strftime("%Y-%m-%d")
    out = ps("$d=(Get-Date).Date; Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=$d; ProviderName='Microsoft-Windows-Kernel-Power','Microsoft-Windows-Power-Troubleshooter'} "
             "-ErrorAction SilentlyContinue | Where-Object { $_.Id -in 42,107,1,41,109,506,507 } | Sort-Object TimeCreated | "
             "ForEach-Object { '{0:HH:mm:ss}  ID {1}  {2}' -f $_.TimeCreated, $_.Id, (($_.Message -split \"`n\")[0]) }", timeout=60)
    if out is None:
        say("  (윈도우가 아니라 건너뜀)")
        return
    if not out:
        say("  오늘 절전·재부팅 기록이 없어요 (또는 읽을 권한이 없음)")
        return
    for ln in out.splitlines()[-14:]:
        say("  " + ln[:150])
    say("  (ID 42=절전 들어감, 107/1=깨어남, 41=비정상 종료, 506/507=모던 대기 진입/해제)")


def remote():
    say("\n[4] GitHub 에 올라간 실시간 데이터")
    try:
        url = "https://raw.githubusercontent.com/HaimWhite/ai-trader/live/live.json?t=" + str(int(datetime.now().timestamp()))
        d = json.load(urllib.request.urlopen(url, timeout=15))
        upd = d["updated_at"]
        age = (datetime.now() - datetime.strptime(upd, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
        say(f"  live.json 마지막 갱신: {upd} ({age:.0f}분 전)")
        now = datetime.now()
        market = now.weekday() < 5 and "09:00" <= now.strftime("%H:%M") <= "15:35"
        if market and age > 12:
            say("  ❌ 장중인데 12분 넘게 갱신이 없어요 -> 감시가 멈춘 상태예요. run_monitor.bat 로 다시 켜세요.")
        elif market:
            say("  ✅ 장중 5분 갱신이 정상이에요")
        else:
            say("  (지금은 장 시간이 아니라 갱신이 없는 게 정상이에요)")
    except Exception as e:
        say(f"  읽지 못했어요: {e}")


def main():
    say(f"점검 시각: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    for f in (tasks, log, power, remote):
        try:
            f()
        except Exception as e:
            say(f"  (점검 중 오류: {e})")
    (config.BASE_DIR / "check_monitor_report.txt").write_text("\n".join(OUT), encoding="utf-8")
    say("\n결과를 check_monitor_report.txt 에도 저장했어요.")


if __name__ == "__main__":
    main()
