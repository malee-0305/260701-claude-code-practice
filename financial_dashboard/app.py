import os, time, threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CHROME_BINARY  = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
CHROME_DRIVER  = "/tmp/147.0.7727.24/chromedriver/chromedriver-linux64/chromedriver"

# ── Selenium 공통 드라이버 팩토리 ─────────────────────────────────────────
def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    opts = webdriver.ChromeOptions()
    opts.binary_location = CHROME_BINARY
    for arg in ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--window-size=1920,1080",
                "--disable-blink-features=AutomationControlled"]:
        opts.add_argument(arg)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    svc = Service(CHROME_DRIVER)
    return webdriver.Chrome(service=svc, options=opts)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Investing.com  (requests + BeautifulSoup)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_investing(date: str):
    import requests
    from bs4 import BeautifulSoup
    import urllib3, pandas as pd
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    date_format2 = date[:4] + "년 " + date[4:6] + "월 " + date[6:8] + "일"

    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/122.0.0.0 Safari/537.36"),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://kr.investing.com/"
    })

    def fetch_row(url, cls1, cls2, label):
        try:
            r = session.get(url, verify=False, timeout=20)
            if r.status_code != 200:
                return None
            soup = BeautifulSoup(r.text, "html.parser")
            table = soup.find("table", class_=cls1) or soup.find("table", class_=cls2)
            if not table:
                return None
            tbody = table.find("tbody")
            if not tbody:
                return None
            for row in tbody.find_all("tr"):
                cols = [c.get_text(strip=True) for c in row.find_all("td")]
                if cols and cols[0] == date_format2:
                    return [label] + cols
        except Exception as e:
            print(f"[investing] {label}: {e}")
        return None

    CLS1 = "freeze-column-w-1 w-full overflow-x-auto text-xs leading-4"
    CLS2 = "genTbl closedTbl historicalTbl"

    assets = [
        ("https://kr.investing.com/commodities/crude-oil-historical-data",          CLS1, CLS2, "WTI"),
        ("https://kr.investing.com/currencies/us-dollar-index-historical-data",     CLS2, CLS2, "달러인덱스(DXI)"),
        ("https://kr.investing.com/rates-bonds/u.s.-2-year-bond-yield-historical-data",  CLS1, CLS2, "미국채2년"),
        ("https://kr.investing.com/rates-bonds/u.s.-5-year-bond-yield-historical-data",  CLS1, CLS2, "미국채5년"),
        ("https://kr.investing.com/rates-bonds/u.s.-10-year-bond-yield-historical-data", CLS1, CLS2, "미국채10년"),
        ("https://kr.investing.com/rates-bonds/japan-3-year-bond-yield-historical-data", CLS1, CLS2, "일본국채3년"),
        ("https://kr.investing.com/rates-bonds/japan-5-year-bond-yield-historical-data", CLS1, CLS2, "일본국채5년"),
        ("https://kr.investing.com/rates-bonds/japan-10-year-bond-yield-historical-data",CLS1, CLS2, "일본국채10년"),
        ("https://kr.investing.com/rates-bonds/germany-10-year-bond-yield-historical-data",CLS1,CLS2,"독일국채10년"),
        ("https://kr.investing.com/rates-bonds/brazil-3-year-bond-yield-historical-data", CLS1,CLS2,"브라질국채3년"),
        ("https://kr.investing.com/rates-bonds/brazil-5-year-bond-yield-historical-data", CLS1,CLS2,"브라질국채5년"),
        ("https://kr.investing.com/rates-bonds/brazil-10-year-bond-yield-historical-data",CLS1,CLS2,"브라질국채10년"),
    ]

    rows = []
    for url, c1, c2, label in assets:
        row = fetch_row(url, c1, c2, label)
        if row:
            rows.append(row)

    index_tickers = [
        ("indices",  "kospi",                      "KOSPI"),
        ("equities", "samsung-electronics-co-ltd", "삼성전자"),
        ("indices",  "kospi-large-sized",           "KOSPI대형"),
        ("indices",  "kospi-medium-sized",          "KOSPI중형"),
        ("indices",  "kospi-small-sized",           "KOSPI소형"),
        ("indices",  "kosdaq",                      "KOSDAQ"),
        ("indices",  "us-spx-500",                  "S&P500"),
        ("indices",  "nasdaq-composite",            "NASDAQ"),
        ("indices",  "eu-stoxx50",                  "EUROSTOXX50"),
        ("indices",  "japan-ni225",                 "니케이225"),
        ("indices",  "csi300",                      "CSI300"),
        ("indices",  "hang-seng-china-enterprises", "항셍차이나"),
        ("indices",  "sensex",                      "SENSEX"),
        ("indices",  "vn",                          "VN지수"),
        ("indices",  "idx-composite",               "IDX"),
        ("indices",  "msci-world-stock",            "MSCI World"),
    ]

    for typ, ticker, label in index_tickers:
        url = f"https://kr.investing.com/{typ}/{ticker}-historical-data"
        row = fetch_row(url, CLS1, CLS2, label)
        if row:
            rows.append(row)

    if not rows:
        return None, "데이터를 찾을 수 없습니다 (날짜 확인 필요)"

    import pandas as pd
    # 컬럼 수 통일
    max_c = max(len(r) for r in rows)
    padded = [r + [""] * (max_c - len(r)) for r in rows]
    cols = ["지표", "날짜", "종가", "시가", "고가", "저가"] + \
           (["거래량"] if max_c >= 8 else []) + ["등락률"] + \
           [""] * max(0, max_c - (8 if max_c >= 8 else 7) - 1)
    cols = cols[:max_c]
    df = pd.DataFrame(padded, columns=cols)
    df = df.set_index("지표")
    return df, None


