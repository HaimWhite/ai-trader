"""내 PC 의 Ollama(로컬 AI)를 부르는 공통 도구. 매매 판단·계산에는 쓰지 않고 '글 다듬기·설명'에만 씁니다.
- 꺼져 있거나 느리면 조용히 건너뛰고(원래 글을 그대로 사용), 한 번 연결에 실패하면 그 실행에서는 다시 시도하지 않아요.
- 숫자·날짜·링크가 바뀌면 AI 가 쓴 글을 버리고 원래 글을 써요 (numbers_ok)."""
import json
import re
import urllib.error
import urllib.request

import config

_state = {"off": False}


def chat(system, user, json_mode=False, timeout=None):
    """Ollama 에 질문하고 답 글자를 돌려줍니다. 실패하면 None."""
    if _state["off"]:
        return None
    body = {"model": config.OLLAMA_MODEL, "stream": False, "think": False, "options": {"temperature": 0.2 if not json_mode else 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["format"] = "json"
    req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout or config.OLLAMA_TIMEOUT) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError:
        _state["off"] = True
        print("Ollama 에 연결하지 못해 AI 기능은 건너뜁니다.")
        return None
    except Exception as e:
        print("Ollama 호출 실패(무시):", str(e)[:60])
        return None
    text = resp.get("message", {}).get("content", "") or ""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return text.strip() or None


NUM = re.compile(r"\d[\d,]*\.?\d*")


def numbers(text):
    return sorted(m.rstrip(".,") for m in NUM.findall(text or ""))


def numbers_ok(original, new):
    """원문의 숫자(날짜·금액·퍼센트)가 하나도 바뀌거나 빠지거나 늘지 않았는지"""
    return numbers(original) == numbers(new)


def numbers_subset(source, new):
    """설명 글에 나온 숫자가 모두 근거 자료에 있는 숫자인지 (없는 숫자를 지어내지 않았는지)"""
    have = set(numbers(source))
    return all(n in have for n in numbers(new) if len(n.replace(",", "").replace(".", "")) > 1)


POLISH_SYSTEM = (
    "당신은 개인 주식 비서 '하임님의 AI 비서'의 문장 편집자입니다. 아래 보고서를 읽고, 말투만 자연스럽고 부드러운 여성 비서의 존댓말로 다듬으세요.\n"
    "규칙: 1) 숫자, 날짜, 금액, 퍼센트, 종목명, 링크(<...>), 이모지는 한 글자도 바꾸지 마세요. 2) 없는 사실이나 조언·예측을 절대 추가하지 마세요. "
    "3) 줄 구성과 항목(•)은 그대로 유지하세요. 4) 설명이나 따옴표 없이 다듬은 보고서 본문만 출력하세요."
)


def polish(text):
    """보고서 말투 다듬기. 숫자가 하나라도 달라지면 원문 그대로."""
    if not config.OLLAMA_POLISH or not text:
        return text
    new = chat(POLISH_SYSTEM, text, timeout=config.OLLAMA_POLISH_TIMEOUT)
    if not new or not numbers_ok(text, new) or not (0.6 * len(text) <= len(new) <= 1.6 * len(text)):
        return text
    for url in re.findall(r"<https?://[^>]+>", text):
        if url not in new:
            return text
    return new
