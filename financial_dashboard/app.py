import time, threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CHROME_BINARY = ""
CHROME_DRIVER = "chromedriver.exe"

# ── 섹션별 전역 상태 ─────────────────────────────────────────────────────────
SECTIONS = ["investing", "fx", "bond", "call", "krx", "rates"]

def _fresh_state():
    return {"done": False, "data": None, "error": None,
            "stop": threading.Event(), "running": False}

_state = {s: _fresh_state() for s in SECTIONS}

# KRX 로그인 대기용
_krx_login_event = threading.Event()

# ── Chrome 드라이버 ──────────────────────────────────────────────────────────
def make_driver(headless=True):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    opts = webdriver.ChromeOptions()
    if CHROME_BINARY:
        opts.binary_location = CHROME_BINARY
    if headless:
        opts.add_argument("--headless=new")
    for a in ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
              "--window-size=1920,1080","--disable-blink-features=AutomationControlled",
              "--ignore-certificate-errors"]:
        opts.add_argument(a)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(service=Service(CHROME_DRIVER), options=opts)
    driver.execute_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return driver

def stopped(sec): return _state[sec]["stop"].is_set()
def chk(sec):
    if stopped(sec): raise RuntimeError("조회가 중지되었습니다.")


# ══════════════════════════════════════════════════════════════════════════════
# 1. Investing.com
# ══════════════════════════════════════════════════════════════════════════════
def run_investing(end_date: str):
    import requests, urllib3, pandas as pd
    from bs4 import BeautifulSoup
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    date_fmt = f"{end_date[:4]}년 {end_date[4:6]}월 {end_date[6:8]}일"
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://kr.investing.com/"
    })
    CLS1 = "freeze-column-w-1 w-full overflow-x-auto text-xs leading-4"
    CLS2 = "genTbl closedTbl historicalTbl"

    def get_row(url, label):
        chk("investing")
        try:
            r = sess.get(url, verify=False, timeout=20)
            if r.status_code != 200: return None
            soup  = BeautifulSoup(r.text, "html.parser")
            table = soup.find("table", class_=CLS1) or soup.find("table", class_=CLS2)
            if not table: return None
            tbody = table.find("tbody")
            if not tbody: return None
            for row in tbody.find_all("tr"):
                cols = [c.get_text(strip=True) for c in row.find_all("td")]
                if cols and cols[0] == date_fmt:
                    return [label] + cols
        except RuntimeError: raise
        except Exception as e:
            print(f"[investing] {label}: {e}")
        return None

    targets = [
        ("https://kr.investing.com/commodities/crude-oil-historical-data",                "WTI"),
        ("https://kr.investing.com/currencies/us-dollar-index-historical-data",           "달러인덱스(DXI)"),
        ("https://kr.investing.com/rates-bonds/u.s.-2-year-bond-yield-historical-data",   "미국채 2년"),
        ("https://kr.investing.com/rates-bonds/u.s.-5-year-bond-yield-historical-data",   "미국채 5년"),
        ("https://kr.investing.com/rates-bonds/u.s.-10-year-bond-yield-historical-data",  "미국채 10년"),
        ("https://kr.investing.com/rates-bonds/u.s.-30-year-bond-yield-historical-data",  "미국채 30년"),
        ("https://kr.investing.com/rates-bonds/japan-3-year-bond-yield-historical-data",  "일본국채 3년"),
        ("https://kr.investing.com/rates-bonds/japan-5-year-bond-yield-historical-data",  "일본국채 5년"),
        ("https://kr.investing.com/rates-bonds/japan-10-year-bond-yield-historical-data", "일본국채 10년"),
        ("https://kr.investing.com/rates-bonds/japan-30-year-bond-yield-historical-data", "일본국채 30년"),
        ("https://kr.investing.com/rates-bonds/germany-10-year-bond-yield-historical-data","독일국채 10년"),
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
        if row: rows.append(row)
    for typ, ticker, label in index_targets:
        row = get_row(f"https://kr.investing.com/{typ}/{ticker}-historical-data", label)
        if row: rows.append(row)

    if not rows:
        return None, f"날짜 {date_fmt} 데이터 없음"

    max_c  = max(len(r) for r in rows)
    padded = [r + [""] * (max_c - len(r)) for r in rows]
    base   = ["지표","날짜","종가","시가","고가","저가"]
    extra  = ["거래량"] if max_c >= 8 else []
    cols   = (base + extra + ["등락률"] + [""]*10)[:max_c]
    import pandas as pd
    df = pd.DataFrame(padded, columns=cols).set_index("지표")
    return df, None


# ══════════════════════════════════════════════════════════════════════════════
# 2. 환율 (네이버 금융) — requests 기반, Selenium 불필요
# ══════════════════════════════════════════════════════════════════════════════
def run_fx(date: str):
    import requests, pandas as pd
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Referer": "https://finance.naver.com/marketindex/",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    fx_codes = {
        "달러(USD)": "FX_USDKRW",
        "위안(CNY)": "FX_CNYKRW",
        "엔(JPY)":   "FX_JPYKRW",
    }

    date_fmt = f"{date[:4]}.{date[4:6]}.{date[6:8]}"

    def fetch_naver_fx(market_code, max_pages=10):
        base_url = ("https://finance.naver.com/marketindex/exchangeDailyQuote.nhn"
                    f"?marketindexCd={market_code}")
        for page in range(1, max_pages + 1):
            chk("fx")
            r = requests.get(base_url + f"&page={page}", headers=headers, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            for row in soup.select("table.tbl_exchange tbody tr"):
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if not cols: continue
                if cols[0] == date_fmt:
                    try: return float(cols[1].replace(",", ""))
                    except: return None
            last_els = soup.select("table.tbl_exchange tbody tr td:first-child")
            if last_els:
                last = last_els[-1].get_text(strip=True)
                if last and last < date_fmt:
                    break
        return None

    results = []
    for name, code in fx_codes.items():
        chk("fx")
        try:
            val = fetch_naver_fx(code)
        except RuntimeError: raise
        except Exception as e:
            print(f"[fx] {name}: {e}"); val = None
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
    except Exception: pass

    return df, None


# ══════════════════════════════════════════════════════════════════════════════
# 3. 채권정보센터 — 원본 스크립트 기반
# ══════════════════════════════════════════════════════════════════════════════
def run_bond(date: str):
    import pandas as pd
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    driver = make_driver(headless=False)
    wait   = WebDriverWait(driver, 40)

    def switch_to_main_frame():
        """fraAMAKMain 프레임으로 이동"""
        driver.switch_to.default_content()
        try:
            driver.switch_to.frame(driver.find_element(By.NAME, "fraAMAKMain"))
        except Exception:
            driver.switch_to.frame(driver.find_element(By.ID, "fraAMAKMain"))

    def switch_to_nested():
        """fraAMAKMain → maincontent → tabContents1_contents_tabs1_body"""
        switch_to_main_frame()
        driver.switch_to.frame(driver.find_element(By.ID, "maincontent"))
        driver.switch_to.frame(driver.find_element(By.ID, "tabContents1_contents_tabs1_body"))
        time.sleep(3)

    def dismiss_popup():
        try:
            WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="popup_ok"]'))).click()
        except Exception: pass

    def input_date():
        el = driver.find_element(By.XPATH, '//*[@id="srchDt_input"]')
        el.send_keys(Keys.BACKSPACE * len(el.get_attribute("value")))
        el.send_keys(date)

    def click_all_cb():
        for i in range(1, 5):
            try:
                driver.find_element(By.XPATH, f'//*[@id="checkbox{i}_input_0"]').click()
                time.sleep(0.2)
            except Exception: pass

    def click_search():
        driver.find_element(By.XPATH, '//*[@id="image1"]').click()
        time.sleep(7)

    def parse_grid(cols):
        soup  = BeautifulSoup(driver.page_source, "html.parser")
        d     = soup.find("div", id="grdMain_dataLayer")
        if not d: return pd.DataFrame(columns=cols)
        t     = d.find("table", id="grdMain_body_table")
        if not t: return pd.DataFrame(columns=cols)
        tb    = t.find("tbody", id="grdMain_body_tbody")
        if not tb: return pd.DataFrame(columns=cols)
        data  = [[c.get_text(strip=True) for c in r.find_all("td")] for r in tb.find_all("tr")]
        if not data: return pd.DataFrame(columns=cols)
        # 열 수가 다르면 잘라내거나 패딩
        fixed = []
        for row in data:
            if len(row) > len(cols):  row = row[:len(cols)]
            elif len(row) < len(cols): row = row + [""] * (len(cols) - len(row))
            fixed.append(row)
        return pd.DataFrame(fixed, columns=cols)

    bond_cols = ['종류','종류명','신용등급','조회기준','3월','6월','9월','1년','1년6월',
                 '2년','2년6월','3년','4년','5년','7년','10년','15년','20년','30년','50년']
    cp_cols   = ['신용등급','구분','기관명','7일','15일','1월','3월','6월','1년']

    try:
        chk("bond")
        driver.get("https://www.kofiabond.or.kr/")
        time.sleep(10)

        # ── 채권수익률 메뉴 진입 (image6 클릭) ──────────────────────────────
        switch_to_main_frame()
        driver.find_element(By.XPATH, '//*[@id="image6"]').click()
        time.sleep(10)

        # ── 국고채/회사채 조회 ────────────────────────────────────────────────
        switch_to_nested()
        dismiss_popup()
        input_date()
        click_all_cb()
        click_search()
        chk("bond")
        kb_df1 = parse_grid(bond_cols)

        # ── CP 메뉴 클릭 (fraAMAKMain 레벨에서) ──────────────────────────────
        chk("bond")
        switch_to_main_frame()
        driver.find_element(By.XPATH, '//*[@id="leftGenLv1_1_leftGrpLv1Li"]').click()
        time.sleep(5)

        # ── CP 조회 ───────────────────────────────────────────────────────────
        switch_to_nested()
        dismiss_popup()
        input_date()
        click_all_cb()
        click_search()
        chk("bond")
        kb_df2 = parse_grid(cp_cols)

        # ── CD 메뉴 클릭 (fraAMAKMain 레벨에서) ──────────────────────────────
        chk("bond")
        switch_to_main_frame()
        driver.find_element(By.XPATH, '//*[@id="leftGenLv1_2_leftGrpLv1A"]').click()
        time.sleep(5)

        # ── CD 조회 ───────────────────────────────────────────────────────────
        switch_to_nested()
        dismiss_popup()
        input_date()
        click_all_cb()
        click_search()
        chk("bond")
        kb_df3 = parse_grid(cp_cols)

        def sf(df, r, c):
            try: return float(str(df.iloc[r, c]).replace(",", ""))
            except: return None

        summary = {
            "국고채 3년":    sf(kb_df1, 0, 11),
            "국고채 5년":    sf(kb_df1, 0, 13),
            "국고채 10년":   sf(kb_df1, 0, 15),
            "회사채 AAA(3y)":sf(kb_df1, 28, 11),
            "회사채 AA+(3y)":sf(kb_df1, 29, 11),
            "회사채 AA0(3y)":sf(kb_df1, 30, 11),
            "회사채 AA-(3y)":sf(kb_df1, 31, 11),
            "회사채 A+(3y)": sf(kb_df1, 32, 11),
            "회사채 A0(3y)": sf(kb_df1, 33, 11),
            "회사채 A-(3y)": sf(kb_df1, 34, 11),
            "회사채 BBB+(3y)":sf(kb_df1, 35, 11),
            "금융채 AA-(3y)":sf(kb_df1, 19, 11),
            "금융채 A+(3y)": sf(kb_df1, 20, 11),
            "금융채 A0(3y)": sf(kb_df1, 21, 11),
            "금융채 A-(3y)": sf(kb_df1, 22, 11),
            "CD(91일)":      sf(kb_df3, 5, 6),
            "CP(91일)":      sf(kb_df2, 5, 6),
        }
        df = pd.DataFrame(list(summary.items()), columns=["종목", "수익률(%)"])
        return df.set_index("종목"), None

    except RuntimeError: raise
    except Exception as e:
        return None, str(e)
    finally:
        try: driver.quit()
        except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