# ══════════════════════════════════════════════════════════════════════════════
# 2. 환율 (SMBS)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_fx(date: str):
    import pandas as pd
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    def set_val(driver, el, val):
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            el.click()
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.DELETE)
            el.send_keys(val)
        except Exception:
            driver.execute_script(
                "const e=arguments[0],v=arguments[1];e.value=v;"
                "e.dispatchEvent(new Event('input',{bubbles:true}));"
                "e.dispatchEvent(new Event('change',{bubbles:true}));", el, val)

    driver = make_driver()
    wait   = WebDriverWait(driver, 25)
    results = []

    try:
        driver.get("http://www.smbs.biz/ExRate/StdExRate.jsp")
        start_box = wait.until(EC.element_to_be_clickable((By.ID, "startDate")))
        end_box   = wait.until(EC.element_to_be_clickable((By.ID, "endDate")))
        set_val(driver, start_box, date)
        set_val(driver, end_box,   date)

        select_xpath = '//*[@id="frm_SearchDate"]/div[1]/table/tbody/tr[1]/td/select'
        search_xpath = '//*[@id="frm_SearchDate"]/p[2]/a[2]/img'
        rate_xpath   = '//*[@id="frm_SearchDate"]/div[6]/table/tbody/tr/td[1]'

        for currency, idx in [("달러", 0), ("위안화", 1), ("엔화", 3)]:
            try:
                sel_el = wait.until(EC.element_to_be_clickable((By.XPATH, select_xpath)))
                Select(sel_el).select_by_index(idx)
                btn = wait.until(EC.element_to_be_clickable((By.XPATH, search_xpath)))
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1.5)
                cell = wait.until(EC.presence_of_element_located((By.XPATH, rate_xpath)))
                txt  = cell.text.strip().replace(",", "")
                val  = float(txt) if txt else None
            except Exception as e:
                print(f"[fx] {currency}: {e}")
                val = None
            results.append([currency, val])

        df = pd.DataFrame(results, columns=["통화", "값(원)"]).set_index("통화")
        df["값(원)"] = pd.to_numeric(df["값(원)"], errors="coerce")

        usd = df.loc["달러",  "값(원)"]
        cny = df.loc["위안화","값(원)"]
        jpy = df.loc["엔화",  "값(원)"]
        if pd.notna(usd) and pd.notna(cny) and cny != 0:
            df.loc["위안/달러", "값(원)"] = round(usd / cny, 4)
        if pd.notna(usd) and pd.notna(jpy) and jpy != 0:
            df.loc["엔/달러",   "값(원)"] = round(usd / (jpy / 100), 4)

        return df, None
    except Exception as e:
        return None, str(e)
    finally:
        driver.quit()


