import sys

for _stream in (sys.stdout, sys.stderr):   # 윈도우 콘솔(cp949)이 표시하지 못하는 문자(•, 이모지 등) 때문에 프로그램이 멈추지 않도록
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# 매매할 종목 (코드: 이름)
SYMBOLS = {
    # 코스피 (15)
    "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER", "005380": "현대차", "105560": "KB금융",
    "207940": "삼성바이오로직스", "000270": "기아", "068270": "셀트리온", "006400": "삼성SDI", "055550": "신한지주",
    "012330": "현대모비스", "033780": "KT&G", "032830": "삼성생명", "086280": "현대글로비스", "015760": "한국전력",
    # 코스닥 (6)
    "247540": "에코프로비엠", "196170": "알테오젠", "263750": "펄어비스", "086520": "에코프로", "028300": "HLB", "058470": "리노공업",
    # 나스닥 (9, 영문 티커로 입력하면 미국 종목으로 인식, 달러 시세를 원화로 환산)
    "NVDA": "엔비디아", "AAPL": "애플", "MSFT": "마이크로소프트", "AMZN": "아마존", "GOOGL": "알파벳",
    "META": "메타", "TSLA": "테슬라", "AVGO": "브로드컴", "NFLX": "넷플릭스",
}
KOSDAQ_CODES = {"247540", "196170", "263750", "086520", "028300", "058470"}   # 코스닥 종목 (배당 조회·손절선 구분용)
SECTORS = {   # 업종 (같은 업종에 몰리는 것을 막는 옵션용)
    "005930": "반도체", "000660": "반도체", "058470": "반도체", "NVDA": "반도체", "AVGO": "반도체",
    "035420": "인터넷", "263750": "인터넷", "AMZN": "인터넷", "GOOGL": "인터넷", "META": "인터넷",
    "005380": "자동차", "000270": "자동차", "012330": "자동차", "TSLA": "자동차",
    "105560": "금융", "055550": "금융", "032830": "금융",
    "207940": "바이오", "068270": "바이오", "196170": "바이오", "028300": "바이오",
    "006400": "배터리", "247540": "배터리", "086520": "배터리",
    "AAPL": "IT", "MSFT": "IT", "033780": "소비재", "NFLX": "소비재", "086280": "산업", "015760": "에너지",
}


def _load_symbols_csv():
    """symbols.csv 가 있으면 종목·시장·업종을 거기서 읽습니다 (코드를 열지 않고 종목을 바꿀 수 있게)."""
    import csv
    p = BASE_DIR / "symbols.csv"
    if not p.exists():
        return None
    try:
        try:
            text = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = p.read_text(encoding="cp949")
        syms, kq, sec = {}, set(), {}
        for r in csv.DictReader(text.splitlines()):
            code = r["code"].strip()
            code = code.zfill(6) if code.isdigit() else code.upper()
            if not code:
                continue
            syms[code] = r["name"].strip()
            if r.get("market", "").strip().upper() == "KQ":
                kq.add(code)
            if r.get("sector", "").strip():
                sec[code] = r["sector"].strip()
        return (syms, kq, sec) if syms else None
    except Exception as e:
        print("symbols.csv 를 읽지 못해 기본 종목을 씁니다:", e)
        return None


_csv = _load_symbols_csv()
if _csv:
    SYMBOLS, KOSDAQ_CODES, SECTORS = _csv

# 관찰 목록 (symbols_watch.csv): 매매는 하지 않고 신호만 대시보드에 보여주는 종목
WATCH = {}


def _load_watch():
    import csv
    p = BASE_DIR / "symbols_watch.csv"
    if not p.exists():
        return
    try:
        for r in csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()):
            code = r["code"].strip()
            code = code.zfill(6) if code.isdigit() else code.upper()
            if code and code not in SYMBOLS:
                WATCH[code] = {"name": r["name"].strip(), "sector": r.get("sector", "").strip()}
                if r.get("market", "").strip().upper() == "KQ":
                    KOSDAQ_CODES.add(code)   # 시세 조회·시장 분류용 (매매 종목에는 영향 없음)
    except Exception as e:
        print("symbols_watch.csv 를 읽지 못했어요:", e)


