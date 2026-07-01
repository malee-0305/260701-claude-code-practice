import time
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ── Windows 로컬 환경 설정 ────────────────────────────────────────────────
CHROME_BINARY = ""          # 비워두면 시스템 Chrome 자동 사용
CHROME_DRIVER = "chromedriver.exe"   # 같은 폴더에 있는 chromedriver.exe

# ── KRX 로그인 대기용 전역 상태 ──────────────────────────────────────────
_krx_login_event  = threading.Event()
_krx_result       = {"data": None, "error": None, "done": False}
_krx_driver_ref   = [None]   # list로 감싸서 thread 간 공유

# ─────────────────────────────────────────────────────────────────────────────
# Chrome 드라이버 팩토리
# ─────────────────────────────────────────────────────────────────────────────
def make_driver(headless=True):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    opts = webdriver.ChromeOptions()
    if CHROME_BINARY:
        opts.binary_location = CHROME_BINARY
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    svc = Service(CHROME_DRIVER)
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.execute_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return driver


# ══════════════════════════════════════════════════════════════════════════════
# 1. Investing.com  (requests + BeautifulSoup, Selenium 불필요)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_investing(date: str):
    import requests, urllib3, pandas as pd
    from bs4 import BeautifulSoup
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 날짜 포맷: "2026년 06월 30일"
    date_fmt = f"{date[:4]}년 {date[4:6]}월 {date[6:8]}일"

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/149.0.0.0 Safari/537.36"),
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://kr.investing.com/"
    })

    CLS1 = "freeze-column-w-1 w-full overflow-x-auto text-xs leading-4"
    CLS2 = "genTbl closedTbl historicalTbl"

    def get_row(url, label):
        try:
            r = sess.get(url, verify=False, timeout=20)
            if r.status_code != 200:
                return None
            soup  = BeautifulSoup(r.text, "html.parser")
            table = (soup.find("table", class_=CLS1) or
                     soup.find("table", class_=CLS2))
            if not table:
                return None
            tbody = table.find("tbody")
            if not tbody:
                return None
            for row in tbody.find_all("tr"):
                cols = [c.get_text(strip=True) for c in row.find_all("td")]
                if cols and cols[0] == date_fmt:
                    return [label] + cols
        except Exception as e:
            print(f"[investing] {label}: {e}")
        return None

    targets = [
        # 상품
        ("https://kr.investing.com/commodities/crude-oil-historical-data",               "WTI"),
        ("https://kr.investing.com/currencies/us-dollar-index-historical-data",          "달러인덱스(DXI)"),
        # 미국채
        ("https://kr.investing.com/rates-bonds/u.s.-2-year-bond-yield-historical-data",  "미국채 2년"),
        ("https://kr.investing.com/rates-bonds/u.s.-5-year-bond-yield-historical-data",  "미국채 5년"),
        ("https://kr.investing.com/rates-bonds/u.s.-10-year-bond-yield-historical-data", "미국채 10년"),
        ("https://kr.investing.com/rates-bonds/u.s.-30-year-bond-yield-historical-data", "미국채 30년"),
        # 일본국채
        ("https://kr.investing.com/rates-bonds/japan-3-year-bond-yield-historical-data", "일본국채 3년"),
        ("https://kr.investing.com/rates-bonds/japan-5-year-bond-yield-historical-data", "일본국채 5년"),
        ("https://kr.investing.com/rates-bonds/japan-10-year-bond-yield-historical-data","일본국채 10년"),
        ("https://kr.investing.com/rates-bonds/japan-30-year-bond-yield-historical-data","일본국채 30년"),
        # 독일국채
        ("https://kr.investing.com/rates-bonds/germany-10-year-bond-yield-historical-data","독일국채 10년"),
        # 브라질국채
        ("https://kr.investing.com/rates-bonds/brazil-3-year-bond-yield-historical-data", "브라질국채 3년"),
        ("https://kr.investing.com/rates-bonds/brazil-5-year-bond-yield-historical-data", "브라질국채 5년"),
        ("https://kr.investing.com/rates-bonds/brazil-10-year-bond-yield-historical-data","브라질국채 10년"),
    ]
    index_targets = [
        ("indices",  "kospi",                      "KOSPI"),
        ("equities", "samsung-electronics-co-ltd", "삼성전자"),
        ("indices",  "kospi-large-sized",           "KOSPI 대형"),
        ("indices",  "kospi-medium-sized",          "KOSPI 중형"),
        ("indices",  "kospi-small-sized",           "KOSPI 소형"),
        ("indices",  "kosdaq",                      "KOSDAQ"),
        ("indices",  "us-spx-500",                  "S&P 500"),
        ("indices",  "nasdaq-composite",            "NASDAQ"),
        ("indices",  "eu-stoxx50",                  "EUROSTOXX 50"),
        ("indices",  "japan-ni225",                 "닛케이 225"),
        ("indices",  "csi300",                      "CSI 300"),
        ("indices",  "hang-seng-china-enterprises", "항셍 차이나"),
        ("indices",  "sensex",                      "SENSEX"),
        ("indices",  "vn",                          "VN 지수"),
        ("indices",  "idx-composite",               "IDX"),
        ("indices",  "msci-world-stock",            "MSCI World"),
    ]

    rows = []
    for url, label in targets:
        row = get_row(url, label)
        if row:
            rows.append(row)
    for typ, ticker, label in index_targets:
        row = get_row(f"https://kr.investing.com/{typ}/{ticker}-historical-data", label)
        if row:
            rows.append(row)

    if not rows:
        return None, f"날짜 {date_fmt} 데이터 없음 (휴장일 또는 날짜 오류)"

    max_c  = max(len(r) for r in rows)
    padded = [r + [""] * (max_c - len(r)) for r in rows]
    base   = ["지표", "날짜", "종가", "시가", "고가", "저가"]
    extra  = ["거래량"] if max_c >= 8 else []
    cols   = (base + extra + ["등락률"] + [""] * 10)[:max_c]
    df = pd.DataFrame(padded, columns=cols).set_index("지표")
    return df, None


