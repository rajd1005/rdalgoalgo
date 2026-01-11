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
    
    # 1. Setup Headless Chrome
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    driver = None
    try:
        # Install and setup Chrome Driver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        login_url = kite_instance.login_url()
        driver.get(login_url)
        wait = WebDriverWait(driver, 15)

        # 2. Enter User ID
        print("➡️ Entering User ID...")
        try:
            user_id_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
            user_id_field.send_keys(config.ZERODHA_USER_ID)
        except:
            return None, "Error: Could not find User ID field."
        
        try:
             driver.find_element(By.ID, "password")
        except:
             user_id_field.submit()

        # 3. Enter Password
        print("➡️ Entering Password...")
        try:
            password_field = wait.until(EC.visibility_of_element_located((By.ID, "password")))
            password_field.send_keys(config.ZERODHA_PASSWORD)
            password_field.submit()
        except:
            return None, "Error: Could not find Password field."

        # 4. Enter TOTP (2FA)
        print("➡️ Entering TOTP...")
        if not config.TOTP_SECRET:
            return None, "Error: TOTP_SECRET is missing in Config."
            
        totp_now = pyotp.TOTP(config.TOTP_SECRET).now()
        
        try:
            # Wait for the numeric input field
            totp_field = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='text'][maxlength='6']")))
            totp_field.send_keys(totp_now)
            
            # Submit if needed
            try:
                totp_field.submit()
            except:
                pass
        except:
             # Snapshot the page source for debugging if needed
             return None, "Error: Could not find TOTP field (2FA)."

        # 5. Wait for Redirect and Capture Token
        print("⏳ Waiting for Redirect...")
        try:
            wait.until(EC.url_contains("request_token="))
        except:
            return None, "Error: Login timed out. Incorrect Password or TOTP?"
        
        current_url = driver.current_url
        parsed = urlparse(current_url)
        request_token = parse_qs(parsed.query).get('request_token', [None])[0]
        
        if request_token:
            print(f"✅ Auto-Login Success! Token: {request_token[:6]}...")
            return request_token, None
        else:
            return None, "Error: Request Token not found in URL."

    except Exception as e:
        print(f"❌ Auto-Login Failed: {e}")
        return None, str(e)
        
    finally:
        if driver:
            driver.quit()
