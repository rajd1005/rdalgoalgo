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
    print("🔄 Starting Auto-Login Sequence (Robust Mode)...")
    
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
            time.sleep(1)
        except Exception as e:
            return None, f"Error at User ID: {str(e)}"

        # --- STEP 2: PASSWORD ---
        print("➡️ Entering Password...")
        try:
            try:
                password_field = driver.find_element(By.ID, "password")
            except:
                user_id_field.send_keys(Keys.ENTER)
                password_field = wait.until(EC.visibility_of_element_located((By.ID, "password")))
            
            password_field.clear()
            password_field.send_keys(config.ZERODHA_PASSWORD)
            time.sleep(1) 
            
            # Click Login
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", submit_btn)
            
        except Exception as e:
            return None, f"Error at Password: {str(e)}"

        # --- STEP 3: WAIT FOR TOTP PAGE ---
        print("⏳ Waiting for TOTP Page...")
        time.sleep(3) 

        # Check for errors first
        try:
            err = driver.find_element(By.CSS_SELECTOR, ".su-message.error, .error-message")
            if err.is_displayed():
                return None, f"Login Failed: {err.text}"
        except: pass

        # --- STEP 4: TOTP (UPDATED STRATEGY) ---
        print("➡️ Finding TOTP Input...")
        if not config.TOTP_SECRET:
            return None, "Error: TOTP_SECRET missing."
            
        totp_now = pyotp.TOTP(config.TOTP_SECRET).now()
        
        try:
            # STRATEGY: Find ANY visible text/number input on this page
            # The TOTP page typically only has ONE input field.
            totp_input = None
            inputs = driver.find_elements(By.TAG_NAME, "input")
            
            for inp in inputs:
                # Skip hidden inputs
                if not inp.is_displayed(): continue
                
                # Check types
                t = inp.get_attribute("type")
                if t in ["text", "number", "tel", "password"]:
                    totp_input = inp
                    print(f"   ✅ Found input field (Type: {t})")
                    break
            
            if not totp_input:
                # Fallback: specific wait
                totp_input = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='number'], input[type='text']")))

            totp_input.clear()
            totp_input.send_keys(totp_now)
            time.sleep(1)
            
            # Press Continue/Submit
            try:
                # Try finding a button with type="submit"
                continue_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                continue_btn.click()
                print("   Clicked Continue.")
            except:
                totp_input.send_keys(Keys.ENTER)
                print("   Hit Enter.")

        except Exception as e:
            # Only dump if strictly necessary
            return None, "Error: Could not find visible input field for TOTP."

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