# ══════════════════════════════════════════════════════════════════════════════
# 3. 채권정보센터
# ══════════════════════════════════════════════════════════════════════════════
def fetch_bond(date: str):
    import pandas as pd
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    driver = make_driver()
    wait   = WebDriverWait(driver, 30)

    def switch_nested(fid1, fid2):
        driver.switch_to.default_content()
        driver.switch_to.frame(driver.find_element(By.NAME, fid1))
        driver.switch_to.frame(driver.find_element(By.ID, fid2))

    def dismiss_popup():
        try:
            btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="popup_ok"]')))
            btn.click()
        except Exception:
            pass

    def type_date(xpath):
        box = driver.find_element(By.XPATH, xpath)
        box.send_keys(Keys.BACKSPACE * len(box.get_attribute("value") or ""))
        box.send_keys(date)

    def check_all():
        for i in range(1, 5):
            try:
                driver.find_element(By.XPATH, f'//*[@id="checkbox{i}_input_0"]').click()
            except Exception:
                pass

    def click_search():
        driver.find_element(By.XPATH, '//*[@id="image1"]').click()
        time.sleep(5)

    def parse_table(div_id, tbl_id, tbody_id, cols):
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        div  = soup.find("div", id=div_id)
        if not div:
            return pd.DataFrame(columns=cols)
        tbl  = div.find("table", id=tbl_id)
        if not tbl:
            return pd.DataFrame(columns=cols)
        rows = tbl.find("tbody", id=tbody_id).find_all("tr")
        data = [[c.get_text(strip=True) for c in r.find_all("td")] for r in rows]
        return pd.DataFrame(data, columns=cols)

    try:
        driver.get("https://www.kofiabond.or.kr/")
        time.sleep(8)

        driver.switch_to.frame(driver.find_element(By.NAME, "fraAMAKMain"))
        driver.find_element(By.XPATH, '//*[@id="image6"]').click()
        time.sleep(8)

        # 국고채/회사채/금융채
        driver.switch_to.frame(driver.find_element(By.ID, "maincontent"))
        driver.switch_to.frame(driver.find_element(By.ID, "tabContents1_contents_tabs1_body"))
        time.sleep(6)
        dismiss_popup()
        type_date('//*[@id="srchDt_input"]')
        check_all()
        click_search()

        bond_cols = ['종류','종류명','신용등급','조회기준','3월','6월','9월','1년','1년6월',
                     '2년','2년6월','3년','4년','5년','7년','10년','15년','20년','30년','50년']
        kb_df1 = parse_table("grdMain_dataLayer","grdMain_body_table","grdMain_body_tbody", bond_cols)

        # CP
        switch_nested("fraAMAKMain", "maincontent")
        driver.switch_to.frame(driver.find_element(By.ID, "tabContents1_contents_tabs1_body"))
        driver.find_element(By.XPATH, '//*[@id="leftGenLv1_1_leftGrpLv1Li"]').click()
        time.sleep(6)
        dismiss_popup()
        type_date('//*[@id="srchDt_input"]')
        check_all()
        click_search()

        cp_cols = ['신용등급','구분','기관명','7일','15일','1월','3월','6월','1년']
        kb_df2  = parse_table("grdMain_dataLayer","grdMain_body_table","grdMain_body_tbody", cp_cols)

        # CD
        switch_nested("fraAMAKMain", "maincontent")
        driver.switch_to.frame(driver.find_element(By.ID, "tabContents1_contents_tabs1_body"))
        driver.find_element(By.XPATH, '//*[@id="leftGenLv1_2_leftGrpLv1A"]').click()
        time.sleep(6)
        dismiss_popup()
        type_date('//*[@id="srchDt_input"]')
        check_all()
        click_search()

        kb_df3 = parse_table("grdMain_dataLayer","grdMain_body_table","grdMain_body_tbody", cp_cols)

        # 요약
        def safe_float(df, row, col):
            try:
                return float(df.iloc[row, col])
            except Exception:
                return None

        gov_3y   = safe_float(kb_df1, 0, 11)
        gov_5y   = safe_float(kb_df1, 0, 13)
        gov_10y  = safe_float(kb_df1, 0, 15)
        corp_AAA = safe_float(kb_df1, 28, 11)
        corp_AAp = safe_float(kb_df1, 29, 11)
        corp_AA  = safe_float(kb_df1, 30, 11)
        corp_AAm = safe_float(kb_df1, 31, 11)
        corp_Ap  = safe_float(kb_df1, 32, 11)
        corp_A   = safe_float(kb_df1, 33, 11)
        corp_Am  = safe_float(kb_df1, 34, 11)
        corp_BBBp= safe_float(kb_df1, 35, 11)
        fin_AAm  = safe_float(kb_df1, 19, 11)
        fin_Ap   = safe_float(kb_df1, 20, 11)
        fin_A    = safe_float(kb_df1, 21, 11)
        fin_Am   = safe_float(kb_df1, 22, 11)
        cp_val   = safe_float(kb_df2,  5,  6)
        cd_val   = safe_float(kb_df3,  5,  6)

        summary = {
            "국고채 3년": gov_3y, "국고채 5년": gov_5y, "국고채 10년": gov_10y,
            "회사채 AAA(3y)": corp_AAA, "회사채 AA+(3y)": corp_AAp,
            "회사채 AA0(3y)": corp_AA,  "회사채 AA-(3y)": corp_AAm,
            "회사채 A+(3y)":  corp_Ap,  "회사채 A0(3y)":  corp_A,
            "회사채 A-(3y)":  corp_Am,  "회사채 BBB+(3y)":corp_BBBp,
            "금융채 AA-(3y)": fin_AAm,  "금융채 A+(3y)":  fin_Ap,
            "금융채 A0(3y)":  fin_A,    "금융채 A-(3y)":  fin_Am,
            "CD(91일)": cd_val, "CP(91일)": cp_val,
        }
        import pandas as pd
        df = pd.DataFrame(list(summary.items()), columns=["종목", "수익률(%)"])
        df = df.set_index("종목")
        return df, None

    except Exception as e:
        return None, str(e)
    finally:
        driver.quit()


