"""코드이터를 매일 장 마감 뒤(16:30) 자동으로 업그레이드하고, 끝나면 버전(V몇)을 디스코드로 알려줍니다.
  python codeeater_daily.py            지금 바로 업그레이드 (평소엔 작업 스케줄러가 평일 16:30 에 실행)
  python codeeater_daily.py --status   현재 버전과 최근 기록 보기
  python codeeater_daily.py --dry      실제 실행 없이 설정만 확인
● 코드이터가 받는 '주식 데이터'는 업그레이드와 별개예요. config.py 의 CODEEATER_DATA_DIR 를 적으면 업그레이드 전에 오늘 갱신된 주식 데이터(시세·거래·타임머신 등)를 그 폴더로 복사해서 넘겨요.
● 버전은 CODEEATER_VERSION_FILE 이 있으면 그 파일의 글자를, 없으면 성공할 때마다 1씩 올리는 번호(V1, V2…)를 써요."""
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import config
import notify
import status

LOG = config.DATA_DIR / "codeeater.json"
TEXT_LOG = config.BASE_DIR / "codeeater_log.txt"
DATA_FILES = ["prices.json", "history.json", "trades.json", "latest.json", "indices.json", "time_machine.json", "news_shadow.json"]


def read():
    try:
        return json.load(open(LOG, encoding="utf-8"))
    except Exception:
        return {"n": 0, "version": "V0", "runs": []}


def write(d):
    config.DATA_DIR.mkdir(exist_ok=True)
    d["runs"] = d["runs"][-60:]
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def read_version(fallback):
    p = config.CODEEATER_VERSION_FILE
    if p:
        try:
            t = Path(p).read_text(encoding="utf-8").strip().splitlines()[0].strip()
            if t:
                return t if t[:1] in "vV" else "V" + t
        except Exception:
            pass
    return fallback


def send_data():
    """코드이터가 받는 주식 데이터 폴더로 오늘 데이터를 복사 (설정했을 때만)"""
    dest = config.CODEEATER_DATA_DIR
    if not dest:
        return 0
    Path(dest).mkdir(parents=True, exist_ok=True)
    n = 0
    for name in DATA_FILES:
        src = config.DATA_DIR / name
        if src.exists():
            shutil.copy2(src, Path(dest) / name)
            n += 1
    return n


def main():
    d = read()
    if "--status" in sys.argv:
        print(f"코드이터 현재 버전: {d['version']} (업그레이드 성공 {d['n']}번)")
        for r in d["runs"][-8:]:
            print(f"  {r['time']}  {r['version']}  {'성공' if r['ok'] else '실패'}  {r['minutes']}분  {r.get('note', '')}")
        return
    cwd = Path(config.CODEEATER_DIR)
    if "--dry" in sys.argv:
        print("폴더:", cwd, "(있음)" if cwd.exists() else "(없음!)")
        print("명령:", config.CODEEATER_CMD)
        print("주식 데이터 폴더:", config.CODEEATER_DATA_DIR or "(넘기지 않음)")
        print("버전 파일:", config.CODEEATER_VERSION_FILE or "(없음: 성공할 때마다 번호를 세요)")
        return
    if not cwd.exists():
        msg = f"하임님, 코드이터 폴더({cwd})를 찾지 못해서 오늘 업그레이드를 하지 못했어요. config.py 의 CODEEATER_DIR 를 확인해 주세요."
        print(msg)
        notify.send(msg, mention=True)
        status.beat("codeeater", False, "폴더 없음")
        return
    try:
        n_files = send_data()
    except Exception as e:
        n_files = 0
        print("주식 데이터 전달 실패(업그레이드는 계속):", str(e)[:80])
    t0 = time.time()
    ok, note = False, ""
    with open(TEXT_LOG, "a", encoding="utf-8") as lf:
        lf.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M} 업그레이드 시작 =====\n")
        try:
            r = subprocess.run(config.CODEEATER_CMD, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT, timeout=config.CODEEATER_TIMEOUT_MIN * 60)
            ok = r.returncode == 0
            note = "" if ok else f"종료 코드 {r.returncode}"
        except subprocess.TimeoutExpired:
            note = f"{config.CODEEATER_TIMEOUT_MIN}분을 넘겨 중단"
        except Exception as e:
            note = str(e)[:80]
    minutes = round((time.time() - t0) / 60, 1)
    old = d["version"]
    if ok:
        d["n"] += 1
        d["version"] = read_version(f"V{d['n']}")
    d["runs"].append({"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "ok": ok, "version": d["version"], "minutes": minutes, "note": note})
    write(d)
    status.beat("codeeater", ok, f"{d['version']} {note}".strip())
    if ok:
        extra = f" 오늘 주식 데이터 {n_files}개도 전달했어요." if n_files else ""
        msg = f"하임님, 코드이터 업그레이드가 끝났어요. 이제 **{d['version']}**입니다. (이전 {old}, 소요 {minutes}분){extra}"
    else:
        msg = f"하임님, 오늘 코드이터 업그레이드가 실패했어요. ({note}) 버전은 그대로 {old}입니다. codeeater_log.txt 를 확인해 주세요."
    print(msg)
    notify.send(msg, mention=not ok)


if __name__ == "__main__":
    main()