# 4. 콜금리
# ══════════════════════════════════════════════════════════════════════════════
def run_call(date: str):
    import pandas as pd
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = make_driver(headless=True)
    wait   = WebDriverWait(driver, 30)

    def sc(xpath, delay=2):
        chk("call")
        try:
            el = wait.until(EC.element_to_be_clickable((By.XPATH,xpath)))
            el.click(); time.sleep(delay)
        except RuntimeError: raise
        except Exception as e: print(f"[call] {xpath}: {e}")

    try:
        driver.get("https://ecos.bok.or.kr/#/SearchStat")
        time.sleep(7)
        sc('//*[@id="root"]/div[4]/div/div[2]/div[2]/ul/li[1]/div/a', 9)
        sc('//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[1]/td/div[1]/span[2]')
        sc('//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[4]/td/div[1]')
        sc('//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[6]/td/div[1]/span[2]')
        sc('//*[@id="centerDiv"]/div/div/div/div[1]/div/div[2]/div/div[2]/div/div/div/div[1]/div/div[1]/div[1]/div[1]/table/tbody/tr[7]/td/div[1]/span[2]')
        sc('//*[@id="allCheckDiv0"]/label')
        sc('//*[@id="1"]/div/div[1]/div/div[1]/div[5]/div[1]/table/tbody/tr[2]/td/div/span')
        sc('//*[@id="centerDiv"]/div/div/div/div[2]/div/div[2]/div/div[3]/div/button[2]')
        sc('//*[@id="centerDiv"]/div/div/div/div[3]/div/div[2]/div/div/div[3]/div/button')
        sc('//*[@id="centerDiv"]/div/div[2]/div/div/div/div/div/div[1]/div[2]/div/button[3]',2)

        html  = driver.page_source
        soup  = BeautifulSoup(html,"html.parser")
        chart = soup.find("div",class_="chartBox")
        if not chart: return None,"콜금리 테이블 파싱 실패"

        bd = chart.find("div",class_="rg-body")
        t1 = bd.find("table",class_="rg-table") if bd else None
        hd = soup.find("div",class_="rg-header")
        t2 = hd.find("table",class_="rg-table") if hd else None
        if not t1 or not t2: return None,"콜금리 테이블 구조 오류"

        data=[[c.find("div",class_="rg-renderer").get_text(strip=True) for c in r.find_all("td")]
              for r in t1.find("tbody").find_all("tr")]
        head=[[c.get_text(strip=True) for c in r.find_all("td")]
              for r in t2.find("tbody").find_all("tr")]
        df = pd.DataFrame(data,columns=head)
        df.insert(0,"","콜금리")
        return df.set_index(df.columns[0]), None

    except RuntimeError: raise
    except Exception as e:
        return None, str(e)
    finally:
        try: driver.quit()
        except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