# ══════════════════════════════════════════════════════════════════════════════
# 4. 콜금리 (ECOS BOK)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_call_rate(date: str):
    import pandas as pd
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = make_driver()
    wait   = WebDriverWait(driver, 30)

    try:
        driver.get("https://ecos.bok.or.kr/#/SearchStat")
        time.sleep(6)

        steps = [
            '//*[@id="root"]/div[4]/div/div[2]/div[2]/ul/li[1]/div/a',
            '//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[1]/td/div[1]/span[2]',
            '//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[4]/td/div[1]',
            '//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[6]/td/div[1]/span[2]',
            '//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[7]/td/div[1]/span[2]',
        ]
        for xpath in steps:
            try:
                el = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                el.click()
                time.sleep(2)
            except Exception as e:
                print(f"[call_rate] step: {e}")

        try:
            wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="allCheckDiv0"]/label'))).click()
            time.sleep(2)
            wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="1"]/div/div[1]/div/div[1]/div[5]/div[1]/table/tbody/tr[2]/td/div/span'))).click()
            time.sleep(2)
            wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="centerDiv"]/div/div/div/div[2]/div/div[2]/div/div[3]/div/button[2]'))).click()
            time.sleep(2)
            wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="centerDiv"]/div/div/div/div[3]/div/div[2]/div/div/div[3]/div/button'))).click()
            time.sleep(2)
            wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="centerDiv"]/div/div[2]/div/div/div/div/div/div[1]/div[2]/div/button[3]'))).click()
            time.sleep(2)
        except Exception as e:
            print(f"[call_rate] nav: {e}")

        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        chart = soup.find("div", class_="chartBox")
        if not chart:
            return None, "콜금리 데이터 파싱 실패"

        body_div = chart.find("div", class_="rg-body")
        tbl1 = body_div.find("table", class_="rg-table") if body_div else None
        head_div = soup.find("div", class_="rg-header")
        tbl2 = head_div.find("table", class_="rg-table") if head_div else None

        if not tbl1 or not tbl2:
            return None, "콜금리 테이블 파싱 실패"

        data_rows = [[c.find("div", class_="rg-renderer").get_text(strip=True)
                      for c in r.find_all("td")] for r in tbl1.find("tbody").find_all("tr")]
        head_rows = [[c.get_text(strip=True) for c in r.find_all("td")]
                     for r in tbl2.find("tbody").find_all("tr")]

        df = pd.DataFrame(data_rows, columns=head_rows)
        df.insert(0, "", "콜금리")
        df = df.set_index(df.columns[0])
        return df, None

    except Exception as e:
        return None, str(e)
    finally:
        driver.quit()


