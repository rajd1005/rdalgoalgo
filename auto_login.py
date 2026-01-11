import time
import os
import pyotp
from urllib.parse import parse_qs, urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import config

def generate_totp():
    if not config.TOTP_SECRET:
        raise Exception("TOTP_SECRET not found in config")
    return pyotp.TOTP(config.TOTP_SECRET).now()

def perform_auto_login(kite_instance):
    print("🔄 Starting Auto-Login Sequence...")
    
    # 1. Setup Headless Chrome
    options = webdriver.ChromeOptions()
    options.add_argument("--headless") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        login_url = kite_instance.login_url()
        driver.get(login_url)
        wait = WebDriverWait(driver, 15)

        # 2. Enter User ID
        print("➡️ Entering User ID...")
        user_id_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
        user_id_field.send_keys(config.ZERODHA_USER_ID)
        
        # Click Login/Continue is sometimes implicitly handled by hitting enter, 
        # but let's check for password field visibility next.
        # If the password field is already there, good. If not, hit enter/submit.
        try:
             driver.find_element(By.ID, "password")
        except:
             user_id_field.submit()

        # 3. Enter Password
        print("➡️ Entering Password...")
        password_field = wait.until(EC.visibility_of_element_located((By.ID, "password")))
        password_field.send_keys(config.ZERODHA_PASSWORD)
        password_field.submit()

        # 4. Enter TOTP
        print("➡️ Entering TOTP...")
        # Wait for the TOTP field. It often has type="text" and maxlength="6" or is the only input left.
        # We look for the field that accepts the App Code.
        # Note: Selectors might vary slightly, this targets the standard numeric input for 2FA.
        totp_field = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='text'][maxlength='6']")))
        
        totp_code = generate_totp()
        totp_field.send_keys(totp_code)
        # Usually auto-submits upon filling 6 digits, if not, we can try submitting form
        try:
            totp_field.submit()
        except: pass

        # 5. Wait for Redirect and Capture Token
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
        # Save screenshot for debugging if needed
        # driver.save_screenshot("login_error.png")
        return None
        
    finally:
        driver.quit()
