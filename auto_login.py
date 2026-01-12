import time
import os
import pyotp
from urllib.parse import parse_qs, urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import config

def perform_auto_login(kite_instance):
    print("🔄 Starting Auto-Login Sequence (v3 - Robust)...", flush=True)
    
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
            
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", submit_btn)
            
        except Exception as e:
            return None, f"Password Error: {e}"

        # --- STEP 3: WAIT FOR TOTP PAGE ---
        print("⏳ Waiting for TOTP Screen...", flush=True)
        time.sleep(3) 

        # --- STEP 4: TOTP (With Stale Element Retry) ---
        print("➡️ Generating TOTP...", flush=True)
        if not config.TOTP_SECRET:
            return None, "Error: TOTP_SECRET missing."
            
        totp_now = pyotp.TOTP(config.TOTP_SECRET).now()
        print(f"   🔑 Generated TOTP: {totp_now}", flush=True)
        
        # Retry loop for Stale Element
        totp_success = False
        for attempt in range(3):
            try:
                # 1. Find the Input (Re-find every attempt)
                totp_input = None
                inputs = driver.find_elements(By.TAG_NAME, "input")
                
                for inp in inputs:
                    if not inp.is_displayed(): continue
                    t = inp.get_attribute("type")
                    if t in ["text", "number", "tel", "password"]:
                        totp_input = inp
                        break
                
                if not totp_input:
                    time.sleep(1)
                    continue

                # 2. Enter Code
                totp_input.clear()
                totp_input.send_keys(totp_now)
                time.sleep(0.5)
                
                # 3. Submit (Try clicking button first, then Enter key)
                try:
                    continue_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                    driver.execute_script("arguments[0].click();", continue_btn)
                    print("   👉 Clicked Continue (JS)", flush=True)
                except:
                    totp_input.send_keys(Keys.ENTER)
                    print("   👉 Sent ENTER Key", flush=True)
                
                totp_success = True
                break # Exit retry loop if successful

            except StaleElementReferenceException:
                print(f"   ⚠️ Stale Element (Attempt {attempt+1}/3). Retrying...", flush=True)
                time.sleep(1)
            except Exception as e:
                print(f"   ⚠️ TOTP Attempt Error: {e}", flush=True)
                time.sleep(1)

        if not totp_success:
            return None, "Failed to enter TOTP after 3 attempts."

        # --- STEP 5: VERIFY SUCCESS ---
        print("⏳ Waiting for Success...", flush=True)
        start_time = time.time()
        while time.time() - start_time < 30:
            try:
                current_url = driver.current_url
                
                if "request_token=" in current_url:
                    parsed = urlparse(current_url)
                    token = parse_qs(parsed.query).get('request_token', [None])[0]
                    if token:
                        print(f"✅ Token Captured: {token[:6]}...", flush=True)
                        return token, None
                
                try:
                    # Check for Success Text or Token on Page (from main.py callback)
                    page_text = driver.find_element(By.TAG_NAME, "body").text
                    
                    if "System Auto-Login Token Received" in page_text:
                        # Extract token from the page body if main.py printed it
                        import re
                        match = re.search(r"Token:\s*([a-zA-Z0-9]+)", page_text)
                        if match:
                            token = match.group(1)
                            print(f"✅ Token Scraped from Page: {token[:6]}...", flush=True)
                            return token, None

                    if "System Online" in page_text or "WATCHLIST" in page_text:
                        return "SKIP_SESSION", None
                    
                    if "Invalid TOTP" in page_text: return None, "Invalid TOTP."
                    if "Session expired" in page_text: return None, "Session Expired."
                except: pass
                
            except Exception as e:
                print(f"   [Warning] Loop Error: {e}", flush=True)
            
            time.sleep(1)

        return None, "Login Timed Out."

    except Exception as e:
        print(f"❌ System Error: {e}", flush=True)
        return None, str(e)
        
    finally:
        if driver: driver.quit()