# ══════════════════════════════════════════════════════════════════════════════
# 5. KRX
# ══════════════════════════════════════════════════════════════════════════════
def fetch_krx(date: str):
    import pandas as pd
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys
    from datetime import datetime, timedelta

    def wait_presence(wait, by, sel):
        return wait.until(EC.presence_of_element_located((by, sel)))

    def wait_click(wait, by, sel):
        el = wait.until(EC.element_to_be_clickable((by, sel)))
        el.click()
        return el

    def clear_type(el, txt):
        el.send_keys(Keys.CONTROL + "a")
        el.send_keys(Keys.DELETE)
        el.send_keys(txt)

    def wait_ready(driver, sec=30):
        WebDriverWait(driver, sec).until(
            lambda d: d.execute_script("return document.readyState") == "complete")

    def open_mdi(driver, wait, menu_id):
        driver.get(f"https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId={menu_id}")
        wait_ready(driver, 40)
        wait_presence(wait, By.ID, "jsMdiMenu")

    def to_float(x):
        try:
            s = str(x).replace(",","").strip()
            return 0.0 if s in ("","nan","none","-") else float(s)
        except:
            return 0.0

    def parse_simple(html, table_id, cols):
        soup = BeautifulSoup(html, "html.parser")
        tbl  = soup.find("table", {"id": table_id})
        if not tbl:
            return pd.DataFrame(columns=cols)
        rows = tbl.find("tbody").find_all("tr") if tbl.find("tbody") else []
        data = [[c.get_text(strip=True).replace(",","") for c in r.find_all("td")] for r in rows]
        data = [r for r in data if not (len(r)==1 and "조회된 데이터가 없습니다" in r[0])]
        return pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)

    def parse_grid(html):
        soup  = BeautifulSoup(html, "html.parser")
        outer = soup.find("div", class_="CI-GRID-WRAPPER") or soup.find("div", class_="CI-GRID-AREA")
        if not outer:
            return []
        tbl = outer.find("table", class_="CI-GRID-BODY-TABLE")
        if not tbl:
            return []
        rows = tbl.find("tbody").find_all("tr") if tbl.find("tbody") else []
        return [[c.get_text(strip=True).replace(",","") for c in r.find_all("td")] for r in rows]

    def wait_table_rows(driver, css, timeout=60, min_rows=1):
        end = time.time() + timeout
        while time.time() < end:
            html = driver.page_source
            if "조회된 데이터가 없습니다" in html:
                return False, True
            from bs4 import BeautifulSoup as BS
            soup = BS(html, "html.parser")
            tbl  = soup.select_one(css)
            if tbl:
                tbody = tbl.find("tbody")
                if tbody:
                    rows = [r for r in tbody.find_all("tr")
                            if "조회된 데이터가 없습니다" not in r.get_text(strip=True)]
                    if len(rows) >= min_rows:
                        return True, False
            time.sleep(0.4)
        return False, False

    def prev_day(d, n=1):
        dt = datetime.strptime(d, "%Y%m%d") - timedelta(days=n)
        return dt.strftime("%Y%m%d")

    def ensure_date(driver, wait, date_xpath, btn_xpath, css, d, max_back=10):
        for _ in range(max_back + 1):
            box = wait_presence(wait, By.XPATH, date_xpath)
            clear_type(box, d)
            wait_click(wait, By.XPATH, btn_xpath)
            ok, nodata = wait_table_rows(driver, css)
            if ok:
                return d
            if nodata:
                d = prev_day(d)
        raise RuntimeError(f"데이터 없음 (최대 {max_back}일 소급 조회)")

    def pick_first(df, label_col, candidates, val_col):
        s = df[label_col].astype(str).str.strip()
        for k in candidates:
            hit = df[s.str.contains(k, na=False)]
            if not hit.empty:
                return to_float(hit.iloc[0][val_col])
        raise RuntimeError(f"라벨 매칭 실패: {candidates}")

    def grid_sum(df, label):
        hit = df[df["투자자구분"].astype(str).str.contains(label, na=False)]
        if hit.empty:
            raise RuntimeError(f"'{label}' 행 없음")
        row = hit.iloc[0]
        return to_float(row["거래대금(매도)"]) + to_float(row["거래대금(매수)"])

    driver = make_driver()
    wait   = WebDriverWait(driver, 40)

    # KRX는 로그인 없이 접근 시도
    driver.get("https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd")
    wait_ready(driver, 30)

    try:
        # 1) 시총
        open_mdi(driver, wait, "MDC0301")
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[2]/a')
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[2]/ul/li[1]/a')

        actual_date = ensure_date(
            driver, wait,
            '//*[@id="trdDd"]', '//*[@id="jsSearchButton"]',
            'table#jsTable_MDCEASY002_0', date
        )

        krx_df1 = parse_simple(driver.page_source, "jsTable_MDCEASY002_0",
                                ["구분","회사수","종목수","상장주식수","자본금","시가총액"])

        # 2) ETP 시총
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[3]/a')
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[3]/ul/li[1]/a')

        ensure_date(driver, wait, '//*[@id="trdDd"]', '//*[@id="jsSearchButton"]',
                    'table#jsTable_MDCEASY007_0', actual_date)
        krx_df2 = parse_simple(driver.page_source, "jsTable_MDCEASY007_0",
                                ["구분","운용사수","종목수","상장좌수","시가총액","순자산총액"])

        # 3) 주식 거래대금
        date1 = (datetime.strptime(actual_date, "%Y%m%d") - timedelta(days=28)).strftime("%Y%m%d")
        date2 = actual_date

        open_mdi(driver, wait, "MDC0201")
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[2]/a')
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[2]/ul/li[3]/a')
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[2]/ul/li[3]/ul/li[1]/a')

        wait_click(wait, By.XPATH, '//*[@id="MDCSTAT022_FORM"]/div[1]/div/table/tbody/tr[3]/td/label[1]')
        wait_click(wait, By.XPATH, '//*[@id="MDCSTAT022_FORM"]/div[1]/div/table/tbody/tr[3]/td/label[2]')

        strt = wait_presence(wait, By.XPATH, '//*[@id="strtDd"]')
        endd = wait_presence(wait, By.XPATH, '//*[@id="endDd"]')
        clear_type(strt, date1)
        clear_type(endd, date2)
        wait_click(wait, By.XPATH, '//*[@id="jsSearchButton"]')
        wait_presence(wait, By.CSS_SELECTOR, 'div.CI-GRID-WRAPPER, div.CI-GRID-AREA')
        wait_table_rows(driver, "table.CI-GRID-BODY-TABLE", timeout=80, min_rows=2)

        gc3 = ["투자자구분","거래량(매도)","거래량(매수)","거래량(순매수)","거래대금(매도)","거래대금(매수)","거래대금(순매수)"]
        krx_df3 = pd.DataFrame(parse_grid(driver.page_source), columns=gc3)

        # 4) ETF 거래대금
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[3]/a')
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[3]/ul/li[1]/a')
        wait_click(wait, By.XPATH, '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[3]/ul/li[1]/ul/li[6]/a')

        strt2 = wait_presence(wait, By.XPATH, '//*[@id="strtDd"]')
        endd2 = wait_presence(wait, By.XPATH, '//*[@id="endDd"]')
        clear_type(strt2, date1)
        clear_type(endd2, date2)
        wait_click(wait, By.XPATH, '//*[@id="jsSearchButton"]')
        wait_presence(wait, By.CSS_SELECTOR, 'div.CI-GRID-WRAPPER, div.CI-GRID-AREA')
        wait_table_rows(driver, "table.CI-GRID-BODY-TABLE", timeout=80, min_rows=2)

        krx_df4 = pd.DataFrame(parse_grid(driver.page_source), columns=gc3)

        # 5) 요약
        kospi_mc  = pick_first(krx_df1, "구분", ["유가증권시장","KOSPI","코스피"], "시가총액") / 1e6
        kosdaq_mc = pick_first(krx_df1, "구분", ["코스닥시장","KOSDAQ","코스닥"],  "시가총액") / 1e6
        konex_mc  = pick_first(krx_df1, "구분", ["코넥스시장","KONEX","코넥스"],   "시가총액") / 1e6
        etf_mc    = pick_first(krx_df2, "구분", ["ETF"], "시가총액") / 1e6
        etn_mc    = pick_first(krx_df2, "구분", ["ETN"], "시가총액") / 1e6

        rows_out = [
            {"구분": "시가총액(조원)",      "코스피": kospi_mc,  "코스닥": kosdaq_mc, "코넥스": konex_mc, "ETF": etf_mc, "ETN": etn_mc},
            {"구분": "전체거래대금(조원)",   "전체": grid_sum(krx_df3,"전체")/1e6, "개인": grid_sum(krx_df3,"개인")/1e6, "기관": grid_sum(krx_df3,"기관")/1e6, "외국인": grid_sum(krx_df3,"외국인")/1e6},
            {"구분": "ETF거래대금(조원)",    "전체": grid_sum(krx_df4,"전체")/1e12,"개인": grid_sum(krx_df4,"개인")/1e12,"기관": grid_sum(krx_df4,"기관")/1e12,"외국인": grid_sum(krx_df4,"외국인")/1e12},
        ]
        df_final = pd.DataFrame(rows_out).set_index("구분")
        return df_final, None, actual_date

    except Exception as e:
        return None, str(e), date
    finally:
        driver.quit()


