import time
import os
import pyotp
from urllib.parse import parse_qs, urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        login_url = kite_instance.login_url()
        driver.get(login_url)
        wait = WebDriverWait(driver, 15)

        # --- STEP 1: USER ID ---
        print("➡️ Entering User ID...")
        try:
            user_id_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
            user_id_field.clear()
            user_id_field.send_keys(config.ZERODHA_USER_ID)
            user_id_field.send_keys(Keys.ENTER) # Hit Enter to move to password
        except Exception as e:
            return None, f"Error at User ID step: {str(e)}"

        # --- STEP 2: PASSWORD ---
        print("➡️ Entering Password...")
        try:
            password_field = wait.until(EC.visibility_of_element_located((By.ID, "password")))
            password_field.clear()
            password_field.send_keys(config.ZERODHA_PASSWORD)
            
            # FIX: Explicitly find and click the Login button
            try:
                login_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                driver.execute_script("arguments[0].click();", login_btn)
            except:
                password_field.send_keys(Keys.ENTER)
                
        except Exception as e:
            return None, f"Error at Password step: {str(e)}"

        # --- STEP 3: CHECK FOR LOGIN ERRORS ---
        # Short sleep to let error messages appear
        time.sleep(2)
        try:
            error_msg = driver.find_element(By.CSS_SELECTOR, ".su-alert-error, .error-message, .su-message.error")
            if error_msg.is_displayed():
                print(f"❌ Zerodha Error: {error_msg.text}")
                return None, f"Login Failed: {error_msg.text}"
        except:
            pass # No error found, proceed

        # --- STEP 4: TOTP (2FA) ---
        print("➡️ Entering TOTP...")
        if not config.TOTP_SECRET:
            return None, "Error: TOTP_SECRET is missing in Config."
            
        totp_now = pyotp.TOTP(config.TOTP_SECRET).now()
        
        try:
            # FIX: Broader selector strategy. Zerodha 2FA input is usually type='text' with maxlength='6'
            # We wait for it to be clickable to ensure the transition is done
            totp_selector = (By.CSS_SELECTOR, "input[type='text'][maxlength='6'], input[placeholder*='App Code'], input[label*='App Code']")
            totp_field = wait.until(EC.element_to_be_clickable(totp_selector))
            
            totp_field.send_keys(totp_now)
            totp_field.send_keys(Keys.ENTER)
        except Exception as e:
            # If we timed out here, it means we are still stuck on Password screen
            return None, "Error: Could not find TOTP field. (Possible Incorrect Password?)"

        # --- STEP 5: CAPTURE TOKEN ---
        print("⏳ Waiting for Redirect...")
        try:
            wait.until(EC.url_contains("request_token="))
        except:
            return None, "Error: Redirect timed out. Login may have failed."
        
        current_url = driver.current_url
        parsed = urlparse(current_url)
        request_token = parse_qs(parsed.query).get('request_token', [None])[0]
        
        if request_token:
            print(f"✅ Auto-Login Success! Token: {request_token[:6]}...")
            return request_token, None
        else:
            return None, "Error: Request Token not found in final URL."

    except Exception as e:
        print(f"❌ Script Crash: {e}")
        return None, str(e)
        
    finally:
        if driver:
            driver.quit()