# 5. KRX
# ══════════════════════════════════════════════════════════════════════════════
def _krx_worker(start_date: str, end_date: str):
    import pandas as pd
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    def wr(d,s=30):
        WebDriverWait(d,s).until(lambda x:x.execute_script("return document.readyState")=="complete")

    def open_mdi(driver,wait,mid):
        driver.get(f"https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId={mid}")
        wr(driver,40)
        wait.until(EC.presence_of_element_located((By.ID,"jsMdiMenu")))

    def sc(wait,by,sel):
        el=wait.until(EC.element_to_be_clickable((by,sel))); el.click(); return el

    def ct(el,txt):
        el.send_keys(Keys.CONTROL+"a"); el.send_keys(Keys.DELETE); el.send_keys(txt)

    def tf(x):
        try:
            s=str(x).replace(",","").strip()
            return 0.0 if s in("","nan","none","-") else float(s)
        except: return 0.0

    def ps(html,tid,cols):
        soup=BeautifulSoup(html,"html.parser")
        t=soup.find("table",{"id":tid})
        if not t: return pd.DataFrame(columns=cols)
        rows=t.find("tbody").find_all("tr") if t.find("tbody") else []
        data=[[c.get_text(strip=True).replace(",","") for c in r.find_all("td")]
              for r in rows if "조회된 데이터가 없습니다" not in r.get_text()]
        return pd.DataFrame(data,columns=cols) if data else pd.DataFrame(columns=cols)

    def pg(html):
        soup=BeautifulSoup(html,"html.parser")
        outer=soup.find("div",class_="CI-GRID-WRAPPER") or soup.find("div",class_="CI-GRID-AREA")
        if not outer: return []
        t=outer.find("table",class_="CI-GRID-BODY-TABLE")
        if not t: return []
        rows=t.find("tbody").find_all("tr") if t.find("tbody") else []
        return [[c.get_text(strip=True).replace(",","") for c in r.find_all("td")] for r in rows]

    def wr2(driver,css,timeout=60,min_rows=1):
        end=time.time()+timeout
        while time.time()<end:
            chk("krx")
            html=driver.page_source
            if "조회된 데이터가 없습니다" in html: return False,True
            soup=BeautifulSoup(html,"html.parser")
            t=soup.select_one(css)
            if t:
                tb=t.find("tbody")
                if tb:
                    v=[r for r in tb.find_all("tr") if "조회된 데이터가 없습니다" not in r.get_text()]
                    if len(v)>=min_rows: return True,False
            time.sleep(0.5)
        return False,False

    def ed(driver,wait,dxp,bxp,css,d,mb=10):
        for _ in range(mb+1):
            chk("krx")
            box=wait.until(EC.presence_of_element_located((By.XPATH,dxp)))
            ct(box,d)
            sc(wait,By.XPATH,bxp)
            ok,nd=wr2(driver,css)
            if ok: return d
            if nd: d=(datetime.strptime(d,"%Y%m%d")-timedelta(days=1)).strftime("%Y%m%d")
        raise RuntimeError(f"데이터 없음 (최대 {mb}일 소급)")

    def sct(wait):
        for xp in['//*[@id="jsMdiTab"]/li[1]/a/button',
                  '//*[@id="jsMdiTab"]/li/a/button',
                  '//*[@id="jsMdiTab"]//button']:
            try: sc(wait,By.XPATH,xp); return
            except Exception: pass

    def pf(df,lc,cands,vc):
        s=df[lc].astype(str).str.strip()
        for k in cands:
            hit=df[s.str.contains(k,na=False)]
            if not hit.empty: return tf(hit.iloc[0][vc])
        raise RuntimeError(f"라벨 매칭 실패: {cands}")

    def gs(df,label):
        hit=df[df["투자자구분"].astype(str).str.contains(label,na=False)]
        if hit.empty: raise RuntimeError(f"'{label}' 없음")
        row=hit.iloc[0]
        return tf(row["거래대금(매도)"])+tf(row["거래대금(매수)"])

    driver=None
    try:
        driver=make_driver(headless=False)
        wait=WebDriverWait(driver,60)
        driver.get("https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd")
        wr(driver,30)
        driver.maximize_window()

        _krx_login_event.wait()
        _krx_login_event.clear()
        chk("krx")

        # 1) 시총
        open_mdi(driver,wait,"MDC0301")
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[2]/a')
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[2]/ul/li[1]/a')
        actual=ed(driver,wait,'//*[@id="trdDd"]','//*[@id="jsSearchButton"]',
                  'table#jsTable_MDCEASY002_0', end_date)
        krx1=ps(driver.page_source,"jsTable_MDCEASY002_0",
                ["구분","회사수","종목수","상장주식수","자본금","시가총액"])
        sct(wait)

        # 2) ETP
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[3]/a')
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[5]/ul/li[2]/div/div[1]/ul/li[3]/ul/li[1]/a')
        ed(driver,wait,'//*[@id="trdDd"]','//*[@id="jsSearchButton"]',
           'table#jsTable_MDCEASY007_0',actual)
        krx2=ps(driver.page_source,"jsTable_MDCEASY007_0",
                ["구분","운용사수","종목수","상장좌수","시가총액","순자산총액"])

        # 3) 주식 거래대금 (start_date ~ actual)
        open_mdi(driver,wait,"MDC0201")
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[2]/a')
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[2]/ul/li[3]/a')
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[2]/ul/li[3]/ul/li[1]/a')
        sc(wait,By.XPATH,'//*[@id="MDCSTAT022_FORM"]/div[1]/div/table/tbody/tr[3]/td/label[1]')
        sc(wait,By.XPATH,'//*[@id="MDCSTAT022_FORM"]/div[1]/div/table/tbody/tr[3]/td/label[2]')
        s1=wait.until(EC.presence_of_element_located((By.XPATH,'//*[@id="strtDd"]')))
        e1=wait.until(EC.presence_of_element_located((By.XPATH,'//*[@id="endDd"]')))
        ct(s1, start_date); ct(e1, actual)
        sc(wait,By.XPATH,'//*[@id="jsSearchButton"]')
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,'div.CI-GRID-WRAPPER,div.CI-GRID-AREA')))
        wr2(driver,"table.CI-GRID-BODY-TABLE",80,2)
        gc=["투자자구분","거래량(매도)","거래량(매수)","거래량(순매수)","거래대금(매도)","거래대금(매수)","거래대금(순매수)"]
        krx3=pd.DataFrame(pg(driver.page_source),columns=gc)
        sct(wait)

        # 4) ETF 거래대금
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[3]/a')
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[3]/ul/li[1]/a')
        sc(wait,By.XPATH,'//*[@id="jsMdiMenu"]/div[4]/ul/li[1]/ul/li[2]/div/div[1]/ul/li[3]/ul/li[1]/ul/li[6]/a')
        s2=wait.until(EC.presence_of_element_located((By.XPATH,'//*[@id="strtDd"]')))
        e2=wait.until(EC.presence_of_element_located((By.XPATH,'//*[@id="endDd"]')))
        ct(s2, start_date); ct(e2, actual)
        sc(wait,By.XPATH,'//*[@id="jsSearchButton"]')
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,'div.CI-GRID-WRAPPER,div.CI-GRID-AREA')))
        wr2(driver,"table.CI-GRID-BODY-TABLE",80,2)
        krx4=pd.DataFrame(pg(driver.page_source),columns=gc)

        # 요약
        kospi=pf(krx1,"구분",["유가증권시장","KOSPI","코스피"],"시가총액")/1e6
        kosdaq=pf(krx1,"구분",["코스닥시장","KOSDAQ","코스닥"],"시가총액")/1e6
        konex=pf(krx1,"구분",["코넥스시장","KONEX","코넥스"],"시가총액")/1e6
        etf=pf(krx2,"구분",["ETF"],"시가총액")/1e6
        etn=pf(krx2,"구분",["ETN"],"시가총액")/1e6

        rows=[
            {"구분":"시가총액(조원)","코스피":round(kospi,1),"코스닥":round(kosdaq,1),
             "코넥스":round(konex,1),"ETF":round(etf,1),"ETN":round(etn,1)},
            {"구분":f"전체거래대금(조원)\n{start_date}~{actual}",
             "전체":round(gs(krx3,"전체")/1e6,2),"개인":round(gs(krx3,"개인")/1e6,2),
             "기관":round(gs(krx3,"기관")/1e6,2),"외국인":round(gs(krx3,"외국인")/1e6,2)},
            {"구분":f"ETF거래대금(조원)\n{start_date}~{actual}",
             "전체":round(gs(krx4,"전체")/1e12,2),"개인":round(gs(krx4,"개인")/1e12,2),
             "기관":round(gs(krx4,"기관")/1e12,2),"외국인":round(gs(krx4,"외국인")/1e12,2)},
        ]
        df_f=pd.DataFrame(rows).set_index("구분")
        _state["krx"]["data"]  = df_f.to_html(classes="data-table",border=0,na_rep="-")
        _state["krx"]["error"] = None
    except RuntimeError as e:
        _state["krx"]["error"] = str(e)
        _state["krx"]["data"]  = None
    except Exception as e:
        _state["krx"]["error"] = str(e)
        _state["krx"]["data"]  = None
    finally:
        _state["krx"]["done"]    = True
        _state["krx"]["running"] = False
        try:
            if driver: driver.quit()
        except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
