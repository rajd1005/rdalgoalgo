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
    print("🔄 Starting Auto-Login Sequence (v2)...", flush=True)
    
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    # Mask User Agent to look like a real browser
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        login_url = kite_instance.login_url()
        print(f"🔗 Opening Login URL: {login_url[:30]}...", flush=True)
        driver.get(login_url)
        wait = WebDriverWait(driver, 20)

        # --- STEP 1: USER ID ---
        try:
            print("➡️ Entering User ID...", flush=True)
            user_id_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
            user_id_field.clear()
            user_id_field.send_keys(config.ZERODHA_USER_ID)
            time.sleep(1)
        except Exception as e:
            return None, f"User ID Field Error: {e}"

        # --- STEP 2: PASSWORD ---
        try:
            print("➡️ Entering Password...", flush=True)
            try:
                password_field = driver.find_element(By.ID, "password")
            except:
                # Sometimes password field is hidden until UserID is submitted
                user_id_field.send_keys(Keys.ENTER)
                password_field = wait.until(EC.visibility_of_element_located((By.ID, "password")))
            
            password_field.clear()
            password_field.send_keys(config.ZERODHA_PASSWORD)
            time.sleep(1) 
            
            # Click Login
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", submit_btn)
            
        except Exception as e:
            return None, f"Password Field Error: {e}"

        # --- STEP 3: WAIT FOR TOTP PAGE ---
        print("⏳ Waiting for TOTP Screen...", flush=True)
        time.sleep(3) 

        # Check for immediate password errors
        try:
            err = driver.find_element(By.CSS_SELECTOR, ".su-message.error, .error-message")
            if err.is_displayed():
                return None, f"Login Failed (Password Step): {err.text}"
        except: pass

        # --- STEP 4: TOTP ---
        print("➡️ Generating TOTP...", flush=True)
        if not config.TOTP_SECRET:
            return None, "Error: TOTP_SECRET missing in config."
            
        totp_now = pyotp.TOTP(config.TOTP_SECRET).now()
        print(f"   🔑 Generated TOTP: {totp_now}", flush=True)
        
        try:
            # Find the active TOTP input field
            totp_input = None
            inputs = driver.find_elements(By.TAG_NAME, "input")
            
            for inp in inputs:
                if not inp.is_displayed(): continue
                # Zerodha TOTP field usually has type text/number or specific attributes
                t = inp.get_attribute("type")
                if t in ["text", "number", "tel", "password"]:
                    totp_input = inp
                    break
            
            if not totp_input:
                # Debug dump if field not found
                return None, "Error: Could not find TOTP input box."

            totp_input.clear()
            totp_input.send_keys(totp_now)
            time.sleep(1)
            
            # Submit TOTP
            try:
                continue_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                driver.execute_script("arguments[0].click();", continue_btn)
                print("   👉 Clicked Continue (JS)", flush=True)
            except:
                totp_input.send_keys(Keys.ENTER)
                print("   👉 Sent ENTER Key", flush=True)

        except Exception as e:
            return None, f"TOTP Entry Error: {e}"

        # --- STEP 5: VERIFY SUCCESS (Enhanced) ---
        print("⏳ Waiting for Redirect/Success (Max 30s)...", flush=True)
        
        start_time = time.time()
        while time.time() - start_time < 30:
            try:
                current_url = driver.current_url
                
                # CASE A: Request Token in URL (Redirection Started)
                if "request_token=" in current_url:
                    parsed = urlparse(current_url)
                    token = parse_qs(parsed.query).get('request_token', [None])[0]
                    if token:
                        print(f"✅ Success! Token Captured: {token[:6]}...", flush=True)
                        return token, None
                
                # CASE B: Dashboard Text (Redirection Complete)
                try:
                    page_text = driver.find_element(By.TAG_NAME, "body").text
                    if "System Online" in page_text or "WATCHLIST" in page_text or "Trade" in page_text:
                        print("✅ Success! Dashboard Detected.", flush=True)
                        return "SKIP_SESSION", None
                    
                    # CASE C: Failure Messages
                    if "Invalid TOTP" in page_text:
                        return None, "Login Failed: Invalid TOTP."
                    if "Session expired" in page_text:
                        return None, "Login Failed: Session Expired."
                except:
                    pass
                
                # Debug Log every 5 seconds
                elapsed = int(time.time() - start_time)
                if elapsed > 0 and elapsed % 5 == 0:
                    print(f"   ... Waiting ({elapsed}s). URL: {current_url}", flush=True)
            
            except Exception as loop_e:
                print(f"   [Warning] Loop Check Error: {loop_e}", flush=True)

            time.sleep(1)

        # Timeout Info
        final_url = driver.current_url
        print(f"❌ Timed Out. Final URL: {final_url}", flush=True)
        return None, "Login Timed Out. (Check Redirect URL config)"

    except Exception as e:
        print(f"❌ System Error: {e}", flush=True)
        return None, str(e)
        
    finally:
        if driver:
            driver.quit()
