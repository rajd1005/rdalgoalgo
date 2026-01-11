import time
import os
import pyotp
from urllib.parse import parse_qs, urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import config

def perform_auto_login(kite_instance):
    print("🔄 Starting Auto-Login Sequence...")
    
    # Chrome Options for Headless Environment
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    
    # Use webdriver_manager to get the driver matching the installed Chrome
    service = Service(ChromeDriverManager().install())
    
    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        login_url = kite_instance.login_url()
        driver.get(login_url)
        wait = WebDriverWait(driver, 15)

        # 1. Enter User ID
        print("➡️ Entering User ID...")
        user_id_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
        user_id_field.send_keys(config.ZERODHA_USER_ID)
        
        try:
             driver.find_element(By.ID, "password")
        except:
             user_id_field.submit()

        # 2. Enter Password
        print("➡️ Entering Password...")
        password_field = wait.until(EC.visibility_of_element_located((By.ID, "password")))
        password_field.send_keys(config.ZERODHA_PASSWORD)
        password_field.submit()

        # 3. Enter TOTP
        print("➡️ Entering TOTP...")
        # Generates TOTP using the secret from config
        totp_now = pyotp.TOTP(config.TOTP_SECRET).now()
        
        # Wait for TOTP field (usually type="text" with maxlength="6")
        totp_field = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='text'][maxlength='6']")))
        totp_field.send_keys(totp_now)
        
        # 4. Wait for Redirect and Capture Token
        print("⏳ Waiting for Redirect...")
        wait.until(EC.url_contains("request_token="))
        
        current_url = driver.current_url
        parsed = urlparse(current_url)
        request_token = parse_qs(parsed.query).get('request_token', [None])[0]
        
        if request_token:
            print(f"✅ Auto-Login Success! Token: {request_token[:6]}...")
            return request_token
        else:
            raise Exception("Request Token not found in redirect URL")

    except Exception as e:
        print(f"❌ Auto-Login Failed: {e}")
        return None
        
    finally:
        if driver:
            driver.quit()
