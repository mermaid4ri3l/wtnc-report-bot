import os
import time
import datetime
import traceback
import cv2
import numpy as np
import re
import pandas as pd
import gspread
import chromedriver_autoinstaller
import easyocr

from datetime import datetime as dt, timedelta
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === Log 函式 ===
def log(msg):
    timestamp = dt.now().strftime("[%Y-%m-%d %H:%M:%S]")
    message = f"{timestamp} {msg}"
    print(message)
    with open("WTNC_log.txt", "a", encoding="utf-8") as f:
        f.write(message + "\n")

# === OCR 辨識驗證碼 ===
def solve_captcha_with_easyocr(captcha_path, debug=False):
    img = cv2.imread(captcha_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.bilateralFilter(gray, 11, 17, 17)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = np.ones((2, 2), np.uint8)
    processed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

    if debug:
        cv2.imwrite(captcha_path.replace(".png", "_processed.png"), processed)

    reader = easyocr.Reader(['en'], gpu=False)
    result = reader.readtext(processed)
    log(f"🔍 OCR 所有結果：{result}")

    for _, text, _ in result:
        text_clean = text.replace(" ", "").replace("=", "")
        text_fixed = re.sub(r"[^0-9\+]", "+", text_clean)
        if re.match(r"^\d+\+\d+$", text_fixed):
            log(f"✅ 成功辨識並修正：{text_fixed}")
            return text_fixed
    return ""

# === 主流程 ===
def main():
    LOGIN_URL = 'https://admin.idelivery.com.tw/admin/auth/login'
    ACCOUNT = '9352211800'
    PASSWORD = 'ABC8261'
    DOWNLOAD_DIR = "/app/downloads"
    DEBUG = False

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # 啟動 Chrome
    options = webdriver.ChromeOptions()
    prefs = {"download.default_directory": DOWNLOAD_DIR}
    options.add_experimental_option("prefs", prefs)
    chromedriver_autoinstaller.install()
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 20)
    driver.get(LOGIN_URL)

    # 登入流程
    for attempt in range(1, 16):
        log(f"\n🔄 第 {attempt} 次登入嘗試")
        try:
            captcha_element = wait.until(EC.presence_of_element_located((By.XPATH, '//img[contains(@class, "captcha")]')))
            captcha_path = os.path.join(DOWNLOAD_DIR, 'captcha.png')
            captcha_element.screenshot(captcha_path)
            captcha_text = solve_captcha_with_easyocr(captcha_path, DEBUG)
            if not captcha_text:
                driver.refresh()
                continue
            match = re.match(r"(\d+)\+(\d+)", captcha_text)
            if not match:
                driver.refresh()
                continue
            answer = int(match.group(1)) + int(match.group(2))

            driver.find_element(By.NAME, 'username').send_keys(ACCOUNT)
            driver.find_element(By.NAME, 'password').send_keys(PASSWORD)
            driver.find_element(By.NAME, 'captcha').send_keys(str(answer))
            driver.find_element(By.XPATH, "//button[contains(text(), '登入')]").click()

            time.sleep(3)
            if "dashboard" in driver.current_url or "overview" in driver.current_url:
                log("✅ 登入成功")
                break
            driver.refresh()
        except Exception as e:
            log(f"❌ 登入錯誤：{str(e)}")
            traceback.print_exc()
            driver.refresh()
    else:
        log("⛔ 所有登入失敗，結束")
        driver.quit()
        return

    # 匯出報表
    try:
        wait.until(EC.element_to_be_clickable((By.XPATH, "//span[text()='店家報表']"))).click()
        wait.until(EC.element_to_be_clickable((By.XPATH, "//span[text()='營業報表']"))).click()
        wait.until(EC.element_to_be_clickable((By.XPATH, "//span[text()='營業銷售報表']"))).click()
        driver.execute_script("window.scrollBy(0, 500);")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'餐點銷售明細')]"))).click()
        wait.until(EC.element_to_be_clickable((By.XPATH, "//a[text()='餐點銷售狀況']"))).click()
        wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "calendar-button"))).click()
        time.sleep(0.5)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//li[contains(text(), '昨日')]"))).click()

        log("📆 已選擇昨日")
        time.sleep(1)
        wait.until(EC.element_to_be_clickable((By.CLASS_NAME, 'btn-success'))).click()
        time.sleep(5)
    except Exception as e:
        log(f"❌ 報表匯出失敗：{str(e)}")
        return

    # 分析報表
    try:
        yesterday = (dt.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        file_path = os.path.join(DOWNLOAD_DIR, f"餐點銷售狀況_{yesterday}.xlsx")
        df = pd.read_excel(file_path, skiprows=4)
        date_raw = pd.read_excel(file_path, nrows=1, header=None).iloc[0, 1]
        report_date = date_raw.strftime("%Y/%m/%d") if isinstance(date_raw, dt) else str(date_raw).split("~")[0].strip()

        log(f"📅 報表日期：{report_date}")

        # 上傳到 Google Sheet
        SHEET_ID = "1Fof9dfq2DFnRzNBysT1oEPgoyEIqHbJ6W5le-ZebZEk"
        SHEET_NAME_1 = "每日報表"
        SHEET_NAME_2 = "銷售分類統計"
        CREDS_FILE = "wtnc-dailyreport.json"

        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
        client = gspread.authorize(credentials)

        ws1 = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME_1)
        if report_date not in ws1.col_values(1):
            next_row = len(ws1.col_values(1)) + 1
            total = df["銷售總額"].sum()
            ws1.update(f"A{next_row}", [[report_date]])
            ws1.update(f"B{next_row}", [[int(total)]])
            log("✅ 已寫入每日報表")

        # ... 省略 ws2 統計邏輯（你可以加回去）

        log("🎉 任務完成！")
    except Exception as e:
        log(f"❌ 分析/上傳失敗：{str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
