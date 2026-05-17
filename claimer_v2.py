"""
TU Delft Library - Room Availability Checker & Auto-Reserver
=============================================================
Scans every weekday in the next 14 days, finds free blocks (09:00-17:00)
per room, prefers Australia > Europe > South America > other rooms,
then reserves slots respecting:
  - Minimum block
  - Maximum per reservation
  - Maximum total per session

Environment variables (via .env):
    USERNAME_NETID   - your NetID username
    PASSWORD_NETID   - your NetID password
"""

import logging
import os
import re
import time
from datetime import date, timedelta
from dataclasses import dataclass, field
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

# = Config ==================================
PREFERRED_ROOMS   = ["Australia", "Europe", "South America"]
DISLIKED_ROOMS = ["Albert Einstein", "Steve Jobs", "Gertrude Stein"]
WINDOW_START      = "09:30"
WINDOW_END        = "16:30"
LOOKAHEAD_DAYS    = 14
MIN_DURATION_MIN  = 60    # 60m
MAX_PER_RES_MIN   = 180   # 3h
SESSION_CAP_MIN   = 360   # 6h per run
BASE_URL          = "https://cloud.timeedit.net/nl_tudelft/web/student/"

# = Logging =================================─
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("timeedit_reserve.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# = Time helpers ===============================
def _t(s: str) -> int:
    h, m = map(int, s.split(":"))
    return h * 60 + m

def _s(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"

WIN_START_MIN = _t(WINDOW_START)
WIN_END_MIN   = _t(WINDOW_END)

# = Data structures =============================─
@dataclass
class FreeBlock:
    room_name: str
    room_object_id: str
    day: date
    start: str
    end: str

    @property
    def duration_minutes(self) -> int:
        return _t(self.end) - _t(self.start)

    def __str__(self):
        return (
            f"{self.room_name} | {self.day.isoformat()} | "
            f"{self.start}-{self.end} ({self.duration_minutes} min)"
        )


# Split a FreeBlock into reservable chunks respecting MAX_PER_RES_MIN
def split_into_reservations(block: FreeBlock, remaining_cap: int) -> list[FreeBlock]:
    """
    Given a free block, return a list of sub-blocks each ≤ MAX_PER_RES_MIN,
    all ≥ MIN_DURATION_MIN, and together not exceeding remaining_cap.
    """
    chunks = []
    cursor = _t(block.start)
    end    = _t(block.end)

    while cursor < end and remaining_cap >= MIN_DURATION_MIN:
        avail   = end - cursor
        chunk   = min(avail, MAX_PER_RES_MIN, remaining_cap)
        if chunk < MIN_DURATION_MIN:
            break
        chunks.append(FreeBlock(
            room_name=block.room_name,
            room_object_id=block.room_object_id,
            day=block.day,
            start=_s(cursor),
            end=_s(cursor + chunk),
        ))
        remaining_cap -= chunk
        cursor        += chunk

    return chunks


# = Preference scoring ============================
def preference_score(block: FreeBlock) -> tuple:
    """
    Sort Order:
    1. Day (Soonest first)
    2. Room Preference (Preferred > Normal > Disliked)
    3. Start Time (Earliest in the day first)
    4. Duration (Longest first)
    """
    # 1. Date & Time
    day_val = block.day
    time_val = _t(block.start)

    # 2. Room Tier
    name_lower = block.room_name.lower()
    
    # Tier 0: Preferred
    tier = 1 
    for pref in PREFERRED_ROOMS:
        if pref.lower() in name_lower:
            tier = 0
            break
            
    # Tier 2: Disliked
    for dis in DISLIKED_ROOMS:
        if dis.lower() in name_lower:
            tier = 2
            break

    return (day_val, tier, time_val, -block.duration_minutes)


# = Driver helpers ==============================
def make_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--window-size=1400,900")
    return webdriver.Chrome(options=options)


def _js_click(driver, elem) -> None:
    driver.execute_script("arguments[0].click();", elem)


def login(driver, username: str, password: str) -> None:
    wait = WebDriverWait(driver, 10)
    driver.get(BASE_URL)
    wait.until(EC.element_to_be_clickable((By.ID, "loginAuth"))).click()
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '/html/body/div/div/div[1]/div/div[3]/div[1]/button')
    )).click()
    wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(username)
    driver.find_element(By.ID, "password").send_keys(password)
    driver.find_element(By.ID, "submit_button").click()
    time.sleep(3)
    log.info("Logged in.")


def navigate_to_reserve(driver) -> None:
    wait = WebDriverWait(driver, 10)
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, '/html/body/div[3]/div[2]/div[5]/div/div[3]/a')
    )).click()
    time.sleep(1)
    log.info("On reservation page.")


