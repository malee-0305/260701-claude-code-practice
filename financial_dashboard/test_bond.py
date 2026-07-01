"""
채권수익률 테스트 스크립트
CMD에서: python test_bond.py
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
import pandas as pd
import time

# ── 설정 ──────────────────────────────────────────────────────────────────────
CHROME_DRIVER = "chromedriver.exe"   # chromedriver.exe 위치
DATE = "20260630"                     # 조회일 (YYYYMMDD)
# ─────────────────────────────────────────────────────────────────────────────

opts = webdriver.ChromeOptions()
driver = webdriver.Chrome(service=Service(CHROME_DRIVER), options=opts)
wait   = WebDriverWait(driver, 40)

bond_cols = ['종류','종류명','신용등급','조회기준','3월','6월','9월','1년','1년6월',
             '2년','2년6월','3년','4년','5년','7년','10년','15년','20년','30년','50년']
cp_cols   = ['신용등급','구분','기관명','7일','15일','1월','3월','6월','1년']

def switch_to_main_frame():
    driver.switch_to.default_content()
    try:
        driver.switch_to.frame(driver.find_element(By.NAME, "fraAMAKMain"))
    except Exception:
        driver.switch_to.frame(driver.find_element(By.ID, "fraAMAKMain"))

def switch_to_nested():
    switch_to_main_frame()
    driver.switch_to.frame(driver.find_element(By.ID, "maincontent"))
    driver.switch_to.frame(driver.find_element(By.ID, "tabContents1_contents_tabs1_body"))
    time.sleep(3)

def dismiss_popup():
    try:
        WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="popup_ok"]'))).click()
        print("  팝업 닫기 완료")
    except Exception:
        print("  팝업 없음 (정상)")

def input_date():
    el = driver.find_element(By.XPATH, '//*[@id="srchDt_input"]')
    el.send_keys(Keys.BACKSPACE * len(el.get_attribute("value")))
    el.send_keys(DATE)
    print(f"  날짜 입력: {DATE}")

def click_all_cb():
    for i in range(1, 5):
        try:
            driver.find_element(By.XPATH, f'//*[@id="checkbox{i}_input_0"]').click()
            time.sleep(0.2)
        except Exception: pass
    print("  체크박스 선택 완료")

def click_search():
    driver.find_element(By.XPATH, '//*[@id="image1"]').click()
    print("  조회 버튼 클릭 - 7초 대기...")
    time.sleep(7)

def parse_grid(cols):
    soup  = BeautifulSoup(driver.page_source, "html.parser")
    d     = soup.find("div", id="grdMain_dataLayer")
    if not d:
        print("  [경고] grdMain_dataLayer 없음")
        return pd.DataFrame(columns=cols)
    t     = d.find("table", id="grdMain_body_table")
    if not t:
        print("  [경고] grdMain_body_table 없음")
        return pd.DataFrame(columns=cols)
    tb    = t.find("tbody", id="grdMain_body_tbody")
    if not tb:
        print("  [경고] grdMain_body_tbody 없음")
        return pd.DataFrame(columns=cols)
    data  = [[c.get_text(strip=True) for c in r.find_all("td")] for r in tb.find_all("tr")]
    if not data:
        print("  [경고] 행 없음")
        return pd.DataFrame(columns=cols)
    print(f"  행 수: {len(data)}, 첫 행 열 수: {len(data[0])}")
    fixed = []
    for row in data:
        if len(row) > len(cols):  row = row[:len(cols)]
        elif len(row) < len(cols): row = row + [""] * (len(cols) - len(row))
        fixed.append(row)
    return pd.DataFrame(fixed, columns=cols)

try:
    print("=== 채권정보센터 접속 ===")
    driver.get("https://www.kofiabond.or.kr/")
    time.sleep(10)

    print("\n[1단계] 채권수익률 메뉴 클릭 (image6)")
    switch_to_main_frame()
    driver.find_element(By.XPATH, '//*[@id="image6"]').click()
    time.sleep(10)
    print("  완료")

    print("\n[2단계] 국고채/회사채 조회")
    switch_to_nested()
    dismiss_popup()
    input_date()
    click_all_cb()
    click_search()
    kb_df1 = parse_grid(bond_cols)
    print(f"  kb_df1 shape: {kb_df1.shape}")
    print(kb_df1.head(3))

    print("\n[3단계] CP 메뉴 클릭")
    switch_to_main_frame()
    driver.find_element(By.XPATH, '//*[@id="leftGenLv1_1_leftGrpLv1Li"]').click()
    time.sleep(5)
    print("  완료")

    print("\n[4단계] CP 조회")
    switch_to_nested()
    dismiss_popup()
    input_date()
    click_all_cb()
    click_search()
    kb_df2 = parse_grid(cp_cols)
    print(f"  kb_df2 shape: {kb_df2.shape}")
    print(kb_df2.head(3))

    print("\n[5단계] CD 메뉴 클릭")
    switch_to_main_frame()
    driver.find_element(By.XPATH, '//*[@id="leftGenLv1_2_leftGrpLv1A"]').click()
    time.sleep(5)
    print("  완료")

    print("\n[6단계] CD 조회")
    switch_to_nested()
    dismiss_popup()
    input_date()
    click_all_cb()
    click_search()
    kb_df3 = parse_grid(cp_cols)
    print(f"  kb_df3 shape: {kb_df3.shape}")
    print(kb_df3.head(3))

    def sf(df, r, c):
        try: return float(str(df.iloc[r, c]).replace(",", ""))
        except: return None

    print("\n=== 최종 결과 ===")
    summary = {
        "국고채 3년":    sf(kb_df1, 0, 11),
        "국고채 5년":    sf(kb_df1, 0, 13),
        "국고채 10년":   sf(kb_df1, 0, 15),
        "회사채 AAA(3y)":sf(kb_df1, 28, 11),
        "CD(91일)":      sf(kb_df3, 5, 6),
        "CP(91일)":      sf(kb_df2, 5, 6),
    }
    for k, v in summary.items():
        print(f"  {k}: {v}")

finally:
    input("\n브라우저를 확인하려면 Enter 키를 누르세요...")
    driver.quit()
    print("완료")
