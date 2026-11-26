"""코드이터가 만든 '작은 텍스트 도구' 관리 (승인형). 하임님이 승인한 것만 설치되고, 격리된 별도 프로세스에서만 실행돼요.
  python plugins.py --list              도구 목록과 상태
  python plugins.py --approve 1         도구 1 설치 (디스코드로 '승인 도구1' 이라고 답해도 돼요)
  python plugins.py --reject 1          도구 1 거절 (디스코드: '거절 도구1')
  python plugins.py --remove 1          설치된 도구 1 제거 (디스코드: '제거 도구1')
  python plugins.py --poll              디스코드 답장 확인 (advisor.py --poll 이 10분마다 같이 실행해요)
  python plugins.py --run 1 "글"        도구 1 을 격리해서 시험 실행
● 안전장치: ① 설치 직전에 다시 엄격한 검사(위험한 이름·밑줄 속성·클래스·허용되지 않은 import 거부) ② 별도 프로세스, 제한된 내장 함수와 import, 5초 제한, 비밀 정보(.env)·계좌 파일이 없는 환경
  ③ 글을 받아 글을 돌려주는 일만 해요. 매매·계좌·설정에는 연결되지 않고, 결과는 알림·대시보드의 '글'로만 보여요 ④ 연속 3번 오류면 자동으로 꺼요."""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import codeknow
import config
import notify

STATE = config.DATA_DIR / "plugin_state.json"
DRAFTS = config.BASE_DIR / "plugins_proposed"
ACTIVE = config.BASE_DIR / "plugins_active"
SAMPLE = "연 18.2% · 최대 낙폭 -13.2% · 최근 3년 연수익÷낙폭 1.26 · 후보 66개 시험 · V2 승격"
FORBID_NAMES = {"exec", "eval", "compile", "__import__", "open", "input", "getattr", "setattr", "delattr", "vars", "dir", "globals", "locals", "type", "breakpoint", "memoryview", "super", "object"}
EXPIRE_DAYS = 14
MAX_PENDING = 3
TIMEOUT = 5

RUNNER = r'''
import sys, json, builtins as _b
code = open(sys.argv[1], encoding="utf-8").read()
text = open(sys.argv[2], encoding="utf-8").read()
OK = %s
def _imp(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in OK:
        raise ImportError("blocked: " + name)
    return __import__(name, globals, locals, fromlist, level)
names = "len range min max sum sorted enumerate zip str int float round abs list dict set tuple any all isinstance bool map filter reversed ValueError Exception KeyError IndexError TypeError ZeroDivisionError divmod pow repr format slice".split()
SAFE = {k: getattr(_b, k) for k in names}
SAFE["__import__"] = _imp
ns = {"__builtins__": SAFE, "__name__": "tool"}
try:
    exec(compile(code, "tool", "exec"), ns)
    out = ns["run"](text)
    print(json.dumps({"ok": True, "out": str(out)[:2000]}, ensure_ascii=False))
except BaseException as e:
    print(json.dumps({"ok": False, "error": type(e).__name__ + ": " + str(e)[:150]}, ensure_ascii=False))
''' % repr(sorted(codeknow.PLUGIN_IMPORTS))


def read():
    try:
        d = json.load(open(STATE, encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("items"), list):
            return d
    except Exception:
        pass
    return {"items": []}


def write(st):
    config.DATA_DIR.mkdir(exist_ok=True)
    st["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))


def find(st, n):
    return next((x for x in st["items"] if x["n"] == n), None)


# ---------- 검사 ----------
def strict_scan(code):
    ok, why = codeknow.scan_code(code, allowed_imports=codeknow.PLUGIN_IMPORTS)
    if not ok:
        return False, why
    for n in ast.walk(ast.parse(code)):
        if isinstance(n, ast.ClassDef):
            return False, "클래스는 쓸 수 없어요"
        if isinstance(n, ast.Attribute) and n.attr.startswith("_"):
            return False, f"밑줄 속성 접근: {n.attr}"
        if isinstance(n, ast.Name) and (n.id in FORBID_NAMES or (n.id.startswith("__") and n.id != "__name__")):
            return False, f"쓸 수 없는 이름: {n.id}"
    tree = ast.parse(code)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body):
        return False, "run(text) 함수가 없어요"
    return True, ""


def _python():
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-11] + "python.exe"
    return exe


