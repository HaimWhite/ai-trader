"""각 작업이 마지막으로 성공한 시각을 data/status.json 에 기록합니다 (대시보드 '작동 상태'에 표시)."""
import json
from datetime import datetime

import config


def beat(name, ok=True, note=""):
    try:
        p = config.DATA_DIR / "status.json"
        d = json.load(open(p, encoding="utf-8")) if p.exists() else {}
        d[name] = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "ok": bool(ok), "note": str(note)[:200]}
        config.DATA_DIR.mkdir(exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