# 6. 국가별 기준 금리
# ══════════════════════════════════════════════════════════════════════════════
def run_rates():
    import requests, urllib3, pandas as pd
    from bs4 import BeautifulSoup
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # ── Data1: Investing.com 중앙은행 금리 ───────────────────────────────────
    chk("rates")
    rows_main = []
    try:
        r = requests.get("https://kr.investing.com/central-banks/",
                         headers=headers, verify=False, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # 테이블 탐색
        table = None
        for t in soup.find_all("table"):
            txt = t.get_text()
            if "기준금리" in txt or "현재 금리" in txt or "Central Bank" in txt or "BOK" in txt:
                table = t; break
        if table is None:
            # div 기반 레이아웃 탐색
            for div in soup.find_all("div", class_=lambda c: c and "centralBank" in c):
                rows_main.append({"중앙은행": div.get_text(strip=True)})

        if table:
            thead = table.find("thead")
            col_names = []
            if thead:
                col_names = [th.get_text(strip=True) for th in thead.find_all("th")]
            tbody = table.find("tbody")
            if tbody:
                for row in tbody.find_all("tr"):
                    cols = [td.get_text(strip=True) for td in row.find_all("td")]
                    if cols:
                        if col_names and len(cols) == len(col_names):
                            rows_main.append(dict(zip(col_names, cols)))
                        else:
                            rows_main.append({
                                "중앙은행": cols[0] if len(cols) > 0 else "",
                                "현재 금리": cols[1] if len(cols) > 1 else "",
                                "다음 회의": cols[2] if len(cols) > 2 else "",
                                "마지막 변경": cols[3] if len(cols) > 3 else "",
                            })
    except RuntimeError: raise
    except Exception as e:
        print(f"[rates] investing.com: {e}")

    # Selenium 폴백 (데이터 없을 때)
    if not rows_main:
        chk("rates")
        driver = None
        try:
            driver = make_driver(headless=True)
            driver.get("https://kr.investing.com/central-banks/")
            time.sleep(5)
            from selenium.webdriver.common.by import By
            from bs4 import BeautifulSoup as BS4
            soup2 = BS4(driver.page_source, "html.parser")
            for table in soup2.find_all("table"):
                tbody = table.find("tbody")
                if tbody:
                    for row in tbody.find_all("tr"):
                        cols = [td.get_text(strip=True) for td in row.find_all("td")]
                        if len(cols) >= 2:
                            rows_main.append({
                                "중앙은행": cols[0],
                                "현재 금리": cols[1] if len(cols)>1 else "",
                                "다음 회의": cols[2] if len(cols)>2 else "",
                                "마지막 변경": cols[3] if len(cols)>3 else "",
                            })
                    if rows_main: break
        except RuntimeError: raise
        except Exception as e:
            print(f"[rates] selenium fallback: {e}")
        finally:
            try:
                if driver: driver.quit()
            except Exception: pass

    df_main = pd.DataFrame(rows_main) if rows_main else pd.DataFrame(
        columns=["중앙은행","현재 금리","다음 회의","마지막 변경"])

    # ── Data2 & 3: TradingEconomics (인도네시아, 베트남) ─────────────────────
    te_targets = [
        ("인도네시아", "https://ko.tradingeconomics.com/indonesia/interest-rate"),
        ("베트남",     "https://ko.tradingeconomics.com/vietnam/interest-rate"),
    ]

    te_rows = []
    for country, url in te_targets:
        chk("rates")
        try:
            r2 = requests.get(url, headers=headers, verify=False, timeout=20)
            soup2 = BeautifulSoup(r2.text, "html.parser")

            # 주요 지표 테이블 찾기
            found = False
            for table in soup2.find_all("table"):
                tbody2 = table.find("tbody")
                if not tbody2: continue
                for row in tbody2.find_all("tr"):
                    cols = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(cols) >= 3:
                        te_rows.append({
                            "국가": country,
                            "경제지표": cols[0] if len(cols)>0 else "",
                            "GMT":      cols[1] if len(cols)>1 else "",
                            "참고":     cols[2] if len(cols)>2 else "",
                            "실제":     cols[3] if len(cols)>3 else "",
                            "이전":     cols[4] if len(cols)>4 else "",
                            "예측치":   cols[5] if len(cols)>5 else "",
                        })
                        found = True
                if found: break

            if not found:
                # 현재 금리만 파싱
                val_el = soup2.find("span", id="p")
                val = val_el.get_text(strip=True) if val_el else "N/A"
                te_rows.append({
                    "국가": country, "경제지표": "기준금리",
                    "GMT":"","참고":"","실제": val,"이전":"","예측치":""
                })
        except RuntimeError: raise
        except Exception as e:
            te_rows.append({"국가": country,"경제지표": f"오류: {e}",
                            "GMT":"","참고":"","실제":"","이전":"","예측치":""})
            print(f"[rates] {country}: {e}")

    df_te = pd.DataFrame(te_rows) if te_rows else pd.DataFrame(
        columns=["국가","경제지표","GMT","참고","실제","이전","예측치"])

    return df_main, df_te, None


# ══════════════════════════════════════════════════════════════════════════════
# 섹션 스레드 래퍼
# ══════════════════════════════════════════════════════════════════════════════
def _run_section(sec, fn, *args):
    try:
        _state[sec]["running"] = True
        _state[sec]["done"]    = False
        _state[sec]["data"]    = None
        _state[sec]["error"]   = None
        _state[sec]["stop"].clear()

        if sec == "rates":
            df_main, df_te, err = fn()
            if err:
                _state[sec]["error"] = err
            else:
                import pandas as pd
                html  = "<h4 style='margin-bottom:8px'>Investing.com 중앙은행 금리</h4>"
                html += df_main.to_html(classes="data-table",border=0,na_rep="-",index=False)
                html += "<h4 style='margin:14px 0 8px'>인도네시아·베트남 (TradingEconomics)</h4>"
                html += df_te.to_html(classes="data-table",border=0,na_rep="-",index=False)
                _state[sec]["data"] = html
        else:
            result = fn(*args)
            if isinstance(result, tuple) and len(result) == 2:
                df, err = result
                if err:
                    _state[sec]["error"] = err
                else:
                    _state[sec]["data"] = df.to_html(classes="data-table",border=0,na_rep="-")
            else:
                _state[sec]["error"] = "반환값 오류"

    except RuntimeError as e:
        _state[sec]["error"] = str(e)
    except Exception as e:
        _state[sec]["error"] = str(e)
    finally:
        _state[sec]["done"]    = True
        _state[sec]["running"] = False


# ══════════════════════════════════════════════════════════════════════════════
# Flask 라우트
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/run/<section>", methods=["POST"])
def api_run(section):
    if section not in SECTIONS:
        return jsonify({"error": "unknown section"}), 400

    body       = request.get_json() or {}
    end_date   = body.get("end_date", "").replace("-","")
    start_date = body.get("start_date","").replace("-","")

    if not end_date or len(end_date)!=8:
        return jsonify({"error":"종료일 형식 오류"}), 400

    if _state[section]["running"]:
        return jsonify({"error":"이미 실행 중"}), 409

    if section == "krx":
        _krx_login_event.clear()
        _state["krx"].update({"done":False,"data":None,"error":None,"running":True})
        _state["krx"]["stop"].clear()
        t = threading.Thread(
            target=_krx_worker, args=(start_date or end_date, end_date), daemon=True)
        t.start()
        return jsonify({"status":"browser_opened"})

    fn_map = {
        "investing": (run_investing, [end_date]),
        "fx":        (run_fx,        [end_date]),
        "bond":      (run_bond,      [end_date]),
        "call":      (run_call,      [end_date]),
        "rates":     (run_rates,     []),
    }
    fn, args = fn_map[section]
    t = threading.Thread(target=_run_section, args=(section, fn, *args), daemon=True)
    t.start()
    return jsonify({"status":"started"})


@app.route("/api/stop/<section>", methods=["POST"])
def api_stop(section):
    if section == "all":
        for s in SECTIONS:
            _state[s]["stop"].set()
        _krx_login_event.set()   # 대기 해제
        return jsonify({"status":"stopped all"})
    if section not in SECTIONS:
        return jsonify({"error":"unknown section"}), 400
    _state[section]["stop"].set()
    if section == "krx":
        _krx_login_event.set()
    return jsonify({"status":"stopped"})


@app.route("/api/result/<section>", methods=["GET"])
def api_result(section):
    if section not in SECTIONS:
        return jsonify({"error":"unknown section"}), 400
    s = _state[section]
    return jsonify({
        "done":    s["done"],
        "running": s["running"],
        "data":    s["data"],
        "error":   s["error"],
    })


@app.route("/api/krx-continue", methods=["POST"])
def api_krx_continue():
    _krx_login_event.set()
    return jsonify({"status":"ok"})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
