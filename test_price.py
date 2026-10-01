import FinanceDataReader as fdr

# 삼성전자(005930) 최근 일봉 조회
df = fdr.DataReader("005930", "2025-01-01")

print("최근 5일 시세")
print(df.tail(5))
print()
print("마지막 종가:", int(df["Close"].iloc[-1]), "원")