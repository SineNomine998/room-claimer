from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from dotenv import load_dotenv
import os
import time

load_dotenv()

username_credentials = os.environ["USERNAME_NETID"]
password_credentials = os.environ["PASSWORD_NETID"]

# Set up the driver (assuming Chrome)
driver = webdriver.Chrome()

# Navigate to the website
driver.get("https://cloud.timeedit.net/nl_tudelft/web/student/")

# Wait for page to load
wait = WebDriverWait(driver, 3)

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

# Wait for login to complete
time.sleep(2)

# Click on "Ruimte reserveren"
ruimte_reserveren_button = wait.until(EC.element_to_be_clickable((By.XPATH, '/html/body/div[3]/div[2]/div[5]/div/div[3]/a')))
ruimte_reserveren_button.click()

# Pick a timeslot:

# 1. Click on the calendar
calendar = wait.until(EC.element_to_be_clickable((By.ID, "leftresdate")))
calendar.click()

# 2. Select the date
selected_date = wait.until(EC.element_to_be_clickable((By.XPATH, '/html/body/div[18]/table/tbody/tr[4]/td[7]/a')))  # The last day possible? (in my case 23-05-2026)
selected_date.click()

# 3. Select a timeslot from a room (Australia)
australia_slot = wait.until(EC.element_to_be_clickable(
    (By.CSS_SELECTOR, "div.slotfree2[data-object='429418.4']")
))

ActionChains(driver).move_to_element(australia_slot).click().perform()
# print(driver.page_source)

# Wait until visible start dropdown exists
start_select_element = wait.until(
    EC.visibility_of_element_located(
        (By.CSS_SELECTOR, "form#reserveformedit select.timeslotStart")
    )
)

# Wait until visible end dropdown exists
end_select_element = wait.until(
    EC.visibility_of_element_located(
        (By.CSS_SELECTOR, "form#reserveformedit select.timeslotEnd")
    )
)

# Use Select on the visible dropdowns
start_dropdown = Select(start_select_element)
start_dropdown.select_by_value("10:00")

# Wait for end options to populate
wait.until(lambda d: len(Select(
    d.find_element(By.CSS_SELECTOR, "form#reserveformedit select.timeslotEnd")
).options) > 0)

end_select_element = driver.find_element(By.CSS_SELECTOR, "form#reserveformedit select.timeslotEnd")
end_dropdown = Select(end_select_element)
end_dropdown.select_by_value("13:00")

time.sleep(1)

reserve_btn = wait.until(EC.element_to_be_clickable((By.ID, "continueRes2")))
reserve_btn.click()

time.sleep(1)

print("Times selected successfully")

print("Reservation attempted.")

# Close the driver
driver.quit()