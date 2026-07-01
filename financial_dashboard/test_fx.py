"""
환율 테스트 스크립트
CMD에서: python test_fx.py
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
import pandas as pd
import time

# ── 설정 ──────────────────────────────────────────────────────────────────────
CHROME_DRIVER = "chromedriver.exe"   # chromedriver.exe 위치 (같은 폴더면 그대로)
DATE = "20260630"                     # 조회일 (YYYYMMDD)
# ─────────────────────────────────────────────────────────────────────────────

def set_value_force(driver, el, value):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        el.click()
        el.send_keys(Keys.CONTROL, "a")
        el.send_keys(Keys.DELETE)
        el.send_keys(value)
    except Exception:
        driver.execute_script(
            "var el=arguments[0],val=arguments[1];"
            "el.value=val;"
            "el.dispatchEvent(new Event('input',{bubbles:true}));"
            "el.dispatchEvent(new Event('change',{bubbles:true}));",
            el, value)

opts = webdriver.ChromeOptions()
opts.add_argument("--start-maximized")

driver = webdriver.Chrome(service=Service(CHROME_DRIVER), options=opts)
wait   = WebDriverWait(driver, 25)

select_xpath = '//*[@id="frm_SearchDate"]/div[1]/table/tbody/tr[1]/td/select'
search_xpath = '//*[@id="frm_SearchDate"]/p[2]/a[2]/img'
rate_xpath   = '//*[@id="frm_SearchDate"]/div[6]/table/tbody/tr/td[1]'

currencies = [("달러(USD)", 0), ("위안(CNY)", 1), ("엔(JPY)", 3)]
results = []

try:
    driver.get("http://www.smbs.biz/ExRate/StdExRate.jsp")
    time.sleep(3)

    start_box = wait.until(EC.element_to_be_clickable((By.ID, "startDate")))
    end_box   = wait.until(EC.element_to_be_clickable((By.ID, "endDate")))
    set_value_force(driver, start_box, DATE)
    set_value_force(driver, end_box,   DATE)
    print(f"날짜 입력 완료: {DATE}")

    for currency, option_index in currencies:
        try:
            sel_el = wait.until(EC.element_to_be_clickable((By.XPATH, select_xpath)))
            Select(sel_el).select_by_index(option_index)

            search_btn = wait.until(EC.element_to_be_clickable((By.XPATH, search_xpath)))
            driver.execute_script("arguments[0].click();", search_btn)
            time.sleep(2)

            rate_cell = wait.until(EC.presence_of_element_located((By.XPATH, rate_xpath)))
            txt = rate_cell.text.strip().replace(",", "")
            val = float(txt) if txt else None
            print(f"  {currency}: {val}")
        except Exception as e:
            print(f"  {currency} 실패: {e}")
            val = None
        results.append({"통화": currency, "값(원)": val})

    df = pd.DataFrame(results).set_index("통화")
    df["값(원)"] = pd.to_numeric(df["값(원)"], errors="coerce")

    usd = df.loc["달러(USD)", "값(원)"]
    cny = df.loc["위안(CNY)", "값(원)"]
    jpy = df.loc["엔(JPY)",   "값(원)"]
    if pd.notna(usd) and pd.notna(cny) and cny != 0:
        df.loc["위안/달러", "값(원)"] = round(usd / cny, 4)
    if pd.notna(usd) and pd.notna(jpy) and jpy != 0:
        df.loc["엔/달러",   "값(원)"] = round(usd / (jpy / 100), 4)

    print("\n=== 최종 결과 ===")
    print(df)

finally:
    input("\n브라우저를 확인하려면 Enter 키를 누르세요...")
    driver.quit()
    print("완료")
