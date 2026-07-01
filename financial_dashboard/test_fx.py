"""
환율 테스트 스크립트 (네이버 금융 기반 - requests만 사용, 브라우저 불필요)
CMD에서: python test_fx.py
"""
import requests
import urllib3
from bs4 import BeautifulSoup
import pandas as pd

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 설정 ──────────────────────────────────────────────────────────────────────
DATE = "20260630"   # 조회일 (YYYYMMDD) — 원하는 날짜로 변경
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com/marketindex/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

FX_CODES = {
    "달러(USD)": "FX_USDKRW",
    "위안(CNY)": "FX_CNYKRW",
    "엔(JPY)":   "FX_JPYKRW",
}

def fetch_naver_fx(market_code: str, target_date: str, max_pages: int = 10):
    """네이버 금융 일별 환율에서 target_date(YYYYMMDD) 값 찾기"""
    date_fmt = f"{target_date[:4]}.{target_date[4:6]}.{target_date[6:8]}"
    base_url = (
        "https://finance.naver.com/marketindex/exchangeDailyQuote.nhn"
        f"?marketindexCd={market_code}"
    )
    for page in range(1, max_pages + 1):
        url = base_url + f"&page={page}"
        r = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("table.tbl_exchange tbody tr")
        for row in rows:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cols:
                continue
            if cols[0] == date_fmt:
                try:
                    return float(cols[1].replace(",", ""))
                except Exception:
                    return None
        # 더 이상 과거 데이터가 없으면 중단
        last_els = soup.select("table.tbl_exchange tbody tr td:first-child")
        if last_els:
            last_date = last_els[-1].get_text(strip=True)
            if last_date and last_date < date_fmt:
                break
    return None

results = []
for name, code in FX_CODES.items():
    print(f"{name} 조회 중...")
    val = fetch_naver_fx(code, DATE)
    print(f"  → {val}")
    results.append({"통화": name, "값(원)": val})

df = pd.DataFrame(results).set_index("통화")
df["값(원)"] = pd.to_numeric(df["값(원)"], errors="coerce")

try:
    usd = df.loc["달러(USD)", "값(원)"]
    cny = df.loc["위안(CNY)", "값(원)"]
    jpy = df.loc["엔(JPY)",   "값(원)"]
    if pd.notna(usd) and pd.notna(cny) and cny != 0:
        df.loc["위안/달러", "값(원)"] = round(usd / cny, 4)
    if pd.notna(usd) and pd.notna(jpy) and jpy != 0:
        df.loc["엔/달러",   "값(원)"] = round(usd / (jpy / 100), 4)
except Exception as e:
    print(f"크로스 환율 계산 오류: {e}")

print("\n=== 최종 결과 ===")
print(df)
print("\n완료")
