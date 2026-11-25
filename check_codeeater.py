"""코드이터가 잘 돌고 있는지 한 번에 점검합니다.   실행: python check_codeeater.py
확인하는 것: 현재 버전과 이번 주 탐색 횟수 / 마지막 오류 / 깃허브 호출 한도와 토큰 / Ollama / 작업 스케줄러 두 작업 / 로그 끝부분"""
import json
import subprocess
import sys
from datetime import datetime

import config


def load(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def ago(ts):
    try:
        m = (datetime.now() - datetime.strptime(ts[:16], "%Y-%m-%d %H:%M")).total_seconds() / 60
        return f"{m / 60:.1f}시간 전" if m >= 90 else f"{m:.0f}분 전"
    except Exception:
        return "?"


def main():
    st = load(config.DATA_DIR / "codeeater.json", {})
    sx = load(config.DATA_DIR / "status.json", {})
    print("== 코드이터 점검 ==")
    if not st.get("versions"):
        print("❌ 기록이 없어요. python codeeater.py 를 한 번 실행하세요.")
    else:
        cur = st["versions"][-1]
        print(f"✅ 현재 V{cur['v']} (총 {len(st['versions'])}개 버전), 마지막 갱신 {st.get('updated', '?')} ({ago(st.get('updated', ''))})")
        p = st.get("pool") or {}
        if p.get("rounds") and not str(p.get("week", "")).startswith("applied"):
            print(f"   이번 주 탐색 {p['rounds']}번 · 시험 {p['tests']}개 · 후보 풀 {len(p.get('cands', []))}개 · 필요 개선폭 {p.get('need')}% · 깃허브 아이디어 {p.get('git_ideas', 0)}개")
            if p["rounds"] >= 3 and not p.get("git_ideas"):
                print("⚠️ 깃허브에서 배운 아이디어가 한 개도 없어요. 아래 깃허브/Ollama 항목을 확인하세요. (스스로 변형 시험만 돌고 있는 상태)")
            for e in p.get("errors", [])[-5:]:
                print("   오류:", e)
        else:
            print("   이번 주 탐색 기록 없음 (월요일 09:00 부터 시작, 금요일 적용 직후에도 이렇게 나와요)")
    for key, name, days in (("codeeater_scout", "탐색", 4), ("codeeater", "적용", 9)):
        s = sx.get(key)
        if s:
            print(f"{'✅' if s.get('ok') else '❌'} {name} 마지막 {s['time'][:16]} ({ago(s['time'])}) {s.get('note', '')}")
        else:
            print(f"– {name} 기록 없음")
    import github_scout
    tok = github_scout.has_token()
    print(f"{'✅' if tok else 'ℹ️'} 깃허브 토큰 {'있음' if tok else '없음'}")
    try:
        r = github_scout.rate_status()
        print(f"✅ 깃허브 연결됨 · 검색 한도 {r['remaining']}/{r['limit']} (초기화 {r['reset']})")
    except Exception as e:
        print("❌ 깃허브 한도 조회 실패 (인터넷 또는 깃허브 문제일 수 있어요):", str(e)[:70])
    if not tok:
        print("   자주 '검색 실패 403'이 나오면 .env 파일에 GITHUB_TOKEN=발급받은토큰 한 줄을 넣으세요. (github.com → Settings → Developer settings → Personal access tokens → 권한 없이 생성)")
    try:
        import llm
        t = llm.chat("한 글자로만 답해.", "OK", timeout=60, model=getattr(config, "CODEEATER_MODEL", None))
        print("✅ Ollama 응답함" if t else "❌ Ollama 가 빈 답을 줬어요 (python check_ollama.py)")
    except Exception as e:
        print("❌ Ollama 확인 실패:", str(e)[:70])
    if sys.platform.startswith("win"):
        for n in ("AITraderCodeEaterScout", "AITraderCodeEaterWeekly"):
            ps = f"$i = Get-ScheduledTaskInfo -TaskName {n} -ErrorAction SilentlyContinue; if ($i) {{ '{n}|' + $i.LastRunTime + '|' + $i.LastTaskResult + '|' + $i.NextRunTime }} else {{ '{n}|none' }}"
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
            out = r.stdout.decode("cp949", "replace").strip()
            if out.endswith("|none") or not out:
                print(f"❌ 작업 {n} 이 등록되어 있지 않아요 → python register_tasks.py --fix-tasks")
            else:
                _, last, res, nxt = (out.split("|") + ["", "", ""])[:4]
                print(f"{'✅' if res in ('0', '267009', '267011') else '⚠️'} 작업 {n}: 마지막 실행 {last} (결과 {res}), 다음 {nxt}")
    log = config.BASE_DIR / "codeeater_log.txt"
    if log.exists():
        print("\n-- codeeater_log.txt 끝부분 --")
        print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]))


if __name__ == "__main__":
    main()
