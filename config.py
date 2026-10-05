from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# 매매할 종목 (코드: 이름)
SYMBOLS = {
    # 코스피
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "005380": "현대차",
    "105560": "KB금융",
    # 코스닥
    "247540": "에코프로비엠",
    "196170": "알테오젠",
    "263750": "펄어비스",
    # 나스닥 (영문 티커로 입력하면 미국 종목으로 인식, 달러 시세를 원화로 환산)
    "NVDA": "엔비디아",
    "AAPL": "애플",
    "MSFT": "마이크로소프트",
}

# 가상 시작 자금 (원)
INITIAL_CASH = 10_000_000

# 비용 설정
FEE_RATE = 0.00015      # 수수료 (매수/매도 각각) 0.015%
SELL_TAX_RATE = 0.002   # 매도 거래세 약 0.2% (세율은 바뀔 수 있으니 확인 후 조정)
SLIPPAGE_RATE = 0.001   # 체결가를 불리하게 가정 0.1%
US_FEE_RATE = 0.0025    # 미국 주식 수수료 0.25% (증권사마다 다름, 매수/매도 각각)
# 미국 주식은 매도 거래세가 없지만, 연간 양도소득세(수익의 22%, 연 250만 원 공제)는 반영하지 않았습니다.

MAX_POSITIONS = 5       # 동시에 보유할 최대 종목 수. 종목당 투자 한도 = 총자산 ÷ 이 값


def is_us(code):
    return code.isalpha()


def fee_rate(code):
    return US_FEE_RATE if is_us(code) else FEE_RATE


def sell_tax_rate(code):
    return 0.0 if is_us(code) else SELL_TAX_RATE

# 전략 설정
SHORT_MA = 20           # 단기 이동평균 (일)
LONG_MA = 120           # 장기 이동평균 (일)
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
WIDE_STOP_CODES = {"247540", "196170", "263750", "NVDA", "AAPL", "MSFT"}
WIDE_STOP_PCT = -0.12

# 뉴스 분석 방식: "keyword"(무료, 단어 검색) / "claude"(API 사용, 유료) / "auto"(키가 있으면 Claude, 없으면 keyword)
NEWS_MODE = "keyword"
