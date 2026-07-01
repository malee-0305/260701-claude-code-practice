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

# NXT 업로드 데이터 저장 (투자자구분 → {매도, 매수} in 원)
# 구조: {"kospi": {투자자: {매도:v, 매수:v}, ...}, "kosdaq": {...}}
_nxt_data = {"kospi": {}, "kosdaq": {}, "period": ""}

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
    import requests, urllib3, pandas as pd
    from bs4 import BeautifulSoup
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        sess = requests.Session()
        sess.verify = False
        sess.headers.update(headers)
        for page in range(1, max_pages + 1):
            chk("fx")
            r = sess.get(base_url + f"&page={page}", timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("table.tbl_exchange tbody tr")
            if not rows:
                # 테이블 구조가 바뀐 경우 모든 테이블 시도
                for tbl in soup.find_all("table"):
                    tb = tbl.find("tbody")
                    if tb:
                        rows = tb.find_all("tr")
                        if rows: break
            for row in rows:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cols) < 2: continue
                if cols[0] == date_fmt:
                    try: return float(cols[1].replace(",", ""))
                    except: return None
            # 마지막 날짜 확인
            date_cells = [td.get_text(strip=True)
                         for row in rows
                         for td in [row.find("td")]
                         if td]
            if date_cells and date_cells[-1] < date_fmt:
                break
        return None

    results = []
    for name, code in fx_codes.items():
        chk("fx")
        try:
            val = fetch_naver_fx(code)
            print(f"[fx] {name}: {val}")
        except RuntimeError: raise
        except Exception as e:
            print(f"[fx] {name} 오류: {e}"); val = None
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

        # 1) 시총 — 종합정보(일) [42001], menuId=MDC03010201 직접 접근
        open_mdi(driver, wait, "MDC03010201")
        # 조회구분: 상장정보 선택 (라디오 버튼)
        for xp in [
            '//label[contains(text(),"상장정보")]',
            '//*[contains(@id,"FORM")]//label[contains(text(),"상장")]',
            '//input[@type="radio"][@value="S"]',
            '//input[@type="radio"][1]',
        ]:
            try: sc(wait, By.XPATH, xp); time.sleep(0.3); break
            except: pass
        actual=ed(driver,wait,'//*[@id="trdDd"]','//*[@id="jsSearchButton"]',
                  'table#jsTable_MDCEASY002_0', end_date)
        krx1=ps(driver.page_source,"jsTable_MDCEASY002_0",
                ["구분","회사수","종목수","상장주식수","자본금","시가총액"])

        # 2) ETP 시총 — 증권상품 종합정보(일) [43001]
        # menuId 후보를 순서대로 시도
        etp_cols = ["구분","운용사수","종목수","상장좌수","시가총액","순자산총액"]
        krx2 = pd.DataFrame(columns=etp_cols)
        for etp_mid in ["MDC03010301", "MDC03010302", "MDC03020101", "MDC03020201"]:
            try:
                open_mdi(driver, wait, etp_mid)
                ed(driver, wait, '//*[@id="trdDd"]', '//*[@id="jsSearchButton"]',
                   'table#jsTable_MDCEASY007_0', actual)
                tmp = ps(driver.page_source, "jsTable_MDCEASY007_0", etp_cols)
                if not tmp.empty:
                    krx2 = tmp
                    break
            except Exception:
                continue

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

        # ── 결과 조합 ──────────────────────────────────────────────────────

        # 시가총액: "소계" 행에서 추출 (유가증권시장→첫번째소계, 코스닥→두번째소계)
        subcap_rows = krx1[krx1["구분"].astype(str).str.strip().str.contains("소계",na=False)]
        kospi  = tf(subcap_rows.iloc[0]["시가총액"]) if len(subcap_rows) > 0 else 0.0
        kosdaq = tf(subcap_rows.iloc[1]["시가총액"]) if len(subcap_rows) > 1 else 0.0
        # KONEX: 코넥스 섹션의 주권 행 (마지막 주권 행)
        konex_rows = krx1[krx1["구분"].astype(str).str.strip() == "주권"]
        konex = tf(konex_rows.iloc[-1]["시가총액"]) if not konex_rows.empty else 0.0
        # 전체 합계
        total_cap_row = krx1[krx1["구분"].astype(str).str.contains("전체|합계",na=False)]
        total_cap = tf(total_cap_row.iloc[-1]["시가총액"]) if not total_cap_row.empty else 0.0

        etf_row = krx2[krx2["구분"].astype(str).str.strip() == "ETF"]
        etn_row = krx2[krx2["구분"].astype(str).str.strip() == "ETN"]
        elw_row = krx2[krx2["구분"].astype(str).str.strip() == "ELW"]
        etf = tf(etf_row.iloc[0]["시가총액"]) if not etf_row.empty else 0.0
        etn = tf(etn_row.iloc[0]["시가총액"]) if not etn_row.empty else 0.0
        elw = tf(elw_row.iloc[0]["시가총액"]) if not elw_row.empty else 0.0

        # 투자자 순서 (KRX)
        inv_order=["금융투자","보험","투신","사모","은행","기타금융","연기금 등","기관합계",
                   "기타법인","개인","외국인","기타외국인","전체"]

        # KRX 투자자별 거래대금 상세 테이블
        def build_detail(df_raw, unit):
            rows=[]
            for inv in inv_order:
                keyword=inv.replace(" 등","").strip()
                hit=df_raw[df_raw["투자자구분"].astype(str).str.contains(keyword,na=False,regex=False)]
                if hit.empty: continue
                r=hit.iloc[0]
                sell=tf(r["거래대금(매도)"])
                buy=tf(r["거래대금(매수)"])
                rows.append({
                    "투자자구분":inv,
                    "매도(조원)":round(sell/unit,2),
                    "매수(조원)":round(buy/unit,2),
                    "합계(조원)":round((sell+buy)/unit,2),
                })
            return pd.DataFrame(rows).set_index("투자자구분")

        df_stock_detail = build_detail(krx3, unit=1e6)   # 주식: 백만원
        df_etf_detail   = build_detail(krx4, unit=1e12)  # ETF: 원

        # NXT 업로드 데이터로 테이블 구성 (원 → 조원)
        has_nxt = bool(_nxt_data["kospi"] or _nxt_data["kosdaq"])

        # NXT 투자자별 합산 헬퍼 (기타+기관종합=기관, 전체=기타+개인+기관종합+외국인)
        def nxt_get(mkt_dict, *keys):
            """mkt_dict에서 여러 키를 매칭해 매도+매수 합산(원). 정확한 키 우선, 그 다음 부분 매칭."""
            total = 0.0
            for k in keys:
                if k in mkt_dict:
                    # 정확한 키 매칭 (예: "기타" → "기타"만, "기타외국인" 제외)
                    total += mkt_dict[k]["매도"] + mkt_dict[k]["매수"]
                else:
                    matched = next((dk for dk in mkt_dict if k in dk), None)
                    if matched:
                        total += mkt_dict[matched]["매도"] + mkt_dict[matched]["매수"]
            return total

        def build_nxt_from_upload(market_dict):
            if not market_dict:
                return None
            all_keys = list(market_dict.keys())
            rows = []
            for k in all_keys:
                sell = market_dict[k]["매도"]
                buy  = market_dict[k]["매수"]
                rows.append({"투자자구분": k,
                             "매도(조원)": round(sell/1e12, 2),
                             "매수(조원)": round(buy/1e12, 2),
                             "합계(조원)": round((sell+buy)/1e12, 2)})
            return pd.DataFrame(rows).set_index("투자자구분") if rows else None

        df_nxt_kospi  = build_nxt_from_upload(_nxt_data["kospi"])  if has_nxt else None
        df_nxt_kosdaq = build_nxt_from_upload(_nxt_data["kosdaq"]) if has_nxt else None

        # KRX 주식 합계 (전체/개인/기관/외국인)
        def tot_krx(df, label, unit):
            keyword = label.replace(" 등","").strip()
            hit = df[df["투자자구분"].astype(str).str.contains(keyword, na=False, regex=False)]
            if hit.empty: return 0.0
            r = hit.iloc[0]
            return (tf(r["거래대금(매도)"]) + tf(r["거래대금(매수)"])) / unit

        # NXT 합계: 기관=기타+기관종합, 전체=기타+개인+기관종합+외국인
        def nxt_total_val(key_label):
            val = 0.0
            for mkt in [_nxt_data["kospi"], _nxt_data["kosdaq"]]:
                if key_label == "전체":
                    # 기관종합은 하위 항목(금융투자+보험+투신 등)의 합계이므로 제외해 이중계산 방지
                    for k in mkt:
                        if "기관종합" not in k:
                            val += mkt[k]["매도"] + mkt[k]["매수"]
                elif key_label == "기관":
                    val += nxt_get(mkt, "기타", "기관종합")
                elif key_label == "개인":
                    val += nxt_get(mkt, "개인")
                elif key_label == "외국인":
                    val += nxt_get(mkt, "외국인")
            return round(val / 1e12, 2)

        krx_주식_전체  = round(tot_krx(krx3, "전체",   1e6), 2)
        krx_주식_개인  = round(tot_krx(krx3, "개인",   1e6), 2)
        krx_주식_기관  = round(tot_krx(krx3, "기관합계", 1e6), 2)
        krx_주식_외국  = round(tot_krx(krx3, "외국인", 1e6), 2)

        nxt_전체 = nxt_total_val("전체")  if has_nxt else 0.0
        nxt_개인 = nxt_total_val("개인")  if has_nxt else 0.0
        nxt_기관 = nxt_total_val("기관")  if has_nxt else 0.0
        nxt_외국 = nxt_total_val("외국인") if has_nxt else 0.0

        tbl_h = lambda title, df: (
            f'<div class="krx-sub"><h5>{title}</h5>'
            + df.to_html(classes="data-table", border=0, na_rep="-")
            + '</div>'
        )

        # ── 시가총액 테이블 (백만원 → 조원 변환) ───────────────────────
        def to_trillion(df, cols):
            """지정 컬럼을 백만원→조원으로 변환한 복사본 반환"""
            d = df.copy()
            for c in cols:
                if c in d.columns:
                    d[c] = d[c].apply(lambda x: round(tf(x)/1e6, 4) if str(x).strip() not in ("","nan","-") else "-")
            return d

        # krx_df1: 상장주식수, 자본금, 시가총액 → 조원
        df_cap1 = to_trillion(krx1, ["상장주식수","자본금","시가총액"])
        # krx_df2: 상장좌수, 시가총액, 순자산총액 → 조원
        df_cap2 = to_trillion(krx2, ["상장좌수","시가총액","순자산총액"])

        # 시가총액 요약: krx_df1 소계/합계 행에서 조원 값으로 직접 구성
        def cap_조원(val): return round(val/1e6, 2)
        df_cap_summary = pd.DataFrame([
            {"구분":"코스피(소계)", "상장주식수(조원)": cap_조원(tf(subcap_rows.iloc[0]["상장주식수"])) if len(subcap_rows)>0 else "-",
             "자본금(조원)": cap_조원(tf(subcap_rows.iloc[0]["자본금"])) if len(subcap_rows)>0 else "-",
             "시가총액(조원)": cap_조원(kospi)},
            {"구분":"코스닥(소계)", "상장주식수(조원)": cap_조원(tf(subcap_rows.iloc[1]["상장주식수"])) if len(subcap_rows)>1 else "-",
             "자본금(조원)": cap_조원(tf(subcap_rows.iloc[1]["자본금"])) if len(subcap_rows)>1 else "-",
             "시가총액(조원)": cap_조원(kosdaq)},
            {"구분":"코넥스(주권)", "상장주식수(조원)": cap_조원(tf(konex_rows.iloc[-1]["상장주식수"])) if not konex_rows.empty else "-",
             "자본금(조원)": cap_조원(tf(konex_rows.iloc[-1]["자본금"])) if not konex_rows.empty else "-",
             "시가총액(조원)": cap_조원(konex)},
            {"구분":"ETF", "상장주식수(조원)":"-", "자본금(조원)":"-", "시가총액(조원)": cap_조원(etf)},
            {"구분":"ETN", "상장주식수(조원)":"-", "자본금(조원)":"-", "시가총액(조원)": cap_조원(etn)},
            {"구분":"ELW", "상장주식수(조원)":"-", "자본금(조원)":"-", "시가총액(조원)": cap_조원(elw)},
            {"구분":"전체합계", "상장주식수(조원)":"-", "자본금(조원)":"-", "시가총액(조원)": cap_조원(total_cap)},
        ]).set_index("구분")

        # ── 거래대금 합계 요약 ──────────────────────────────────────────
        nxt_period_label = _nxt_data["period"] or "업로드"
        summary_rows = [
            {"구분": "KRX 주식",
             "전체(조원)": krx_주식_전체, "개인(조원)": krx_주식_개인,
             "기관(조원)": krx_주식_기관, "외국인(조원)": krx_주식_외국},
        ]
        if has_nxt:
            summary_rows.append({
                "구분": f"NXT ({nxt_period_label})",
                "전체(조원)": nxt_전체, "개인(조원)": nxt_개인,
                "기관(조원)": nxt_기관, "외국인(조원)": nxt_외국,
            })
            summary_rows.append({
                "구분": "합계 (KRX주식+NXT)",
                "전체(조원)": round(krx_주식_전체+nxt_전체, 2),
                "개인(조원)": round(krx_주식_개인+nxt_개인, 2),
                "기관(조원)": round(krx_주식_기관+nxt_기관, 2),
                "외국인(조원)": round(krx_주식_외국+nxt_외국, 2),
            })
        df_summary = pd.DataFrame(summary_rows).set_index("구분")

        period_label = f"{start_date}~{actual}"
        html_out = (
            tbl_h(f"■ 시가총액 요약 (기준일: {actual}, 단위: 조원)", df_cap_summary)
            + tbl_h(f"■ 시가총액 원본 — krx_df1 (기준일: {actual}, 단위: 조원)", df_cap1)
            + tbl_h(f"■ ETP 시총 원본 — krx_df2 (기준일: {actual}, 단위: 조원)", df_cap2)
            + tbl_h(f"■ 주식 거래대금 — KRX ({period_label}, 조원)", df_stock_detail)
            + tbl_h(f"■ ETF 거래대금 — KRX ({period_label}, 조원)", df_etf_detail)
        )
        if df_nxt_kospi is not None:
            html_out += tbl_h(f"■ NXT 거래대금 — 코스피 ({nxt_period_label}, 조원)", df_nxt_kospi)
        if df_nxt_kosdaq is not None:
            html_out += tbl_h(f"■ NXT 거래대금 — 코스닥 ({nxt_period_label}, 조원)", df_nxt_kosdaq)
        html_out += tbl_h(f"■ 거래대금 합계 요약 ({period_label}, 조원)", df_summary)

        _state["krx"]["data"]  = html_out
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

    # ── Data2 & 3: TradingEconomics (인도네시아, 베트남) — Selenium 사용 ────────
    # 목표 테이블: 실제 / 이전 / 최고 / 최저 / 날짜 / 단위 / 업데이트 주기
    TE_COLS = ["실제", "이전", "최고", "최저", "날짜", "단위", "업데이트 주기"]

    def scrape_te_stats(country, url):
        """TradingEconomics 기준금리 요약 통계 파싱 (Selenium + JS 직접 추출)"""
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By
        driver2 = None
        try:
            driver2 = make_driver(headless=True)
            driver2.get(url)
            # 페이지 로딩 대기: #p (현재 금리 값) 요소가 나타날 때까지
            try:
                WebDriverWait(driver2, 20).until(
                    EC.presence_of_element_located((By.ID, "p"))
                )
            except Exception:
                time.sleep(12)

            # JS로 핵심 값 직접 추출
            def js_txt(selector):
                try:
                    return driver2.execute_script(
                        f"var el=document.querySelector('{selector}'); return el?el.innerText.trim():'';"
                    )
                except Exception:
                    return ""

            actual   = js_txt("#p")
            previous = js_txt("#prev")
            high     = js_txt("#high")
            low      = js_txt("#low")
            date_rng = js_txt("#date")
            unit     = js_txt("#unit")
            freq     = js_txt("#freq")

            # JS로 값이 안 오면 BeautifulSoup으로 탐색
            if not actual:
                soup = BeautifulSoup(driver2.page_source, "html.parser")
                def bs_txt(sid):
                    el = soup.find(id=sid)
                    return el.get_text(strip=True) if el else ""
                actual   = bs_txt("p")
                previous = bs_txt("prev")
                high     = bs_txt("high")
                low      = bs_txt("low")
                date_rng = bs_txt("date")
                unit     = bs_txt("unit")
                freq     = bs_txt("freq")

            # 여전히 없으면 테이블 행 파싱 (마지막 수단)
            if not actual:
                soup = BeautifulSoup(driver2.page_source, "html.parser")
                for tbl in soup.find_all("table"):
                    tbody = tbl.find("tbody")
                    if not tbody:
                        continue
                    for row in tbody.find_all("tr"):
                        cols = [td.get_text(strip=True) for td in row.find_all("td")]
                        if len(cols) >= 4 and any(c.replace(".","").isdigit() for c in cols[:2]):
                            actual, previous = cols[0], cols[1]
                            high   = cols[2] if len(cols) > 2 else ""
                            low    = cols[3] if len(cols) > 3 else ""
                            date_rng = cols[4] if len(cols) > 4 else ""
                            unit   = cols[5] if len(cols) > 5 else ""
                            freq   = cols[6] if len(cols) > 6 else ""
                            break
                    if actual:
                        break

            return [{"국가": country,
                     "실제": actual or "N/A", "이전": previous or "N/A",
                     "최고": high or "N/A",   "최저": low or "N/A",
                     "날짜": date_rng or "N/A","단위": unit or "N/A",
                     "업데이트 주기": freq or "N/A"}]
        except RuntimeError: raise
        except Exception as e:
            print(f"[rates] {country} TE: {e}")
        finally:
            try:
                if driver2: driver2.quit()
            except Exception: pass
        return [{"국가": country, **{c: "N/A" for c in TE_COLS}}]

    chk("rates")
    te_rows = []
    for country, url in [
        ("인도네시아", "https://ko.tradingeconomics.com/indonesia/interest-rate"),
        ("베트남",     "https://ko.tradingeconomics.com/vietnam/interest-rate"),
    ]:
        chk("rates")
        te_rows.extend(scrape_te_stats(country, url))

    df_te = pd.DataFrame(te_rows) if te_rows else pd.DataFrame(
        columns=["국가"] + TE_COLS)

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
                html += "<h4 style='margin:14px 0 8px'>인도네시아·베트남 기준금리 (TradingEconomics)</h4>"
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
# 영업일 조정 헬퍼
# ══════════════════════════════════════════════════════════════════════════════
def adjust_to_biz_day(date_str, direction="back"):
    """주말이면 직전(back) 또는 직후(forward) 평일로 이동. 공휴일은 KRX가 알아서 처리."""
    d = datetime.strptime(date_str, "%Y%m%d")
    step = timedelta(days=-1) if direction == "back" else timedelta(days=1)
    while d.weekday() >= 5:   # 5=토, 6=일
        d += step
    return d.strftime("%Y%m%d")


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

    # 주말이면 자동 조정: 종료일→직전 평일, 시작일→직후 평일
    end_date   = adjust_to_biz_day(end_date,   direction="back")
    if start_date and len(start_date)==8:
        start_date = adjust_to_biz_day(start_date, direction="forward")

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


