"""코드이터 V 를 '본 전략'에 올리는 승인 장치 (Discord 로 물어보고, 하임님이 답해야만 적용)

- 금요일에 V 가 오르면 "V6 을 본 전략에 적용할까요?" 하고 물어봐요.  답장: 승인 V6 / 거절 V6
- 적용 뒤 성적이 이전 설정보다 계속 나쁘면 "되돌릴까요?" 하고 물어봐요.  답장: 되돌려 V5 (그냥 두려면 거절 V5)
- 아무 답이 없으면 5일 뒤에 취소돼요. 자동으로 바뀌는 일은 절대 없어요.
- 적용되는 것은 단기선·장기선·손절·추적손절 4가지뿐이에요 (본 전략에 없는 매수 필터가 붙은 V 는 안내만 하고 적용하지 않아요).
- 적용은 data/live_override.json 에 기록되고, config.py 가 다음 실행부터 읽어요.

사용: python live_apply.py --status | --poll
"""
import json
import re
import sys
from datetime import datetime

import config
import notify

STATE = config.DATA_DIR / "live_apply.json"
OVERRIDE = config.DATA_DIR / "live_override.json"
EXPIRE_DAYS = 5
ROLLBACK_MIN_DAYS = 20        # 적용 뒤 이만큼 거래일이 지나야 되돌리기를 물어봐요
ROLLBACK_GAP = -3.0           # 이전 설정보다 이 %p 이상 나쁠 때만
CMD = re.compile(r"(승인|거절|되돌려|롤백)\s*[vV]\s*(\d+)")
FILTERS = ("rsi_max", "breakout_n", "mom_min", "vol_max", "slope_up")


def read():
    try:
        st = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        st = {}
    st.setdefault("live_v", 1)
    st.setdefault("live_since", None)
    st.setdefault("prev", None)         # 직전에 쓰던 {"v":, "genome":}  (되돌리기용)
    st.setdefault("pending", [])
    st.setdefault("history", [])
    return st


def write(st):
    config.DATA_DIR.mkdir(exist_ok=True)
    st["history"] = st["history"][-30:]
    st["pending"] = st["pending"][-10:]
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))


def can_apply(g):
    """(가능한지, 이유)"""
    if config.LONG_MAS:
        return False, "본 전략이 장기선 여러 개(LONG_MAS) 방식이라 바로 붙일 수 없어요"
    used = [k for k in FILTERS if g.get(k)]
    if g.get("mom_min") is not None and "mom_min" not in used:
        used.append("mom_min")
    if used:
        return False, "본 전략에는 아직 없는 매수 조건(" + ", ".join(used) + ")이 들어 있어요"
    if not (g["short"] < g["long"]):
        return False, "단기선이 장기선보다 길어요"
    return True, ""


def _text(g):
    return f"{g['short']}/{g['long']}일선 · 손절 {g['stop'] * 100:.0f}% · 추적 {g['trail'] * 100:.0f}%"


def _live_now():
    return {"short": config.SHORT_MA, "long": config.LONG_MA, "stop": config.STOP_LOSS_PCT, "trail": config.TRAIL_STOP_PCT}


def _write_override(g):
    config.DATA_DIR.mkdir(exist_ok=True)
    with open(OVERRIDE, "w", encoding="utf-8") as f:
        json.dump({"SHORT_MA": int(g["short"]), "LONG_MA": int(g["long"]), "STOP_LOSS_PCT": float(g["stop"]),
                   "TRAIL_STOP_PCT": float(g["trail"])}, f)


def _pend(st, kind, v, genome, extra=""):
    for p in st["pending"]:
        if p["status"] == "pending":
            p["status"] = "superseded"
    item = {"id": (max([p["id"] for p in st["pending"]] or [0]) + 1), "kind": kind, "v": v, "genome": genome, "date": datetime.now().strftime("%Y-%m-%d"),
            "status": "pending", "msg_id": None, "acked": [], "extra": extra}
    st["pending"].append(item)
    return item


def propose_apply(v, genome, vs_text=""):
    """금요일에 V 가 올랐을 때 호출 → 승인 요청 DM. 돌려주는 글은 보고에 한 줄로 붙여요."""
    st = read()
    if v == st["live_v"]:
        return ""
    ok, why = can_apply(genome)
    if not ok:
        return f"V{v}은 본 전략에 바로 붙일 수 없어요: {why}. (실험실 기록으로만 남겨요)"
    item = _pend(st, "apply", v, genome)
    msg = (f"하임님, 코드이터 V{v}을 본 전략에 적용할까요?\n- 지금 본 전략(V{st['live_v']}): {_text(_live_now())}\n- V{v}: {_text(genome)}\n"
           f"{vs_text}\n답장: **승인 V{v}** 또는 **거절 V{v}** ({EXPIRE_DAYS}일 안에 답이 없으면 취소돼요, 이미 가진 종목은 그대로 두고 앞으로의 신호부터 바뀌어요)")
    if notify.send(msg, mention=True):
        item["msg_id"] = getattr(notify, "LAST_MESSAGE_ID", None)
    write(st)
    return f"V{v} 을 본 전략에 적용할지 따로 DM 으로 여쭤봤어요 (승인 V{v} / 거절 V{v})."