# = Calendar =================================
def _datepicker_visible(driver) -> bool:
    try:
        return driver.find_element(By.ID, "ui-datepicker-div").is_displayed()
    except NoSuchElementException:
        return False


def select_date_on_calendar(driver, target: date) -> bool:
    wait = WebDriverWait(driver, 10)
    try:
        cal = wait.until(EC.presence_of_element_located((By.ID, "leftresdate")))
        _js_click(driver, cal)
        wait.until(lambda d: _datepicker_visible(d))
        time.sleep(0.3)

        for _ in range(24):
            title_text = driver.find_element(
                By.CSS_SELECTOR, "#ui-datepicker-div .ui-datepicker-title"
            ).text
            cells = driver.find_elements(
                By.CSS_SELECTOR,
                "#ui-datepicker-div td:not(.ui-datepicker-other-month) a.ui-state-default"
            )
            if str(target.day) in [c.text.strip() for c in cells] and str(target.year) in title_text:
                for cell in cells:
                    if cell.text.strip() == str(target.day):
                        _js_click(driver, cell)
                        time.sleep(0.6)
                        return True
            _js_click(driver, driver.find_element(
                By.CSS_SELECTOR, "#ui-datepicker-div .ui-datepicker-next"
            ))
            time.sleep(0.4)

        log.warning(f"Could not navigate datepicker to {target}")
        return False
    except (TimeoutException, NoSuchElementException) as e:
        log.warning(f"Calendar failed for {target}: {e}")
        return False


# = CSS geometry helpers ===========================
def _css_pct(style: str, prop: str) -> float | None:
    """Extract a percentage value from an inline style string, e.g. 'left: 12.5%' → 12.5."""
    import re
    m = re.search(rf"{prop}\s*:\s*([\d.]+)%", style)
    return float(m.group(1)) if m else None


def _slot_times_from_css(style: str, first_hour: int, day_hours: int) -> tuple[int, int] | None:
    """
    TimeEdit encodes slot position as CSS left/width percentages over the
    full day span (first_hour .. first_hour+day_hours).

    left  %  → start offset into the day span
    width %  → duration as fraction of the day span

    Returns (start_min, end_min) as absolute minutes since midnight, or None.
    """
    left  = _css_pct(style, "left")
    width = _css_pct(style, "width")
    if left is None or width is None:
        return None
    day_total_min = day_hours * 60
    start_min = round(first_hour * 60 + (left  / 100) * day_total_min)
    end_min   = round(start_min       + (width / 100) * day_total_min)
    return start_min, end_min


# = Slot scraping ==============================─
def scrape_free_slots_for_day(driver, target: date) -> list[FreeBlock]:
    free_blocks: list[FreeBlock] = []
    try:
        # 1. Map Rooms by vertical position
        room_map = {}
        room_links = driver.find_elements(By.CSS_SELECTOR, "a.boxlink.hour")
        for i, a in enumerate(room_links):
            name = a.find_element(By.CLASS_NAME, "objbase").text.strip()
            onclick = a.get_attribute("onclick") or ""
            m = re.search(r"openObject\(([\d.]+)", onclick)
            obj_id = m.group(1) if m else str(i)
            room_map[i * 40] = {"id": obj_id, "name": name}

        # 2. Get All Reserved Blocks (The "Obstacles")
        reserved_by_room = {} # {obj_id: [(start, end), ...]}
        bookings = driver.find_elements(By.CSS_SELECTOR, "div.bookingDiv")
        
        for b in bookings:
            style = b.get_attribute("style") or ""
            top_m = re.search(r"top:\s*(\d+)px", style)
            if not top_m: continue
            top_val = int(top_m.group(1))
            
            # Match booking to room
            room_info = next((v for k, v in room_map.items() if abs(k - top_val) < 10), None)
            if not room_info: continue

            # Extract time from style (Standard TE: left/width %)
            times = _slot_times_from_css(style, 8, 16) # Adjust 8/16 if your view starts earlier
            if times:
                reserved_by_room.setdefault(room_info["id"], []).append(times)

        # 3. Calculate True Gaps
        for top_px, info in room_map.items():
            room_id = info["id"]
            room_name = info["name"]
            
            # Start with the full allowed window
            available_gaps = [(WIN_START_MIN, WIN_END_MIN)]
            
            # Subtract every reservation from the available gaps
            room_reservations = sorted(reserved_by_room.get(room_id, []))
            for r_start, r_end in room_reservations:
                new_gaps = []
                for g_start, g_end in available_gaps:
                    # If reservation overlaps with this gap
                    if r_start < g_end and r_end > g_start:
                        # Fragment before reservation
                        if r_start > g_start:
                            new_gaps.append((g_start, r_start))
                        # Fragment after reservation
                        if r_end < g_end:
                            new_gaps.append((r_end, g_end))
                    else:
                        new_gaps.append((g_start, g_end))
                available_gaps = new_gaps

            # 4. Convert valid gaps to FreeBlocks
            for start_m, end_m in available_gaps:
                if (end_m - start_m) >= MIN_DURATION_MIN:
                    free_blocks.append(FreeBlock(
                        room_name=room_name,
                        room_object_id=room_id,
                        day=target,
                        start=_s(start_m),
                        end=_s(end_m)
                    ))

    except Exception as e:
        log.warning(f"Scrape error: {e}")
    return free_blocks