# ══════════════════════════════════════════════════════════════════════════════
# Flask 라우트
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    data = request.get_json()
    date = data.get("date", "").replace("-", "")
    if len(date) != 8 or not date.isdigit():
        return jsonify({"error": "날짜 형식 오류 (YYYYMMDD)"}), 400

    results = {}
    errors  = {}

    # ── Investing.com (requests, 빠름) ──────────────────────────────────────
    try:
        df, err = fetch_investing(date)
        if err:
            errors["investing"] = err
        else:
            results["investing"] = df.to_html(classes="data-table", border=0, na_rep="-")
    except Exception as e:
        errors["investing"] = str(e)

    # ── 환율 ────────────────────────────────────────────────────────────────
    try:
        df, err = fetch_fx(date)
        if err:
            errors["fx"] = err
        else:
            results["fx"] = df.to_html(classes="data-table", border=0, na_rep="-")
    except Exception as e:
        errors["fx"] = str(e)

    # ── 채권정보센터 ─────────────────────────────────────────────────────────
    try:
        df, err = fetch_bond(date)
        if err:
            errors["bond"] = err
        else:
            results["bond"] = df.to_html(classes="data-table", border=0, na_rep="-")
    except Exception as e:
        errors["bond"] = str(e)

    # ── 콜금리 ──────────────────────────────────────────────────────────────
    try:
        df, err = fetch_call_rate(date)
        if err:
            errors["call"] = err
        else:
            results["call"] = df.to_html(classes="data-table", border=0, na_rep="-")
    except Exception as e:
        errors["call"] = str(e)

    # ── KRX ─────────────────────────────────────────────────────────────────
    try:
        df, err, actual = fetch_krx(date)
        if err:
            errors["krx"] = err
        else:
            results["krx"] = df.to_html(classes="data-table", border=0, na_rep="-")
            results["krx_date"] = actual
    except Exception as e:
        errors["krx"] = str(e)

    return jsonify({"results": results, "errors": errors, "date": date})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
