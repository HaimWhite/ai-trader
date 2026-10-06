"""자동 실행 작업(작업 스케줄러)을 한 번에 등록합니다. 이미 등록된 것은 건드리지 않아요.
  python register_tasks.py           빠진 작업만 등록
  python register_tasks.py --print   실행하지 않고 등록 명령만 보기
등록되는 작업: 평일 08:55 장중 감시 / 12:30 중간 보고 / 16:00 정기 점검, 금요일 16:30 설정 점검 / 17:00 주간 리포트"""
import base64
import subprocess
import sys

import config

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
# (작업 이름, 실행 파일, 요일, 시각, 절전 해제, 놓친 실행 보충, 설명)
TASKS = [
    ("AITrader", "run_auto.bat", WEEKDAYS, "16:00", True, True, "평일 16:00 정기 점검"),
    ("AITraderMidday", "run_report.bat", WEEKDAYS, "12:30", True, False, "평일 12:30 중간 보고"),
    ("AITraderMonitor", "run_monitor.bat", WEEKDAYS, "08:55", True, True, "평일 08:55 장중 5분 감시"),
    ("AITraderAdvisor", "run_advisor.bat", ("Friday",), "16:30", False, True, "금요일 16:30 설정 점검"),
    ("AITraderWeekly", "run_weekly.bat", ("Friday",), "17:00", False, True, "금요일 17:00 주간 리포트"),
]


def build_script():
    d = str(config.BASE_DIR).replace("'", "''")
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$ProgressPreference = 'SilentlyContinue'",   # '모듈을 준비하는 중' 같은 진행 표시가 오류처럼 보이지 않게
        f"$d = '{d}'",
        "function Reg($name, $bat, $days, $time, $wake, $avail) {",
        "  if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { Write-Output \"$name already\"; return }",
        "  $a = New-ScheduledTaskAction -Execute \"$d\\$bat\" -WorkingDirectory $d",
        "  $t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $time",
        "  $p = @{}",
        "  if ($wake) { $p['WakeToRun'] = $true }",
        "  if ($avail) { $p['StartWhenAvailable'] = $true }",
        "  $s = New-ScheduledTaskSettingsSet @p",
        "  Register-ScheduledTask -TaskName $name -Action $a -Trigger $t -Settings $s | Out-Null",
        "  Write-Output \"$name registered\"",
        "}",
    ]
    for name, bat, days, time, wake, avail, _ in TASKS:
        dd = ",".join(f"'{x}'" for x in days)
        lines.append(f"Reg '{name}' '{bat}' @({dd}) '{time}' ${str(wake).lower()} ${str(avail).lower()}")
    return "\n".join(lines)


def real_error(returncode, err):
    """PowerShell 의 진행 표시(CLIXML)는 오류가 아니므로 걸러냅니다."""
    if returncode != 0:
        return True
    return bool(err) and (not err.startswith("#< CLIXML") or 'S="Error"' in err)


def main():
    script = build_script()
    if "--print" in sys.argv:
        print(script)
        return
    if not sys.platform.startswith("win"):
        print("이 도구는 윈도우에서만 작업을 등록할 수 있어요. (--print 로 명령만 볼 수 있어요)")
        return
    enc = base64.b64encode(script.encode("utf-16le")).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc], capture_output=True)
    out = r.stdout.decode("cp949", "replace")
    err = r.stderr.decode("cp949", "replace").strip()
    desc = {t[0]: t[6] for t in TASKS}
    for ln in out.splitlines():
        parts = ln.strip().split()
        if len(parts) == 2 and parts[0] in desc:
            print(f"{'새로 등록' if parts[1] == 'registered' else '이미 등록됨'}: {parts[0]} ({desc[parts[0]]})")
    if real_error(r.returncode, err):
        print("등록 중 오류가 났어요:", err[:300])
        print("PowerShell 을 '관리자 권한으로 실행'해서 다시 시도해 보세요.")
    else:
        print("\n확인: python check_setup.py")


if __name__ == "__main__":
    main()