# = Reservation ===============================─
def _get_available_values(select_elem) -> list[str]:
    return [o.get_attribute("value") for o in Select(select_elem).options]


def _nearest_value(target_val: str, available: list[str]) -> str:
    """Return the closest available HH:MM value to target_val."""
    t = _t(target_val)
    return min(available, key=lambda v: abs(_t(v) - t) if ":" in v else 9999)


def reserve_block(driver, block: FreeBlock) -> int:
    wait = WebDriverWait(driver, 10)
    log.info(f"Reserving: {block}")

    try:
        if not select_date_on_calendar(driver, block.day):
            return False

        # Click the slot cell closest to our desired start time.
        # Use CSS geometry (same logic as scraping) to find the right cell.
        target_start_min = _t(block.start)
        slot_elems = driver.find_elements(
            By.CSS_SELECTOR, f"div.slotfree2[data-object='{block.room_object_id}']"
        )

        best_slot = None
        best_diff = 9999
        for slot in slot_elems:
            style      = slot.get_attribute("style") or ""
            fh_raw     = slot.get_attribute("data-firsthour") or "480"
            first_hour = int(fh_raw) // 60
            day_hours  = 24 - first_hour
            times      = _slot_times_from_css(style, first_hour, day_hours)
            if times:
                diff = abs(times[0] - target_start_min)
                if diff < best_diff:
                    best_diff, best_slot = diff, slot

        slot_to_click = best_slot or (slot_elems[0] if slot_elems else None)
        if slot_to_click is None:
            log.warning("  No slot elements found for room.")
            return False

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", slot_to_click)
        time.sleep(0.2)
        _js_click(driver, slot_to_click)

        # = Start time ============================
        start_sel_elem = wait.until(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "form#reserveformedit select.timeslotStart")
        ))
        available_starts = _get_available_values(start_sel_elem)
        start_val = (block.start if block.start in available_starts
                     else _nearest_value(block.start, available_starts))
        Select(start_sel_elem).select_by_value(start_val)
        if start_val != block.start:
            log.info(f"  Start adjusted: {block.start} → {start_val}")

        # = End time (wait for options to populate after start change) ====─
        time.sleep(0.6)
        wait.until(lambda d: len(Select(
            d.find_element(By.CSS_SELECTOR, "form#reserveformedit select.timeslotEnd")
        ).options) > 0)
        end_sel_elem = driver.find_element(
            By.CSS_SELECTOR, "form#reserveformedit select.timeslotEnd"
        )
        available_ends = _get_available_values(end_sel_elem)
        end_val = (block.end if block.end in available_ends
                   else _nearest_value(block.end, available_ends))
        Select(end_sel_elem).select_by_value(end_val)
        if end_val != block.end:
            log.info(f"  End adjusted: {block.end} → {end_val}")

        # Verify we still meet the minimum duration after any adjustments
        if _t(end_val) - _t(start_val) < MIN_DURATION_MIN:
            log.warning(f"  Adjusted slot too short ({_t(end_val) - _t(start_val)} min) — skipping")
            return False

        # SIGNATURE MOVE :)
        name_of_the_reservation = driver.find_element(By.CSS_SELECTOR, 'input[name="fe1"]')
        name_of_the_reservation.clear()
        name_of_the_reservation.send_keys("Aeneas")

        time.sleep(0.8)
        wait.until(EC.element_to_be_clickable((By.ID, "continueRes2"))).click()
        time.sleep(1.5)

        # Dismiss any alert the server raised (e.g. "time is occupied")
        try:
            alert = driver.switch_to.alert
            msg   = alert.text.lower()
            alert.accept()
            log.warning(f"  Server rejected: {msg.strip()}")
            
            if "maximale reserveringslengte" in msg or "overschreden" in msg:
                return 2  # GLOBAL QUOTA HIT
            return 1  # ROOM OCCUPIED / TRY NEXT
        except Exception:
            pass  # no alert = success

        log.info(f"✅ Reserved: {block.room_name} {block.day} {start_val}-{end_val}")
        return 0

    except (TimeoutException, NoSuchElementException, WebDriverException) as e:
        # Dismiss any lingering alert before returning
        try:
            driver.switch_to.alert.accept()
        except Exception:
            pass
        log.error(f"Reservation failed: {e}")
        return 1