# ══════════════════════════════════════════════════════════════════════════════
# 2. 환율 (SMBS) — headless=False, 팝업 없이 JS로 값 주입
# ══════════════════════════════════════════════════════════════════════════════
def fetch_fx(date: str):
    import pandas as pd
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    driver = make_driver(headless=False)
    wait   = WebDriverWait(driver, 30)

    def force_set(el, val):
        driver.execute_script(
            "var e=arguments[0],v=arguments[1];e.value=v;"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));",
            el, val)

    results = []
    try:
        driver.get("http://www.smbs.biz/ExRate/StdExRate.jsp")
        time.sleep(3)

        for fld in ["startDate", "endDate"]:
            try:
                el = wait.until(EC.presence_of_element_located((By.ID, fld)))
                force_set(el, date)
            except Exception:
                pass

        for currency, idx in [("달러", 0), ("위안화", 1), ("엔화", 3)]:
            try:
                sel_el = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '//*[@id="frm_SearchDate"]/div[1]/table/tbody/tr[1]/td/select')))
                Select(sel_el).select_by_index(idx)

                btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '//*[@id="frm_SearchDate"]/p[2]/a[2]/img')))
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)

                cell = wait.until(EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="frm_SearchDate"]/div[6]/table/tbody/tr/td[1]')))
                txt = cell.text.strip().replace(",", "")
                val = float(txt) if txt else None
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
        try:
            driver.quit()
        except Exception:
            pass


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

    driver = make_driver(headless=False)
    wait   = WebDriverWait(driver, 40)

    def dismiss_popup():
        for xpath in ['//*[@id="popup_ok"]', '//button[contains(text(),"확인")]',
                      '//input[@type="button"][@value="확인"]']:
            try:
                el = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                el.click()
                return
            except Exception:
                pass

    def type_date_in(xpath):
        el = driver.find_element(By.XPATH, xpath)
        driver.execute_script(
            "var e=arguments[0];e.value='';e.value=arguments[1];"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));", el, date)
        el.send_keys(Keys.TAB)

    def click_all_evaluators():
        for i in range(1, 5):
            try:
                driver.find_element(By.XPATH, f'//*[@id="checkbox{i}_input_0"]').click()
                time.sleep(0.3)
            except Exception:
                pass

    def click_search_btn():
        driver.find_element(By.XPATH, '//*[@id="image1"]').click()
        time.sleep(6)

    def parse_grid(div_id, tbl_id, tbody_id, cols):
        soup = BeautifulSoup(driver.page_source, "html.parser")
        div  = soup.find("div", id=div_id)
        if not div:
            return pd.DataFrame(columns=cols)
        tbl  = div.find("table", id=tbl_id)
        if not tbl:
            return pd.DataFrame(columns=cols)
        tb   = tbl.find("tbody", id=tbody_id)
        if not tb:
            return pd.DataFrame(columns=cols)
        data = [[c.get_text(strip=True) for c in r.find_all("td")]
                for r in tb.find_all("tr")]
        return pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)

    def switch_to_nested():
        driver.switch_to.default_content()
        try:
            driver.switch_to.frame(driver.find_element(By.NAME, "fraAMAKMain"))
        except Exception:
            driver.switch_to.frame(driver.find_element(By.ID, "fraAMAKMain"))
        driver.switch_to.frame(driver.find_element(By.ID, "maincontent"))
        driver.switch_to.frame(driver.find_element(By.ID, "tabContents1_contents_tabs1_body"))

    def click_menu_by_candidates(*xpaths):
        for xp in xpaths:
            try:
                driver.find_element(By.XPATH, xp).click()
                time.sleep(5)
                return
            except Exception:
                pass
        raise RuntimeError(f"메뉴 클릭 실패: {xpaths}")

    try:
        driver.get("https://www.kofiabond.or.kr/")
        time.sleep(8)

        # 메인 프레임 → 국고채/회사채 화면
        driver.switch_to.frame(driver.find_element(By.NAME, "fraAMAKMain"))
        driver.find_element(By.XPATH, '//*[@id="image6"]').click()
        time.sleep(8)

        # 국고채·회사채·금융채 탭
        driver.switch_to.frame(driver.find_element(By.ID, "maincontent"))
        driver.switch_to.frame(driver.find_element(By.ID, "tabContents1_contents_tabs1_body"))
        time.sleep(5)
        dismiss_popup()
        type_date_in('//*[@id="srchDt_input"]')
        click_all_evaluators()
        click_search_btn()

        bond_cols = ['종류','종류명','신용등급','조회기준','3월','6월','9월','1년','1년6월',
                     '2년','2년6월','3년','4년','5년','7년','10년','15년','20년','30년','50년']
        kb_df1 = parse_grid("grdMain_dataLayer","grdMain_body_table","grdMain_body_tbody", bond_cols)

        # CP 탭
        switch_to_nested()
        click_menu_by_candidates(
            '//*[@id="leftGenLv1_1_leftGrpLv1Li"]',
            '//*[@id="leftGenLv1_1_leftGrpLv1A"]',
            '//li[contains(@id,"leftGrpLv1")][2]/a',
            '//li[contains(@id,"leftGrpLv1")][2]',
        )
        dismiss_popup()
        type_date_in('//*[@id="srchDt_input"]')
        click_all_evaluators()
        click_search_btn()

        cp_cols = ['신용등급','구분','기관명','7일','15일','1월','3월','6월','1년']
        kb_df2  = parse_grid("grdMain_dataLayer","grdMain_body_table","grdMain_body_tbody", cp_cols)

        # CD 탭
        switch_to_nested()
        click_menu_by_candidates(
            '//*[@id="leftGenLv1_2_leftGrpLv1A"]',
            '//*[@id="leftGenLv1_2_leftGrpLv1Li"]',
            '//li[contains(@id,"leftGrpLv1")][3]/a',
            '//li[contains(@id,"leftGrpLv1")][3]',
        )
        dismiss_popup()
        type_date_in('//*[@id="srchDt_input"]')
        click_all_evaluators()
        click_search_btn()

        kb_df3 = parse_grid("grdMain_dataLayer","grdMain_body_table","grdMain_body_tbody", cp_cols)

        def sf(df, row, col):
            try:
                return float(str(df.iloc[row, col]).replace(",", ""))
            except Exception:
                return None

        summary = {
            "국고채 3년":     sf(kb_df1, 0, 11),
            "국고채 5년":     sf(kb_df1, 0, 13),
            "국고채 10년":    sf(kb_df1, 0, 15),
            "회사채 AAA(3y)": sf(kb_df1,28, 11),
            "회사채 AA+(3y)": sf(kb_df1,29, 11),
            "회사채 AA0(3y)": sf(kb_df1,30, 11),
            "회사채 AA-(3y)": sf(kb_df1,31, 11),
            "회사채 A+(3y)":  sf(kb_df1,32, 11),
            "회사채 A0(3y)":  sf(kb_df1,33, 11),
            "회사채 A-(3y)":  sf(kb_df1,34, 11),
            "회사채 BBB+(3y)":sf(kb_df1,35, 11),
            "금융채 AA-(3y)": sf(kb_df1,19, 11),
            "금융채 A+(3y)":  sf(kb_df1,20, 11),
            "금융채 A0(3y)":  sf(kb_df1,21, 11),
            "금융채 A-(3y)":  sf(kb_df1,22, 11),
            "CD(91일)":       sf(kb_df3, 5,  6),
            "CP(91일)":       sf(kb_df2, 5,  6),
        }
        df = pd.DataFrame(list(summary.items()), columns=["종목","수익률(%)"])
        return df.set_index("종목"), None

    except Exception as e:
        return None, str(e)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# 4. 콜금리 (한국은행 ECOS)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_call_rate(date: str):
    import pandas as pd
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = make_driver(headless=True)
    wait   = WebDriverWait(driver, 30)

    try:
        driver.get("https://ecos.bok.or.kr/#/SearchStat")
        time.sleep(6)

        def safe_click(xpath, delay=2):
            try:
                el = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                el.click()
                time.sleep(delay)
            except Exception as e:
                print(f"[call] {xpath}: {e}")

        safe_click('//*[@id="root"]/div[4]/div/div[2]/div[2]/ul/li[1]/div/a', 8)
        safe_click('//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[1]/td/div[1]/span[2]')
        safe_click('//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[4]/td/div[1]')
        safe_click('//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[6]/td/div[1]/span[2]')
        safe_click('//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[7]/td/div[1]/span[2]')
        safe_click('//*[@id="allCheckDiv0"]/label')
        safe_click('//*[@id="1"]/div/div[1]/div/div[1]/div[5]/div[1]/table/tbody/tr[2]/td/div/span')
        safe_click('//*[@id="centerDiv"]/div/div/div/div[2]/div/div[2]/div/div[3]/div/button[2]')
        safe_click('//*[@id="centerDiv"]/div/div/div/div[3]/div/div[2]/div/div/div[3]/div/button')
        safe_click('//*[@id="centerDiv"]/div/div[2]/div/div/div/div/div/div[1]/div[2]/div/button[3]', 2)

        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        chart = soup.find("div", class_="chartBox")
        if not chart:
            return None, "콜금리 테이블 파싱 실패"

        body_div = chart.find("div", class_="rg-body")
        tbl1 = body_div.find("table", class_="rg-table") if body_div else None
        head_div = soup.find("div", class_="rg-header")
        tbl2 = head_div.find("table", class_="rg-table") if head_div else None
        if not tbl1 or not tbl2:
            return None, "콜금리 테이블 구조 파싱 실패"

        data = [[c.find("div", class_="rg-renderer").get_text(strip=True)
                 for c in r.find_all("td")] for r in tbl1.find("tbody").find_all("tr")]
        head = [[c.get_text(strip=True) for c in r.find_all("td")]
                for r in tbl2.find("tbody").find_all("tr")]

        df = pd.DataFrame(data, columns=head)
        df.insert(0, "", "콜금리")
        return df.set_index(df.columns[0]), None

    except Exception as e:
        return None, str(e)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# 5. KRX  — Chrome 창을 열고 사용자가 직접 로그인 후 웹에서 "완료" 클릭
