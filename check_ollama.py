"""Ollama 가 실제로 작동하고 있는지 점검합니다.  python check_ollama.py
1) 서버 연결  2) 설치된 모델  3) 실제로 한 번 물어보기(걸리는 시간)  4) 각 기능이 최근에 Ollama 결과를 남겼는지"""
import json
import time
import urllib.request
from datetime import datetime

import config
import llm


def get(path):
    with urllib.request.urlopen(config.OLLAMA_URL.rstrip("/") + path, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def read(name):
    p = config.DATA_DIR / name
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def mark(ok):
    return "[정상]" if ok else "[확인 필요]"


def main():
    print(f"설정: 주소 {config.OLLAMA_URL} / 기본 모델 {config.OLLAMA_MODEL}" + (f" / 가상 트레이더 모델 {config.OLLAMA_TRADER_MODEL}" if config.OLLAMA_TRADER_MODEL else ""))
    try:
        names = [m["name"] for m in get("/api/tags").get("models", [])]
    except Exception as e:
        print(f"{mark(False)} Ollama 서버에 연결하지 못했어요 ({str(e)[:50]}).\n  → 작업 표시줄의 Ollama 아이콘이 켜져 있는지 보고, 꺼져 있으면 Ollama 를 실행하세요.")
        return
    print(f"{mark(True)} 서버 연결됨. 설치된 모델: {', '.join(names) or '없음'}")
    for m in {config.OLLAMA_MODEL, config.OLLAMA_TRADER_MODEL} - {""}:
        if not any(n == m or n.startswith(m + ":") or n.split(":")[0] == m for n in names):
            print(f"{mark(False)} 설정한 모델 '{m}' 이 설치돼 있지 않아요. config.py 의 이름을 위 목록과 맞춰 주세요.")
    try:
        ps = get("/api/ps").get("models", [])
        print("지금 메모리에 올라간 모델:", ", ".join(m["name"] for m in ps) or "없음 (처음 부르면 불러오느라 몇십 초 걸려요)")
    except Exception:
        pass
    t = time.time()
    ans = llm.chat("한국어로 한 문장으로만 답하세요.", "1+1은 얼마인가요? 숫자만 말하고 '준비됐어요'라고 덧붙이세요.", timeout=120)
    sec = time.time() - t
    print(f"{mark(bool(ans))} 실제 질문 테스트: {sec:.1f}초 걸림, 답: {(ans or '응답 없음')[:60]}")
    print("\n각 기능이 최근에 남긴 결과:")
    today = datetime.now().date()

    def age(d):
        try:
            return (today - datetime.strptime(str(d)[:10], "%Y-%m-%d").date()).days
        except Exception:
            return None

    ns = read("news_shadow.json")
    if ns:
        last = max(e["date"] for e in ns)
        print(f"  {mark(age(last) is not None and age(last) <= 4)} 뉴스 그림자: 기록 {len(ns)}건, 마지막 {last}")
    else:
        print(f"  {mark(False)} 뉴스 그림자: 기록 없음")
    ai = read("ai_decisions.json")
    if ai:
        okd = [d for d in ai if not str(d.get("note", "")).startswith("AI 가 응답하지")]
        last = okd[-1]["date"] if okd else "없음"
        print(f"  {mark(bool(okd) and age(last) is not None and age(last) <= 4)} AI 가상 트레이더: 응답한 판단 {len(okd)}번 / 응답 없음 {len(ai) - len(okd)}번, 마지막 정상 판단 {last}")
    else:
        print(f"  {mark(False)} AI 가상 트레이더: 판단 기록 없음")
    tm = read("time_machine.json")
    if tm:
        n = sum(1 for i in tm.get("items", []) if i.get("comment"))
        print(f"  {mark(n > 0)} 타임머신 AI 해설: {n}/{len(tm.get('items', []))}종목, 계산 {tm.get('updated', '?')}")
    rv = read("review.json")
    if rv:
        print(f"  {mark(bool(rv.get('comment')))} 거래 복기 AI 해설: {'있음' if rv.get('comment') else '없음'}")
    print("\n'확인 필요'가 있어도 Ollama 가 꺼져 있던 날은 건너뛰어서 정상이에요. 마지막 날짜가 4일 넘게 멈춰 있으면 정기 점검(16:00) 때 Ollama 가 꺼져 있었던 거예요.")


if __name__ == "__main__":
    main()