def propose_rollback(prev_text, ret_new, ret_old, days):
    st = read()
    if not st.get("prev") or any(p["status"] == "pending" and p["kind"] == "rollback" for p in st["pending"]):
        return ""
    pv = st["prev"]["v"]
    item = _pend(st, "rollback", pv, st["prev"]["genome"])
    msg = (f"하임님, 본 전략을 V{st['live_v']}로 바꾼 뒤 {days}거래일 동안 이전 설정(V{pv})보다 성적이 나빠요.\n"
           f"- 적용 뒤: V{st['live_v']} {ret_new:+.1f}% / V{pv}였다면 {ret_old:+.1f}% (가상 계산)\n- 이전 설정: {prev_text}\n"
           f"짧은 기간이라 우연일 수도 있어요. 되돌리려면 **되돌려 V{pv}**, 그대로 두려면 **거절 V{pv}** 라고 답해 주세요.")
    if notify.send(msg, mention=True):
        item["msg_id"] = getattr(notify, "LAST_MESSAGE_ID", None)
    write(st)
    return f"적용 뒤 성적이 이전 설정보다 나빠서 되돌릴지 DM 으로 여쭤봤어요 (되돌려 V{pv} / 거절 V{pv})."


def _do_apply(st, item):
    ok, why = can_apply(item["genome"])
    if not ok:
        return f"V{item['v']} 적용 실패: {why}"
    if item["kind"] == "apply":
        st["prev"] = {"v": st["live_v"], "genome": _live_now()}
    else:   # 되돌리기: 되돌린 뒤에는 더 되돌릴 곳이 없어요
        st["prev"] = None
    _write_override(item["genome"])
    st["history"].append({"date": datetime.now().strftime("%Y-%m-%d"), "from": st["live_v"], "to": item["v"], "kind": item["kind"]})
    st["live_v"], st["live_since"] = item["v"], datetime.now().strftime("%Y-%m-%d")
    item["status"] = "done"
    return f"{'적용' if item['kind'] == 'apply' else '되돌리기'}했어요: 본 전략이 V{item['v']}({_text(item['genome'])})로 바뀌었어요. 다음 실행부터 반영돼요."


def poll():
    st = read()
    for p in st["pending"]:
        if p["status"] == "pending" and (datetime.now() - datetime.strptime(p["date"], "%Y-%m-%d")).days >= EXPIRE_DAYS:
            p["status"] = "expired"
    notes = []
    pend = [p for p in st["pending"] if p["status"] == "pending" and p.get("msg_id")]
    if pend:
        first = min(pend, key=lambda x: int(x["msg_id"]))["msg_id"]
        for m in notify.fetch_replies(first) or []:
            for verb, num in CMD.findall(m.get("content") or ""):
                it = next((p for p in st["pending"] if p["status"] == "pending" and p["v"] == int(num)), None)
                if not it or m["id"] in it["acked"]:
                    continue
                it["acked"].append(m["id"])
                good = (verb in ("승인",) and it["kind"] == "apply") or (verb in ("되돌려", "롤백") and it["kind"] == "rollback")
                if good:
                    res = _do_apply(st, it)
                elif verb == "거절":
                    it["status"] = "rejected"
                    res = f"알겠어요, V{it['v']} " + ("적용은 하지 않을게요." if it["kind"] == "apply" else "되돌리지 않고 그대로 둘게요.")
                else:
                    res = f"'{verb} V{num}'은 이 요청에 맞지 않는 답이에요 ({'승인/거절' if it['kind'] == 'apply' else '되돌려/거절'} 으로 답해 주세요)."
                    notify.react(m["id"], "❓")
                    notes.append(res)
                    continue
                notify.react(m["id"], "✅")
                notes.append(res)
    write(st)
    for t in notes:
        notify.send("하임님, " + t, mention=True)
    return notes


def status():
    st = read()
    print(f"본 전략: V{st['live_v']} (적용일 {st['live_since'] or '기본값'}) · 지금 설정 {_text(_live_now())}")
    for p in st["pending"][-5:]:
        print(f"  요청 #{p['id']} [{p['kind']}] V{p['v']} {p['status']} ({p['date']})")
    for h in st["history"][-5:]:
        print(f"  {h['date']} V{h['from']} → V{h['to']} ({h['kind']})")


def main():
    a = sys.argv[1:]
    if "--poll" in a:
        for t in poll():
            print(t)
    else:
        status()


if __name__ == "__main__":
    main()