# ══════════════════════════════════════════════════════════════════════════════
def _krx_worker(date: str):
    """별도 스레드에서 실행. 로그인 대기 후 데이터 수집."""
    import pandas as pd
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    def wait_ready(driver, sec=30):
        WebDriverWait(driver, sec).until(
            lambda d: d.execute_script("return document.readyState") == "complete")

    def open_mdi(driver, wait, menu_id):
        driver.get(f"https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId={menu_id}")
        wait_ready(driver, 40)
        wait.until(EC.presence_of_element_located((By.ID, "jsMdiMenu")))

    def safe_click(wait, by, sel):
        el = wait.until(EC.element_to_be_clickable((by, sel)))
        el.click()
        return el

    def clear_type(el, txt):
        el.send_keys(Keys.CONTROL + "a")
        el.send_keys(Keys.DELETE)
        el.send_keys(txt)

    def to_float(x):
        try:
            s = str(x).replace(",", "").strip()
            return 0.0 if s in ("", "nan", "none", "-") else float(s)
        except Exception:
            return 0.0

    def parse_simple(html, table_id, cols):
        soup = BeautifulSoup(html, "html.parser")
        tbl  = soup.find("table", {"id": table_id})
        if not tbl:
            return pd.DataFrame(columns=cols)
        rows = tbl.find("tbody").find_all("tr") if tbl.find("tbody") else []
        data = [[c.get_text(strip=True).replace(",", "") for c in r.find_all("td")]
                for r in rows
                if "조회된 데이터가 없습니다" not in r.get_text()]
        return pd.DataFrame(data, columns=cols) if data else pd.DataFrame(columns=cols)

    def parse_grid(html):
        soup  = BeautifulSoup(html, "html.parser")
        outer = (soup.find("div", class_="CI-GRID-WRAPPER") or
                 soup.find("div", class_="CI-GRID-AREA"))
        if not outer:
            return []
        tbl = outer.find("table", class_="CI-GRID-BODY-TABLE")
        if not tbl:
            return []
        rows = tbl.find("tbody").find_all("tr") if tbl.find("tbody") else []
        return [[c.get_text(strip=True).replace(",", "") for c in r.find_all("td")]
                for r in rows]

    def wait_rows(driver, css, timeout=60, min_rows=1):
        end = time.time() + timeout
        while time.time() < end:
            html = driver.page_source
            if "조회된 데이터가 없습니다" in html:
                return False, True
            soup = BeautifulSoup(html, "html.parser")
            tbl  = soup.select_one(css)
            if tbl:
                tb = tbl.find("tbody")
                if tb:
                    valid = [r for r in tb.find_all("tr")
                             if "조회된 데이터가 없습니다" not in r.get_text()]
                    if len(valid) >= min_rows:
                        return True, False
            time.sleep(0.5)
        return False, False

    def prev_day(d, n=1):
        return (datetime.strptime(d, "%Y%m%d") - timedelta(days=n)).strftime("%Y%m%d")

    def ensure_date(driver, wait, date_xpath, btn_xpath, css, d, max_back=10):
        for _ in range(max_back + 1):
            box = wait.until(EC.presence_of_element_located((By.XPATH, date_xpath)))
            clear_type(box, d)
            safe_click(wait, By.XPATH, btn_xpath)
            ok, nodata = wait_rows(driver, css)
            if ok:
                return d
            if nodata:
                d = prev_day(d)
        raise RuntimeError(f"데이터 없음 (최대 {max_back}일 소급)")

    def safe_close_tab(wait):
        for xp in ['//*[@id="jsMdiTab"]/li[1]/a/button',
                   '//*[@id="jsMdiTab"]/li/a/button',
                   '//*[@id="jsMdiTab"]//button']:
            try:
                safe_click(wait, By.XPATH, xp)
                return
            except Exception:
                pass

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

    driver = None
    try:
        # Chrome 창 열고 KRX 메인 이동
        driver = make_driver(headless=False)
        _krx_driver_ref[0] = driver
        wait = WebDriverWait(driver, 60)

        driver.get("https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd")
        driver.maximize_window()
        wait_ready(driver, 30)

        # ── 로그인 대기 ────────────────────────────────────────────────────
        _krx_login_event.wait()   # 웹 페이지에서 "로그인 완료" 클릭 시 해제
        _krx_login_event.clear()

        # 1) 시총
        open_mdi(driver, wait, "MDC0301")
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[2]/a')
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[2]/ul/li[1]/a')

        actual_date = ensure_date(
            driver, wait,
            '//*[@id="trdDd"]', '//*[@id="jsSearchButton"]',
            'table#jsTable_MDCEASY002_0', date)

        krx_df1 = parse_simple(driver.page_source, "jsTable_MDCEASY002_0",
                                ["구분","회사수","종목수","상장주식수","자본금","시가총액"])
        safe_close_tab(wait)

        # 2) ETP 시총
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[3]/a')
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[3]/ul/li[1]/a')
        ensure_date(driver, wait,
            '//*[@id="trdDd"]', '//*[@id="jsSearchButton"]',
            'table#jsTable_MDCEASY007_0', actual_date)
        krx_df2 = parse_simple(driver.page_source, "jsTable_MDCEASY007_0",
                                ["구분","운용사수","종목수","상장좌수","시가총액","순자산총액"])

        # 3) 주식 거래대금
        date1 = (datetime.strptime(actual_date, "%Y%m%d") - timedelta(days=28)).strftime("%Y%m%d")
        date2 = actual_date

        open_mdi(driver, wait, "MDC0201")
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[2]/a')
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[2]/ul/li[3]/a')
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[2]/ul/li[3]/ul/li[1]/a')
        safe_click(wait, By.XPATH,
            '//*[@id="MDCSTAT022_FORM"]/div[1]/div/table/tbody/tr[3]/td/label[1]')
        safe_click(wait, By.XPATH,
            '//*[@id="MDCSTAT022_FORM"]/div[1]/div/table/tbody/tr[3]/td/label[2]')

        strt = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="strtDd"]')))
        endd = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="endDd"]')))
        clear_type(strt, date1)
        clear_type(endd, date2)
        safe_click(wait, By.XPATH, '//*[@id="jsSearchButton"]')
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, 'div.CI-GRID-WRAPPER, div.CI-GRID-AREA')))
        wait_rows(driver, "table.CI-GRID-BODY-TABLE", timeout=80, min_rows=2)

        gc = ["투자자구분","거래량(매도)","거래량(매수)","거래량(순매수)",
              "거래대금(매도)","거래대금(매수)","거래대금(순매수)"]
        krx_df3 = pd.DataFrame(parse_grid(driver.page_source), columns=gc)
        safe_close_tab(wait)

        # 4) ETF 거래대금
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[3]/a')
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[3]/ul/li[1]/a')
        safe_click(wait, By.XPATH,
            '//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[3]/ul/li[1]/ul/li[6]/a')

        strt2 = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="strtDd"]')))
        endd2 = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="endDd"]')))
        clear_type(strt2, date1)
        clear_type(endd2, date2)
        safe_click(wait, By.XPATH, '//*[@id="jsSearchButton"]')
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, 'div.CI-GRID-WRAPPER, div.CI-GRID-AREA')))
        wait_rows(driver, "table.CI-GRID-BODY-TABLE", timeout=80, min_rows=2)
        krx_df4 = pd.DataFrame(parse_grid(driver.page_source), columns=gc)

        # 5) 요약
        kospi_mc  = pick_first(krx_df1,"구분",["유가증권시장","KOSPI","코스피"],"시가총액") / 1e6
        kosdaq_mc = pick_first(krx_df1,"구분",["코스닥시장","KOSDAQ","코스닥"],"시가총액")  / 1e6
        konex_mc  = pick_first(krx_df1,"구분",["코넥스시장","KONEX","코넥스"],"시가총액")   / 1e6
        etf_mc    = pick_first(krx_df2,"구분",["ETF"],"시가총액") / 1e6
        etn_mc    = pick_first(krx_df2,"구분",["ETN"],"시가총액") / 1e6

        rows_out = [
            {"구분":"시가총액(조원)",
             "코스피":round(kospi_mc,1),"코스닥":round(kosdaq_mc,1),
             "코넥스":round(konex_mc,1),"ETF":round(etf_mc,1),"ETN":round(etn_mc,1)},
            {"구분":"전체거래대금(조원)",
             "전체":round(grid_sum(krx_df3,"전체")/1e6,2),
             "개인":round(grid_sum(krx_df3,"개인")/1e6,2),
             "기관":round(grid_sum(krx_df3,"기관")/1e6,2),
             "외국인":round(grid_sum(krx_df3,"외국인")/1e6,2)},
            {"구분":"ETF거래대금(조원)",
             "전체":round(grid_sum(krx_df4,"전체")/1e12,2),
             "개인":round(grid_sum(krx_df4,"개인")/1e12,2),
             "기관":round(grid_sum(krx_df4,"기관")/1e12,2),
             "외국인":round(grid_sum(krx_df4,"외국인")/1e12,2)},
        ]
        df_final = pd.DataFrame(rows_out).set_index("구분")
        _krx_result["data"]  = df_final.to_html(classes="data-table", border=0, na_rep="-")
        _krx_result["error"] = None

    except Exception as e:
        _krx_result["error"] = str(e)
        _krx_result["data"]  = None
    finally:
        _krx_result["done"] = True
        _krx_driver_ref[0]  = None
        try:
            if driver:
                driver.quit()
        except Exception:
            pass


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
        return jsonify({"error": "날짜 형식 오류"}), 400

    results, errors = {}, {}

    # Investing.com (빠름)
    try:
        df, err = fetch_investing(date)
        if err:
            errors["investing"] = err
        else:
            results["investing"] = df.to_html(classes="data-table", border=0, na_rep="-")
    except Exception as e:
        errors["investing"] = str(e)

    # 환율
    try:
        df, err = fetch_fx(date)
        if err:
            errors["fx"] = err
        else:
            results["fx"] = df.to_html(classes="data-table", border=0, na_rep="-")
    except Exception as e:
        errors["fx"] = str(e)

    # 채권정보센터
    try:
        df, err = fetch_bond(date)
        if err:
            errors["bond"] = err
        else:
            results["bond"] = df.to_html(classes="data-table", border=0, na_rep="-")
    except Exception as e:
        errors["bond"] = str(e)

    # 콜금리
    try:
        df, err = fetch_call_rate(date)
        if err:
            errors["call"] = err
        else:
            results["call"] = df.to_html(classes="data-table", border=0, na_rep="-")
    except Exception as e:
        errors["call"] = str(e)

    return jsonify({"results": results, "errors": errors, "date": date})


@app.route("/api/krx-start", methods=["POST"])
def api_krx_start():
    """KRX Chrome 창 열기 + 로그인 대기 스레드 시작."""
    data = request.get_json()
    date = data.get("date", "").replace("-", "")
    if len(date) != 8 or not date.isdigit():
        return jsonify({"error": "날짜 형식 오류"}), 400

    global _krx_result
    _krx_result = {"data": None, "error": None, "done": False}
    _krx_login_event.clear()

    t = threading.Thread(target=_krx_worker, args=(date,), daemon=True)
    t.start()
    return jsonify({"status": "browser_opened"})


@app.route("/api/krx-continue", methods=["POST"])
def api_krx_continue():
    """사용자가 KRX 로그인 완료 버튼 클릭 시 호출."""
    _krx_login_event.set()
    return jsonify({"status": "ok"})


@app.route("/api/krx-result", methods=["GET"])
def api_krx_result():
    """KRX 스크래핑 완료 여부 폴링."""
    return jsonify({
        "done":  _krx_result["done"],
        "data":  _krx_result["data"],
        "error": _krx_result["error"],
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
