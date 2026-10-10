"""중요한 기록(가상 계좌·거래·자산 이력 등)을 날짜별로 따로 보관합니다.
- 보관 위치: ai-trader 폴더 '옆'의 ai-trader-backup 폴더 (GitHub에는 올라가지 않아요)
- 16:00 점검 때 자동으로 하루 한 번 만들고, 같은 날 다시 실행하면 그날 것을 덮어써요. 최근 60일치만 남겨요.
- 사용법:
    python backup.py              지금 바로 백업
    python backup.py list         보관된 날짜 보기
    python backup.py restore 2026-10-10   그날 상태로 되돌리기 (먼저 지금 상태를 한 번 더 백업해 둬요)"""
import shutil
import sys
from datetime import datetime

import config

FILES = ["account.json", "trades.json", "history.json", "alerts.json", "forecasts.json", "tuning.json", "review.json"]
EXTRA = ["symbols.csv", "symbols_watch.csv"]       # ai-trader 폴더 안의 설정 파일
KEEP_DAYS = 60
ROOT = config.BASE_DIR.parent / "ai-trader-backup"


def make(tag=None):
    """백업 폴더를 만들고 복사한 파일 수를 돌려줍니다."""
    day = tag or datetime.now().strftime("%Y-%m-%d")
    dest = ROOT / day
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in FILES:
        src = config.DATA_DIR / name
        if src.exists():
            shutil.copy2(src, dest / name)
            n += 1
    for name in EXTRA:
        src = config.BASE_DIR / name
        if src.exists():
            shutil.copy2(src, dest / name)
            n += 1
    days = sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name[:2] == "20")
    for old in days[:-KEEP_DAYS]:
        shutil.rmtree(old, ignore_errors=True)
    return n


def dates():
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir()) if ROOT.exists() else []


def restore(day):
    src = ROOT / day
    if not src.is_dir():
        print("그 날짜의 백업이 없어요. python backup.py list 로 확인하세요.")
        return
    make(datetime.now().strftime("%Y-%m-%d_복원전"))   # 되돌리기 전 상태도 남겨 둠
    for f in src.iterdir():
        dst = (config.DATA_DIR if f.name in FILES else config.BASE_DIR) / f.name
        shutil.copy2(f, dst)
    print(f"{day} 상태로 되돌렸어요. 대시보드에 반영하려면 .\\update_all.bat 을 실행하세요.")


def main():
    a = sys.argv[1:]
    if not a:
        print(f"백업 완료: {make()}개 파일 -> {ROOT}")
    elif a[0] == "list":
        d = dates()
        print("\n".join(d) if d else "아직 백업이 없어요.")
        print(f"(위치: {ROOT})")
    elif a[0] == "restore" and len(a) > 1:
        restore(a[1])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
