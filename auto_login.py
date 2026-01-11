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
    print("🔄 Starting Auto-Login Sequence (Debug Mode)...")
    
    # 1. Setup Headless Chrome with Anti-Detection flags
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
            time.sleep(1) # Brief pause for UI reaction
        except Exception as e:
            return None, f"Error finding User ID field: {str(e)}"

        # --- STEP 2: PASSWORD ---
        print("➡️ Entering Password...")
        try:
            # Check if we are already on password field or need to hit enter
            try:
                password_field = driver.find_element(By.ID, "password")
            except:
                user_id_field.send_keys(Keys.ENTER)
                password_field = wait.until(EC.visibility_of_element_located((By.ID, "password")))
            
            password_field.clear()
            password_field.send_keys(config.ZERODHA_PASSWORD)
            time.sleep(1) 
            
            # FORCE CLICK SUBMIT
            print("➡️ Clicking Login Button...")
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", submit_btn)
            
        except Exception as e:
            return None, f"Error at Password step: {str(e)}"

        # --- STEP 3: ANALYZE RESULT (The Fix) ---
        print("⏳ Analyzing next screen...")
        time.sleep(3) # Wait for page transition
        
        # A. Check for Explicit Error (Red Text)
        try:
            error_el = driver.find_element(By.CSS_SELECTOR, ".su-message.error, .error-message")
            if error_el.is_displayed():
                err_text = error_el.text
                print(f"❌ Zerodha Reported Error: {err_text}")
                return None, f"Login Failed: {err_text}"
        except:
            pass

        # B. Check for Security Question (New Device Issue)
        try:
            # Look for text input that is NOT the password field or TOTP field
            sec_q = driver.find_elements(By.XPATH, "//input[@type='password' and contains(@placeholder, 'Answer')]")
            if sec_q:
                print("❌ Stopped at Security Question.")
                return None, "Zerodha is asking a Security Question (New Device). Cannot Auto-Login."
        except:
            pass

        # --- STEP 4: TOTP ---
        print("➡️ Attempting TOTP Entry...")
        try:
            if not config.TOTP_SECRET:
                return None, "Error: TOTP_SECRET missing."
            
            totp_now = pyotp.TOTP(config.TOTP_SECRET).now()
            
            # Look for the 6-digit App Code field
            totp_field = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='text'][maxlength='6']")))
            totp_field.clear()
            totp_field.send_keys(totp_now)
            
            # Submit TOTP (Wait 1s before submitting)
            time.sleep(1)
            totp_field.send_keys(Keys.ENTER)
            
        except Exception as e:
            # DEBUG: Print what page we are actually on
            current_url = driver.current_url
            page_text = driver.find_element(By.TAG_NAME, "body").text[:300].replace('\n', ' ')
            print(f"❌ Failed to find TOTP. Current Page: {current_url}")
            print(f"📄 Page Content Dump: {page_text}")
            return None, "Could not find TOTP field. Check Logs for Page Dump."

        # --- STEP 5: TOKEN ---
        print("⏳ Waiting for Redirect...")
        try:
            wait.until(EC.url_contains("request_token="))
            current_url = driver.current_url
            parsed = urlparse(current_url)
            request_token = parse_qs(parsed.query).get('request_token', [None])[0]
            
            if request_token:
                print(f"✅ Auto-Login Success! Token: {request_token[:6]}...")
                return request_token, None
        except:
            return None, "Login timed out after entering TOTP."

    except Exception as e:
        print(f"❌ System Error: {e}")
        return None, str(e)
        
    finally:
        if driver:
            driver.quit()