def sandbox_run(code, text):
    """격리된 별도 프로세스에서 run(text) 실행. (성공 여부, 결과 또는 오류)"""
    with tempfile.TemporaryDirectory() as d:
        cp, tp, rp = Path(d) / "code.py", Path(d) / "text.txt", Path(d) / "runner.py"
        cp.write_text(code, encoding="utf-8")
        tp.write_text(text, encoding="utf-8")
        rp.write_text(RUNNER, encoding="utf-8")
        env = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PATH": os.environ.get("SYSTEMROOT", "")}   # 비밀 정보가 든 환경 변수는 넘기지 않아요
        try:
            r = subprocess.run([_python(), "-I", str(rp), str(cp), str(tp)], capture_output=True, timeout=TIMEOUT, cwd=d, env=env,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return False, f"{TIMEOUT}초 안에 끝나지 않았어요"
        except Exception as e:
            return False, "실행 실패: " + str(e)[:80]
        try:
            d2 = json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except Exception:
            return False, "결과를 읽지 못했어요: " + r.stderr.decode("utf-8", "replace")[:80]
        return (True, d2["out"]) if d2.get("ok") else (False, d2.get("error", "오류"))


# ---------- 초안 등록과 승인 요청 ----------
def pending_count(st):
    return sum(1 for x in st["items"] if x["status"] == "pending")


def register(file, title, ask=True):
    """새 초안을 '도구 N' 으로 등록하고 승인 요청 DM 을 보내요. 도구 번호를 돌려줘요 (대기 중인 초안이 3개 이상이면 None)."""
    st = read()
    if pending_count(st) >= MAX_PENDING:
        return None
    n = max([x["n"] for x in st["items"]] + [0]) + 1
    item = {"n": n, "file": file, "title": title, "status": "pending", "date": datetime.now().strftime("%Y-%m-%d"), "msg_id": None, "errors": 0, "last": ""}
    st["items"].append(item)
    if ask:
        code = (DRAFTS / file).read_text(encoding="utf-8") if (DRAFTS / file).exists() else ""
        ok, out = sandbox_run(code.split('"""', 2)[-1], SAMPLE) if code else (False, "")
        notify.LAST_MESSAGE_ID = None
        sent = notify.send(f"하임님, 코드이터가 새 도구 초안을 만들었어요.\n도구 {n}: {title}\n- 격리해서 시험해 본 결과: {out[:120] if ok else '실행 실패 (' + str(out)[:60] + ')'}\n"
                           f"- 아직 설치되지 않았고, 설치돼도 글을 받아 글을 돌려주는 일만 해요 (매매·계좌와 무관).\n"
                           f"설치하려면 '승인 도구{n}', 버리려면 '거절 도구{n}' 이라고 답해 주세요. ({EXPIRE_DAYS}일 안에 답이 없으면 자동으로 버려요)", mention=True)
        item["msg_id"] = getattr(notify, "LAST_MESSAGE_ID", None) if sent else None
    write(st)
    return n


# ---------- 승인·거절·제거 ----------
def approve(n):
    st = read()
    it = find(st, n)
    if not it or it["status"] != "pending":
        return f"도구 {n} 은(는) 승인 대기 중이 아니에요."
    p = DRAFTS / it["file"]
    if not p.exists():
        it["status"] = "rejected"
        write(st)
        return f"도구 {n} 초안 파일을 찾지 못해 취소했어요."
    code = p.read_text(encoding="utf-8").split('"""', 2)[-1].lstrip("\n")
    ok, why = strict_scan(code)
    if not ok:
        it["status"], it["last"] = "rejected", "설치 전 검사 실패: " + why
        write(st)
        return f"도구 {n} 은(는) 설치 전 안전 검사에서 거절됐어요 ({why})."
    ok, out = sandbox_run(code, SAMPLE)
    if not ok:
        it["status"], it["last"] = "rejected", "시험 실행 실패: " + str(out)
        write(st)
        return f"도구 {n} 은(는) 시험 실행에 실패해서 설치하지 않았어요 ({str(out)[:80]})."
    ACTIVE.mkdir(exist_ok=True)
    (ACTIVE / f"tool{n}.py").write_text(code, encoding="utf-8")
    it["status"], it["last"], it["errors"] = "installed", out[:120], 0
    it["installed"] = datetime.now().strftime("%Y-%m-%d")
    write(st)
    return f"도구 {n} '{it['title']}' 을(를) 설치했어요. 시험 결과: {out[:100]}"


def reject(n):
    st = read()
    it = find(st, n)
    if not it or it["status"] != "pending":
        return f"도구 {n} 은(는) 승인 대기 중이 아니에요."
    it["status"] = "rejected"
    write(st)
    return f"도구 {n} 을(를) 거절했어요."


def remove(n):
    st = read()
    it = find(st, n)
    if not it or it["status"] not in ("installed", "disabled"):
        return f"도구 {n} 은(는) 설치되어 있지 않아요."
    try:
        (ACTIVE / f"tool{n}.py").unlink()
    except Exception:
        pass
    it["status"] = "removed"
    write(st)
    return f"도구 {n} 을(를) 제거했어요."


# ---------- 설치된 도구 사용 ----------
def run_all(text):
    """설치된 도구를 격리해서 실행하고 (제목, 결과) 목록을 돌려줘요. 연속 3번 오류면 자동으로 꺼요."""
    st = read()
    outs = []
    for it in st["items"]:
        if it["status"] != "installed":
            continue
        p = ACTIVE / f"tool{it['n']}.py"
        try:
            code = p.read_text(encoding="utf-8")
            ok, out = strict_scan(code)[0] and sandbox_run(code, text) or (False, "검사 실패")
        except Exception as e:
            ok, out = False, str(e)[:60]
        if ok:
            it["errors"], it["last"] = 0, out[:120]
            outs.append((it["title"], out[:200]))
        else:
            it["errors"] = it.get("errors", 0) + 1
            it["last"] = "오류: " + str(out)[:80]
            if it["errors"] >= 3:
                it["status"] = "disabled"
    write(st)
    return outs


# ---------- 디스코드 답장 확인 ----------
CMD = re.compile(r"(승인|거절|제거)\s*도구\s*(\d+)")


def poll():
    """승인 대기 중인 도구의 DM 에 달린 답장('승인 도구1' 등)과 설치된 도구의 '제거 도구1' 을 처리해요."""
    st = read()
    for it in st["items"]:
        if it["status"] == "pending" and (datetime.now() - datetime.strptime(it["date"], "%Y-%m-%d")).days >= EXPIRE_DAYS:
            it["status"] = "expired"
    write(st)
    ids = [it for it in st["items"] if it.get("msg_id") and it["status"] in ("pending", "installed")]
    notes = []
    if ids:
        first = min(ids, key=lambda x: int(x["msg_id"]))["msg_id"]
        for m in notify.fetch_replies(first) or []:
            for verb, num in CMD.findall(m.get("content") or ""):
                st = read()
                it = find(st, int(num))
                if not it or m["id"] in it.get("acked", []):
                    continue
                it.setdefault("acked", []).append(m["id"])
                write(st)
                res = {"승인": approve, "거절": reject, "제거": remove}[verb](int(num))
                notify.react(m["id"], "✅" if "했어요" in res else "❓")
                notes.append(res)
    for t in notes:
        notify.send("하임님, " + t)
    return notes


def listing():
    st = read()
    if not st["items"]:
        print("아직 도구가 없어요.")
    names = {"pending": "승인 대기", "installed": "설치됨", "rejected": "거절", "removed": "제거됨", "expired": "만료", "disabled": "오류로 꺼짐"}
    for it in st["items"]:
        print(f"도구 {it['n']} [{names.get(it['status'], it['status'])}] {it['title']} ({it['date']}) {it.get('last', '')}")


def main():
    a = sys.argv[1:]
    if "--list" in a or not a:
        return listing()
    if "--poll" in a:
        for t in poll():
            print(t)
        return
    if "--run" in a:
        i = a.index("--run")
        st = read()
        it = find(st, int(a[i + 1]))
        p = (ACTIVE / f"tool{it['n']}.py") if it and it["status"] == "installed" else None
        if not p:
            return print("설치된 도구가 아니에요.")
        print(sandbox_run(p.read_text(encoding="utf-8"), a[i + 2] if len(a) > i + 2 else SAMPLE))
        return
    for flag, fn in (("--approve", approve), ("--reject", reject), ("--remove", remove)):
        if flag in a:
            return print(fn(int(a[a.index(flag) + 1])))


if __name__ == "__main__":
    main()