# 가상 시작 자금 (원)
INITIAL_CASH = 20_000_000

# 비용 설정
FEE_RATE = 0.00015      # 수수료 (매수/매도 각각) 0.015%
SELL_TAX_RATE = 0.002   # 매도 거래세 약 0.2% (세율은 바뀔 수 있으니 확인 후 조정)
SLIPPAGE_RATE = 0.001   # 체결가를 불리하게 가정 0.1%
US_FEE_RATE = 0.0025    # 미국 주식 수수료 0.25% (증권사마다 다름, 매수/매도 각각)
US_FX_COST = 0.001      # 환전 비용(환율 스프레드) 0.1% (매수/매도 각각, 증권사·우대 조건마다 다름)
# 미국 주식은 매도 거래세가 없지만, 연간 양도소득세(수익의 22%, 연 250만 원 공제)는 반영하지 않았습니다.

MAX_POSITIONS = 5       # 동시에 보유할 최대 종목 수. 종목당 투자 한도 = 총자산 ÷ 이 값


def is_us(code):
    return code.isalpha()


def group_of(code):
    """종목을 큰 분류로 묶습니다: 코스피 / 코스닥 / 나스닥(미국)"""
    if is_us(code):
        return "나스닥"
    return "코스닥" if code in KOSDAQ_CODES else "코스피"


def fee_rate(code):
    return (US_FEE_RATE + US_FX_COST) if is_us(code) else FEE_RATE


def sell_tax_rate(code):
    return 0.0 if is_us(code) else SELL_TAX_RATE

# 전략 설정
SHORT_MA = 20           # 단기 이동평균 (일)
LONG_MA = 120           # 장기 이동평균 (일)
# 장기선을 여러 개 함께 쓰는 옵션 (compare_ma.py 로 비교한 뒤 켜세요). 기본은 꺼짐(LONG_MA 하나만 사용)
LONG_MAS = None         # 예: (60, 90, 120) -> 단기선을 이 장기선들과 함께 비교 (가장 긴 값이 LONG_MA 와 같아야 함)
LONG_RULE = "all"       # "all": 모든 장기선 위일 때만 상승 / "majority": 절반 넘게 위 / "any": 하나라도 위
SHOW_MAS = (60, 90, 120)   # 대시보드·판단표에 참고용으로 보여줄 장기선 (매매에 쓰는지와는 별개)
STOP_LOSS_PCT = -0.07   # 매입가 대비 -7% 이하이면 손절
TRAIL_STOP_PCT = 0.20   # 추적 손절: 매수 후 최고가 대비 이 비율만큼 내려오면 매도 (끄려면 None)

# 백테스트 설정
BACKTEST_START = "2021-01-01"   # 백테스트 시작일

# 대시보드 주가 그래프에 쓸 시세 기록 시작일
PRICE_HISTORY_START = "2020-01-01"

# 뉴스 설정
USE_NEWS = True                          # 뉴스 분석 사용 (끄려면 False)
NEWS_MODEL = "claude-haiku-4-5-20251001" # 뉴스 분석에 쓰는 Claude 모델 (저렴한 모델)
NEWS_MAX_ITEMS = 8                       # 종목당 읽을 뉴스 제목 수
NEWS_BLOCK_BUY_SCORE = -1                # 뉴스 점수가 이 값 이하이면 신규 매수 보류 (-2 큰 악재 ~ +2 큰 호재)
NEWS_WARN_HELD_SCORE = -2                # 보유 종목이 이 점수 이하이면 경고 알림 (자동 매도는 하지 않음)

