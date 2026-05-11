from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from dotenv import load_dotenv
from datetime import datetime
import re
import os
import time

# --- SETUP & CONFIG ---
load_dotenv()
username_credentials = os.environ.get("USERNAME_NETID")
password_credentials = os.environ.get("PASSWORD_NETID")

def get_best_options(driver):
    # 1. Find all existing booking divs to see what is taken
    bookings = driver.find_elements(By.CSS_SELECTOR, "div.bookingDiv")
    taken_periods = []
    
    for b in bookings:
        title = b.get_attribute("title") # Example: "11-05-2026 19:00 - 21:00..."
        times = re.findall(r"(\d{2}:\d{2})", title)
        if len(times) >= 2:
            taken_periods.append((times[0], times[1]))

    # 2. Identify all free slots (the clickable 'slotfree2' areas)
    free_slots = driver.find_elements(By.CSS_SELECTOR, "div.slotfree2")
    
    options = []
    for slot in free_slots:
        # TimeEdit slots often have data-start and data-end or can be derived
        # For simplicity, we capture the data-object or title to identify the room/time
        obj_id = slot.get_attribute("data-object")
        # In a real scenario, you'd calculate the height/duration of this div
        duration = slot.size['height'] 
        options.append({'element': slot, 'duration': duration, 'id': obj_id})

    # Sort by duration (longest first)
    options.sort(key=lambda x: x['duration'], reverse=True)
    return options[:3]

def select_date(driver, wait, day_month_str):
    day, month = day_month_str.split('-')
    target_year = datetime.now().year
    # Convert "05" to index 4 for May
    target_month_index = int(month) - 1 
    # Remove leading zero for text matching (e.g., "05" -> "5")
    day_text = str(int(day))

    # 1. Click to open the calendar
    calendar_btn = wait.until(EC.element_to_be_clickable((By.ID, "leftresdate")))
    calendar_btn.click()
    
    # 2. Wait for the calendar table to actually be visible in the DOM
    wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "ui-datepicker-calendar")))

    # 3. Flexible XPath: Find the TD that matches month/year, then get the link inside
    xpath_query = (
        f"//td[@data-month='{target_month_index}']"
        f"[@data-year='{target_year}']"
        f"//a[text()='{day_text}']"
    )
    
    try:
        # Use a shorter wait here to check if it's actually there
        date_element = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_query)))
        
        # Scroll it into view just in case
        driver.execute_script("arguments[0].scrollIntoView(true);", date_element)
        time.sleep(0.5)
        
        # Use JavaScript click as a fallback if a standard click is intercepted
        driver.execute_script("arguments[0].click();", date_element)
        
        print(f"Successfully selected date: {day}-{month}-{target_year}")
    except Exception as e:
        print(f"Failed to find or click date {day}-{month}. It might be unselectable or already selected.")
        # Optional: capture a screenshot to debug
        # driver.save_screenshot("calendar_error.png")

def run_reservation():
    # Ask the user for input
    user_input = input("Enter day and month (DD-MM): ")
    target_date = f"{user_input}-{datetime.now().year}"
    driver = webdriver.Chrome()
    wait = WebDriverWait(driver, 10) # Increased wait for stability
    
    try:
        driver.get("https://cloud.timeedit.net/nl_tudelft/web/student/")

        # Click initial button (replace with actual selector)
        login_button = wait.until(EC.element_to_be_clickable((By.ID, "loginAuth")))
        login_button.click()

        # Sign in
        sign_in_with_surfconext = wait.until(EC.element_to_be_clickable((By.XPATH, '/html/body/div/div/div[1]/div/div[3]/div[1]/button')))
        sign_in_with_surfconext.click()

        # Username NetID
        username = wait.until(EC.presence_of_element_located((By.ID, "username")))
        # username = driver.find_element(By.XPATH, '//*[@id="username"]')
        username.send_keys(username_credentials)

        # Password NetID
        password = driver.find_element(By.ID, "password")
        password.send_keys(password_credentials)

        # Log in
        login_button_netid = driver.find_element(By.ID, "submit_button")
        login_button_netid.click()
        time.sleep(2)
        # Navigate to Room Reservation
        wait.until(EC.element_to_be_clickable((By.XPATH, '//a[contains(., "Ruimte reserveren")]'))).click()

        # --- DYNAMIC DATE SELECTION ---
        select_date(driver, wait, user_input)

        # --- Implementation in your flow ---
        top_3 = get_best_options(driver)

        print("\nTop 3 longest available slots:")
        for i, opt in enumerate(top_3):
            print(f"{i+1}. Room/Slot ID: {opt['id']} (Duration score: {opt['duration']})")

        choice = int(input("\nSelect option (1-3): ")) - 1
        selected_slot = top_3[choice]['element']

        # Scroll into view and click
        driver.execute_script("arguments[0].scrollIntoView();", selected_slot)
        ActionChains(driver).move_to_element(selected_slot).click().perform()

    finally:
        time.sleep(5)
        driver.quit()

if __name__ == "__main__":
    run_reservation()