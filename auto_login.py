import time
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
    print("🔄 Starting Auto-Login...")
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        driver.get(kite_instance.login_url())
        wait = WebDriverWait(driver, 10) # Reduced timeout to 10s

        # 1. User ID
        try:
            uid = wait.until(EC.presence_of_element_located((By.ID, "userid")))
            uid.clear(); uid.send_keys(config.ZERODHA_USER_ID)
        except: return None, "User ID Field Not Found"

        # 2. Password
        try:
            pwd = driver.find_element(By.ID, "password")
            pwd.clear(); pwd.send_keys(config.ZERODHA_PASSWORD)
            driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        except: return None, "Password Entry Failed"

        # 3. TOTP
        time.sleep(2)
        try:
            totp = pyotp.TOTP(config.TOTP_SECRET).now()
            inputs = driver.find_elements(By.TAG_NAME, "input")
            totp_input = next((i for i in inputs if i.is_displayed() and i.get_attribute("type") in ["text", "number", "tel", "password"]), None)
            
            if not totp_input: return None, "TOTP Field Not Found"
            
            totp_input.clear(); totp_input.send_keys(totp)
            totp_input.send_keys(Keys.ENTER)
        except Exception as e: return None, f"TOTP Error: {e}"

        # 4. Verify Success
        start = time.time()
        while time.time() - start < 10: # Wait max 10s
            url = driver.current_url
            if "request_token=" in url:
                parsed = urlparse(url)
                token = parse_qs(parsed.query).get('request_token', [None])[0]
                if token: return token, None
            time.sleep(1)
            
        return None, "Login Timed Out (Token not found)"

    except Exception as e:
        return None, str(e)
    finally:
        if driver: driver.quit()
