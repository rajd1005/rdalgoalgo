import time
import os
import pyotp
from urllib.parse import parse_qs, urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import config

def perform_auto_login(kite_instance):
    print("🔄 Starting Auto-Login Sequence (v7 - Active Element)...", flush=True)
    
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    # Standard User Agent to avoid detection
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        login_url = kite_instance.login_url()
        print(f"🔗 Opening Login URL...", flush=True)
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
            return None, f"User ID Error: {e}"

        # --- STEP 2: PASSWORD ---
        try:
            print("➡️ Entering Password...", flush=True)
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
            return None, f"Password Error: {e}"

        # --- STEP 3: WAIT FOR TOTP PAGE ---
        print("⏳ Waiting for TOTP Screen...", flush=True)
        # Wait until URL does NOT contain 'login' or wait for a specific TOTP element
        time.sleep(5) 

        # --- STEP 4: TOTP ---
        print("➡️ Generating TOTP...", flush=True)
        if not config.TOTP_SECRET: return None, "Error: TOTP_SECRET missing."
            
        totp_now = pyotp.TOTP(config.TOTP_SECRET).now()
        print(f"   🔑 Generated TOTP: {totp_now}", flush=True)
        
        totp_success = False
        
        # Retry loop with Fallbacks
        for attempt in range(4):
            try:
                print(f"   🔎 Attempt {attempt+1}: Looking for input...", flush=True)
                
                # Strategy A: Find Visible Inputs
                inputs = driver.find_elements(By.TAG_NAME, "input")
                target_input = None
                
                for inp in inputs:
                    try:
                        # Find the first visible input that isn't a button
                        if inp.is_displayed() and inp.get_attribute("type") not in ['hidden', 'submit', 'button', 'checkbox']:
                            target_input = inp
                            break
                    except: continue 
                
                # Strategy B: Active Element Fallback
                if not target_input and attempt > 1:
                    print("   ⚠️ No inputs found. Trying Active Element (Blind Type)...", flush=True)
                    try:
                        driver.switch_to.active_element.send_keys(totp_now)
                        time.sleep(0.5)
                        driver.switch_to.active_element.send_keys(Keys.ENTER)
                        totp_success = True
                        print("   👉 Sent Keys to Active Element.", flush=True)
                        break
                    except Exception as ae:
                        print(f"   ❌ Active Element Failed: {ae}", flush=True)

                if target_input:
                    target_input.click()
                    target_input.clear()
                    target_input.send_keys(totp_now)
                    time.sleep(0.5)
                    
                    # Submit
                    try:
                        # Try finding a 'Continue' button specifically
                        buttons = driver.find_elements(By.TAG_NAME, "button")
                        continue_btn = next((b for b in buttons if b.is_displayed() and b.get_attribute("type") == "submit"), None)
                        
                        if continue_btn:
                            continue_btn.click()
                            print("   👉 Clicked Submit Button.", flush=True)
                        else:
                            target_input.send_keys(Keys.ENTER)
                            print("   👉 Sent ENTER Key.", flush=True)
                    except:
                        target_input.send_keys(Keys.ENTER)
                    
                    totp_success = True
                    break
                else:
                    # DEBUG LOGGING IF FAILED
                    print(f"   ⚠️ Input not found. Page Title: '{driver.title}'", flush=True)
                    if attempt == 2:
                        print(f"   📜 PAGE SOURCE DUMP (First 500 chars):\n{driver.page_source[:500]}", flush=True)
                    time.sleep(2)

            except StaleElementReferenceException:
                print(f"   ⚠️ Stale Element. Page refreshed. Retrying...", flush=True)
                time.sleep(2)
            except Exception as e:
                print(f"   ⚠️ Error: {e}", flush=True)
                time.sleep(1)

        if not totp_success:
            return None, f"Failed to enter TOTP. Stuck on: {driver.title}"

        # --- STEP 5: VERIFY SUCCESS ---
        print("⏳ Waiting for Dashboard Redirect...", flush=True)
        start_time = time.time()
        while time.time() - start_time < 20:
            try:
                current_url = driver.current_url
                
                # Check 1: Token in URL
                if "request_token=" in current_url:
                    parsed = urlparse(current_url)
                    token = parse_qs(parsed.query).get('request_token', [None])[0]
                    if token:
                        print(f"✅ Token Captured: {token[:6]}...", flush=True)
                        return token, None
                
                # Check 2: Success Text on Page
                try:
                    page_text = driver.find_element(By.TAG_NAME, "body").text
                    if "System Auto-Login Token Received" in page_text:
                        import re
                        match = re.search(r"Token:\s*([a-zA-Z0-9]+)", page_text)
                        if match:
                            token = match.group(1)
                            print(f"✅ Token Scraped: {token[:6]}...", flush=True)
                            return token, None

                    if "System Online" in page_text or "WATCHLIST" in page_text:
                        return "SKIP_SESSION", None
                    
                    if "Invalid TOTP" in page_text: return None, "Invalid TOTP."
                except: pass
                
            except Exception as e: pass
            time.sleep(1)

        return None, "Login Timed Out (Token not found)."

    except Exception as e:
        print(f"❌ System Error: {e}", flush=True)
        return None, str(e)
        
    finally:
        if driver: driver.quit()
