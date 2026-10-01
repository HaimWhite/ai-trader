from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# 매매할 종목 (코드: 이름)
SYMBOLS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
}

# 가상 시작 자금 (원)
INITIAL_CASH = 10_000_000

# 비용 설정
FEE_RATE = 0.00015      # 수수료 (매수/매도 각각) 0.015%
SELL_TAX_RATE = 0.002   # 매도 거래세 약 0.2% (세율은 바뀔 수 있으니 확인 후 조정)
SLIPPAGE_RATE = 0.001   # 체결가를 불리하게 가정 0.1%

# 전략 설정
SHORT_MA = 5            # 단기 이동평균 (일)
LONG_MA = 20            # 장기 이동평균 (일)
STOP_LOSS_PCT = -0.07   # 매입가 대비 -7% 이하이면 손절

# 백테스트 설정
BACKTEST_START = "2021-01-01"   # 백테스트 시작일