@app.route("/api/krx-nxt-upload", methods=["POST"])
def api_krx_nxt_upload():
    """NXT 거래대금 엑셀 파일 업로드 및 파싱"""
    import io
    try:
        import openpyxl
    except ImportError:
        return jsonify({"status":"error","message":"openpyxl 패키지가 없습니다. pip install openpyxl"}), 500

    f = request.files.get("file")
    if not f:
        # 파일 없이 POST → 초기화
        _nxt_data["kospi"] = {}
        _nxt_data["kosdaq"] = {}
        _nxt_data["period"] = ""
        return jsonify({"status":"ok","message":"NXT 데이터 초기화됨"})

    try:
        wb = openpyxl.load_workbook(io.BytesIO(f.read()), data_only=True)
        ws = wb.active

        kospi_map = {}
        kosdaq_map = {}
        period_str = request.form.get("period", "")

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or row[0] is None:
                continue
            market = str(row[0]).strip()
            inv    = str(row[1]).strip() if row[1] is not None else ""
            try:
                sell = float(str(row[2]).replace(",","")) if row[2] not in (None,"") else 0.0
                buy  = float(str(row[3]).replace(",","")) if row[3] not in (None,"") else 0.0
            except Exception:
                continue
            if not inv:
                continue
            if "코스피" in market or "KOSPI" in market.upper():
                kospi_map[inv] = {"매도": sell, "매수": buy}
            elif "코스닥" in market or "KOSDAQ" in market.upper():
                kosdaq_map[inv] = {"매도": sell, "매수": buy}

        _nxt_data["kospi"]  = kospi_map
        _nxt_data["kosdaq"] = kosdaq_map
        _nxt_data["period"] = period_str

        total_rows = len(kospi_map) + len(kosdaq_map)
        return jsonify({
            "status": "ok",
            "kospi_rows": len(kospi_map),
            "kosdaq_rows": len(kosdaq_map),
            "message": f"NXT 데이터 로드 완료 (코스피 {len(kospi_map)}개, 코스닥 {len(kosdaq_map)}개 투자자)"
        })
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500