# = Main ===================================
def weekdays_in_next_n_days(n: int) -> list[date]:
    today = date.today()
    return [
        today + timedelta(days=i)
        for i in range(1, n + 1)
        if (today + timedelta(days=i)).weekday() < 5
    ]


def main():
    load_dotenv()
    username = os.environ.get("USERNAME_NETID")
    password = os.environ.get("PASSWORD_NETID")
    if not username or not password:
        log.error("Missing USERNAME_NETID or PASSWORD_NETID in .env")
        return

    driver = make_driver()
    all_blocks: list[FreeBlock] = []
    reserved_minutes = 0

    try:
        login(driver, username, password)
        navigate_to_reserve(driver)

        target_days = weekdays_in_next_n_days(LOOKAHEAD_DAYS)
        log.info(f"Scanning {len(target_days)} weekdays: {target_days[0]} → {target_days[-1]}")

        # = Scan phase ============================
        for day in target_days:
            log.info(f"--- {day.strftime('%a %d %b')} ---")
            if not select_date_on_calendar(driver, day):
                log.warning(f"  Skipping {day}")
                continue
            blocks = scrape_free_slots_for_day(driver, day)
            if blocks:
                for b in sorted(blocks, key=preference_score):
                    log.info(f"  {b}")
                all_blocks.extend(blocks)
            else:
                log.info("  No free blocks found")

        if not all_blocks:
            log.warning("No suitable free blocks found. Nothing to reserve.")
            return

        # = Reserve phase: live rescrape after each attempt ========─
        # After every reservation attempt (success or failure) we re-scrape
        # the affected day so we only ever act on fresh server state.
        # All rooms are candidates; preference_score() orders them.
        actually_reserved = 0
        attempts          = 0
        session_booked_times = [] # List of (start_min, end_min)

        while actually_reserved < SESSION_CAP_MIN:
            remaining = SESSION_CAP_MIN - actually_reserved
            all_blocks = sorted(all_blocks, key=preference_score)
            
            if not all_blocks:
                break

            chosen_idx = None
            chunk = None
            
            for idx, block in enumerate(all_blocks):
                # Conflict Check: Same day AND overlapping time?
                is_conflict = False
                for ex_start, ex_end, ex_day in session_booked_times:
                    if block.day == ex_day:
                        # Overlap formula: (StartA < EndB) and (EndA > StartB)
                        if _t(block.start) < ex_end and _t(block.end) > ex_start:
                            is_conflict = True
                            break
                
                if is_conflict:
                    continue # Skip this block, try the next one in the sorted list

                # If no conflict, see if it fits our remaining time
                potential_chunks = split_into_reservations(block, remaining)
                if potential_chunks:
                    chosen_idx = idx
                    chunk = potential_chunks[0]
                    break

            if chosen_idx is None:
                log.info("No more non-overlapping blocks found.")
                break

            # Pop it so we don't try it again
            all_blocks.pop(chosen_idx)
            
            attempts += 1
            status = reserve_block(driver, chunk)

            if status == 0:  # SUCCESS
                actually_reserved += chunk.duration_minutes
                session_booked_times.append((_t(chunk.start), _t(chunk.end), chunk.day))
                log.info(f"  Current Session: {actually_reserved} min / {SESSION_CAP_MIN} min")
            elif status == 2:  # GLOBAL QUOTA HIT
                log.error("🛑 STOPPING: You have reached your personal TimeEdit account limit.")
                print("\n" + "=" * 55)
                print(f"  Reserved {actually_reserved} min in {attempts} attempt(s)")
                print("=" * 55 + "\n")
                log.info("\n" + "=" * 55)
                log.info(f"  Reserved {actually_reserved} min in {attempts} attempt(s)")
                log.info("=" * 55 + "\n")
                return 
            else:  # ROOM BUSY / FAIL
                log.info("  Slot unavailable or rejected. Trying next best time/room...")
                continue

        print("\n" + "=" * 55)
        print(f"  Reserved {actually_reserved} min in {attempts} attempt(s)")
        print("=" * 55 + "\n")

    except KeyboardInterrupt:
        log.info("Interrupted.")
    except Exception as e:
        log.error(f"Fatal: {e}", exc_info=True)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