# 변동성이 큰 종목(코스닥·나스닥): 손절선을 넓게 쓰는 전략 비교용
WIDE_STOP_CODES = KOSDAQ_CODES | {c for c in SYMBOLS if is_us(c)}
WIDE_STOP_PCT = -0.12
_load_watch()   # (WIDE_STOP_CODES 를 만든 뒤에 불러와야 관찰 종목이 매매 설정에 섞이지 않아요)

# 뉴스 분석 방식: "keyword"(무료, 단어 검색) / "claude"(API 사용, 유료) / "auto"(키가 있으면 Claude, 없으면 keyword)
NEWS_MODE = "keyword"

# 하락장 대응 옵션 (compare_down.py 로 비교한 뒤 켜세요. 기본은 꺼짐)
VOL_SIZE_RISK = None   # 예: 0.01 -> 종목당 예상 손실이 총자산의 1% 안팎이 되도록, 변동성이 큰 종목은 적게 매수
VOL_FLOOR = 0.05      # 변동성 크기 조절의 "최소 예상 손실 폭". 낮출수록(예: 0.025) 종목별 변동성 차이가 더 크게 반영됨
HIGHVOL_SCALE = None   # 예: 0.5 -> 코스닥·나스닥 종목은 투자 금액을 절반으로 (compare_gap.py 로 비교한 뒤 켜세요)
GAP_MODE = "skip"        # "skip": 갭이 잦은 종목은 신규 매수 안 함 / "half": 투자 금액을 절반으로 / None: 끔
GAP_THR = 0.07         # 전날 종가 대비 시가가 이 비율 이상 벌어진 날을 갭으로 셈
GAP_DAYS = 3           # 최근 120일 안에 갭이 이 횟수 이상이면 갭이 잦은 종목으로 봄
MAX_PER_SECTOR = None  # 예: 2 -> 같은 업종은 동시에 최대 2종목까지만 보유 (compare_sector.py 로 비교한 뒤 켜세요)
EARNINGS_AVOID_DAYS = None   # 예: 3 -> 실적 발표 3일 전부터는 새로 사지 않음 (미국 종목 위주, 날짜를 못 구하면 영향 없음. 백테스트로 검증 불가)
BREADTH_MIN = None     # 예: 0.3 -> 상승 추세 종목이 전체의 30% 미만이면 신규 매수 보류 (약세장 대응)


# --- 설정 자동 조정 (advisor.py) ---
TUNABLE = {   # 항목: (최소, 최대, 한 번에 바꿀 수 있는 최대 폭). 이 범위 밖의 값은 적용되지 않습니다.
    "STOP_LOSS_PCT": (-0.10, -0.04, 0.01),
    "TRAIL_STOP_PCT": (0.12, 0.30, 0.03),
    "MAX_POSITIONS": (3, 7, 1),
    "GAP_DAYS": (2, 5, 1),
}
ADVISOR_ENGINE = "auto"            # "claude"(API 사용, 유료) / "rules"(무료, 정해진 규칙) / "auto"(키가 있으면 claude, 없으면 rules)
ADVISOR_MODEL = "claude-sonnet-5-5"
ADVISOR_AUTO_APPLY = False         # True 로 바꾸면 제안을 승인 없이 바로 적용합니다 (권장하지 않음)
TUNABLE_DEFAULTS = {k: globals()[k] for k in TUNABLE}   # 조정하기 전의 기본값


def _apply_tuning():
    """data/tuning.json 에 승인된 조정값이 있으면 범위 안에서만 적용"""
    import json
    p = DATA_DIR / "tuning.json"
    if not p.exists():
        return
    try:
        data = json.load(open(p, encoding="utf-8"))
    except Exception:
        return
    for k, v in data.items():
        if k in TUNABLE and isinstance(v, (int, float)) and TUNABLE[k][0] <= v <= TUNABLE[k][1]:
            globals()[k] = int(v) if k in ("MAX_POSITIONS", "GAP_DAYS") else float(v)


_apply_tuning()