@app.route("/api/krx-nxt-status", methods=["GET"])
def api_krx_nxt_status():
    return jsonify({
        "loaded": bool(_nxt_data["kospi"] or _nxt_data["kosdaq"]),
        "kospi_rows": len(_nxt_data["kospi"]),
        "kosdaq_rows": len(_nxt_data["kosdaq"]),
        "period": _nxt_data["period"],
    })


@app.route("/api/download-excel", methods=["GET"])
def api_download_excel():
    """전체 섹션 데이터를 Excel로 다운로드"""
    import io as _io
    try:
        import openpyxl as _xl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return jsonify({"error":"openpyxl 필요: pip install openpyxl"}), 500
    try:
        import pandas as _pd
    except ImportError:
        return jsonify({"error":"pandas 필요"}), 500

    from flask import send_file

    SECTION_NAMES = {
        "krx":      "KRX 시가총액·거래대금",
        "bond":     "채권수익률",
        "fx":       "환율",
        "call":     "콜금리",
        "investing":"글로벌지수·금리·원자재",
        "rates":    "국가별 기준금리",
    }

    wb = _xl.Workbook()
    wb.remove(wb.active)

    header_fill = PatternFill("solid", fgColor="2B6CB0")
    header_font = Font(color="FFFFFF", bold=True)
    title_font  = Font(bold=True, size=11)

    for sec in SECTIONS:
        data = _state[sec].get("data")
        if not data:
            continue
        sheet_name = SECTION_NAMES.get(sec, sec)[:31]
        ws = wb.create_sheet(title=sheet_name)
        cur_row = 1

        try:
            dfs = _pd.read_html(data, flavor="lxml")
        except Exception:
            try:
                dfs = _pd.read_html(data)
            except Exception:
                ws.cell(row=1, column=1, value=str(data)[:200])
                continue

        for df in dfs:
            df = df.fillna("")
            # 컬럼 헤더
            for c_idx, col in enumerate(df.columns, 1):
                cell = ws.cell(row=cur_row, column=c_idx, value=str(col))
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")
            cur_row += 1
            # 데이터 행
            for _, row in df.iterrows():
                for c_idx, val in enumerate(row, 1):
                    ws.cell(row=cur_row, column=c_idx, value=val)
                cur_row += 1
            cur_row += 2  # 테이블 간 빈 줄

        # 열 너비 자동 조정
        for col in ws.columns:
            max_len = max((len(str(c.value)) if c.value else 0) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    if not wb.sheetnames:
        ws = wb.create_sheet("데이터없음")
        ws.cell(row=1, column=1, value="조회된 데이터가 없습니다.")

    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"금융지표_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
