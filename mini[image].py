import cv2
import numpy as np
import mss
import pygetwindow as gw
import time
import os
import glob
import sys
import tkinter
from tkinter import messagebox
import keyboard
import pydirectinput
import ctypes

# ================= DPI FIX (แก้ปัญหา Resolution เพี้ยน) =================
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()
# ====================================================================

# ================= CONFIG =================
TARGET_WINDOW_KEYWORD = "Seven Knights"  # เปลี่ยนคำนี้เป็นชื่อเกมของคุณ
VIEW_SCALE = 0.5
CHAR_IMAGE_FOLDER = "image"
BACK_CARD_FILENAME = "back.png"

BTN_RESTART_FILENAME = "btn_restart.png"
BTN_EXIT_FILENAME = "btn_exit.png"

GRID_ROWS = 3
GRID_COLS = 8
TOTAL_CARDS = 24

MSE_MATCH_THRESHOLD = 3000 
MIN_DIFF_TO_UPDATE = 6500 

AUTO_PLAY_ENABLED = False



# ==========================================

# ================= UTILS ==================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS # type: ignore
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def mse(imageA, imageB):
    if imageA is None or imageB is None or imageA.size == 0 or imageB.size == 0: return float("inf")
    h, w = imageA.shape[:2]
    imageB = cv2.resize(imageB, (w, h))
    err = np.sum((imageA.astype("float") - imageB.astype("float")) ** 2)
    err /= float(imageA.shape[0] * imageA.shape[1])
    return err

def click_card(slot_x, slot_y, slot_w, slot_h, game_window):
    # คำนวณจุดกึ่งกลาง
    center_x = slot_x + (slot_w // 2)
    center_y = slot_y + (slot_h // 2)
    
    # แปลงพิกัดสัมพัทธ์ในหน้าต่าง -> พิกัดหน้าจอจริง
    # เพิ่ม Offset เล็กน้อย (+5, +35) เพื่อข้ามขอบหน้าต่าง (Title bar)
    abs_x = game_window.left + 5 + center_x
    abs_y = game_window.top + 35 + center_y

    try:
        pydirectinput.moveTo(int(abs_x), int(abs_y))
        pydirectinput.click()
    except Exception as e:
        print(f"Click Error: {e}")

def find_window_fuzzy(keyword):
    for title in gw.getAllTitles():
        if keyword.lower() in title.lower() and title.strip() != "":
            try: return gw.getWindowsWithTitle(title)[0]
            except: continue
    return None

# ================= LOGIC ==================
character_db = [] 
btn_restart_img = None
btn_exit_img = None

def load_resources():
    global character_db, btn_restart_img, btn_exit_img
    character_db = []
    
    # 1. Load Back Card
    full_back_path = os.path.join(resource_path(CHAR_IMAGE_FOLDER), BACK_CARD_FILENAME)
    back_ref = None
    if os.path.exists(full_back_path):
        back_ref = cv2.imread(full_back_path)
    else:
        print(f"⚠️ Warning: ไม่พบไฟล์ {BACK_CARD_FILENAME}")

    # 2. Load Buttons for Auto Reset
    path_restart = os.path.join(resource_path(CHAR_IMAGE_FOLDER), BTN_RESTART_FILENAME)
    path_exit = os.path.join(resource_path(CHAR_IMAGE_FOLDER), BTN_EXIT_FILENAME)
    
    if os.path.exists(path_restart):
        btn_restart_img = cv2.imread(path_restart, 0)
        print(f"✅ Loaded Restart Button")
    else:
        print(f"⚠️ Warning: ไม่พบไฟล์ปุ่ม {BTN_RESTART_FILENAME}")

    if os.path.exists(path_exit):
        btn_exit_img = cv2.imread(path_exit, 0)
        print(f"✅ Loaded Exit Button")
    else:
        print(f"⚠️ Warning: ไม่พบไฟล์ปุ่ม {BTN_EXIT_FILENAME}")

    # 3. Load Character Images
    folder_path = resource_path(CHAR_IMAGE_FOLDER)
    if not os.path.exists(folder_path):
        print(f"⚠️ Warning: ไม่พบโฟลเดอร์ '{CHAR_IMAGE_FOLDER}'")
        return back_ref
    
    files_grabbed = []
    for ext in ('*.png', '*.jpg', '*.jpeg'):
        files_grabbed.extend(glob.glob(os.path.join(folder_path, ext)))
    
    print(f"📂 โหลดรูปตัวละคร...")
    COMPARE_SIZE = (64, 64) 
    
    ignore_files = [BTN_RESTART_FILENAME, BTN_EXIT_FILENAME]
    
    for f in files_grabbed:
        filename = os.path.basename(f)
        if filename in ignore_files: continue 

        img = cv2.imread(f)
        if img is not None:
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img_small = cv2.resize(img_gray, COMPARE_SIZE)
            character_db.append((filename, img_small, img))
            
    print(f"✅ พร้อมใช้งาน {len(character_db)} ตัวละคร")
    return back_ref

def check_auto_reset(frame, reset_func):
    """ฟังก์ชันเช็คปุ่ม Reset หรือ Exit บนหน้าจอ"""
    if btn_restart_img is None and btn_exit_img is None: return

    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    buttons = [
        ("RESTART", btn_restart_img),
        ("EXIT", btn_exit_img)
    ]
    
    found_any = False
    
    for name, template in buttons:
        if template is None: continue
        
        # Match Template
        res = cv2.matchTemplate(gray_frame, template, cv2.TM_CCOEFF_NORMED)
        threshold = 0.85 
        loc = np.where(res >= threshold)
        
        if len(loc[0]) > 0:
            print(f"🔄 Detect System Button: {name} -> Auto Reset Grid")
            found_any = True
            
            break
            
    if found_any:
        reset_func()
        time.sleep(2) 

def identify_card_fast(roi_img):
    if not character_db: return False, roi_img
    COMPARE_SIZE = (64, 64)
    roi_gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
    roi_small = cv2.resize(roi_gray, COMPARE_SIZE)
    best_score = float('inf')
    best_match_img = None
    
    for (_, db_small, db_color) in character_db:
        err = np.sum((roi_small.astype("float") - db_small.astype("float")) ** 2)
        err /= float(COMPARE_SIZE[0] * COMPARE_SIZE[1])
        if err < best_score:
            best_score = err
            best_match_img = db_color

    if best_score < MSE_MATCH_THRESHOLD:
        return True, best_match_img
    else:
        return False, roi_img

def find_contours_hybrid(frame):
    rects = []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([90, 50, 50])
    upper_blue = np.array([130, 255, 255])
    mask_blue = cv2.inRange(hsv, lower_blue, upper_blue)
    mask_blue = cv2.morphologyEx(mask_blue, cv2.MORPH_CLOSE, np.ones((5,5), np.uint8))
    cnts_blue, _ = cv2.findContours(mask_blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts_blue:
        x, y, w, h = cv2.boundingRect(c)
        if w > 30 and h > 40 and h/w > 1.1: rects.append((x, y, w, h))

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, thresh_bright = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
    cnts_bright, _ = cv2.findContours(thresh_bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts_bright:
        x, y, w, h = cv2.boundingRect(c)
        if w > 30 and h > 40 and w < frame.shape[1]/2 and h/w > 1.1: rects.append((x, y, w, h))
    return rects

def reconstruct_grid(rects):
    final_rects = []
    for r in rects:
        found = False
        for fr in final_rects:
            if abs(r[0]-fr[0]) < 10 and abs(r[1]-fr[1]) < 10:
                found = True; break
        if not found: final_rects.append(r)
    return final_rects[:TOTAL_CARDS]

def sort_grid_generic(rects, cols):
    if not rects: return []
    rects = sorted(rects, key=lambda b: b[1]) 
    sorted_slots = []
    current_row = [rects[0]]
    for i in range(1, len(rects)):
        if abs(rects[i][1] - current_row[0][1]) < 25:
            current_row.append(rects[i])
        else:
            sorted_slots.extend(sorted(current_row, key=lambda b: b[0]))
            current_row = [rects[i]]
    sorted_slots.extend(sorted(current_row, key=lambda b: b[0]))
    return sorted_slots

def auto_play_execution(card_memory, card_slots, game_window):
    global AUTO_PLAY_ENABLED
    if not AUTO_PLAY_ENABLED: return

    memo_indices = list(card_memory.keys())
    matched_pair = None

    for i in range(len(memo_indices)):
        for j in range(i + 1, len(memo_indices)):
            idx1 = memo_indices[i]
            idx2 = memo_indices[j]
            verified1, img1 = card_memory[idx1]
            verified2, img2 = card_memory[idx2]

            if verified1 and verified2:
                img1_gray = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
                img2_gray = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
                if mse(img1_gray, img2_gray) < MSE_MATCH_THRESHOLD:
                    matched_pair = (idx1, idx2)
                    break
        if matched_pair: break
    
    if matched_pair:
        idx1, idx2 = matched_pair
        print(f"🤖 Auto: Clicking pair {idx1} & {idx2}")
        x1, y1, w1, h1 = card_slots[idx1]
        click_card(x1, y1, w1, h1, game_window)
        time.sleep(0.5)
        x2, y2, w2, h2 = card_slots[idx2]
        click_card(x2, y2, w2, h2, game_window)
        del card_memory[idx1]
        del card_memory[idx2]
        time.sleep(1)

# ================= MAIN ===================
def process_game_screen():
    global AUTO_PLAY_ENABLED
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except:
        is_admin = False

    if not is_admin:
        messagebox.showwarning("Warning", "โปรดรันโปรแกรมแบบ 'Run as Administrator'\nมิเช่นนั้น Hotkey และ Auto Click จะไม่ทำงานในเกม")
    
    back_card_ref = load_resources()
    back_card_ref_gray = None
    if back_card_ref is not None:
        back_card_ref_gray = cv2.cvtColor(back_card_ref, cv2.COLOR_BGR2GRAY)

    print(f"⏳ ค้นหาหน้าต่าง '{TARGET_WINDOW_KEYWORD}' ...")
    game_window = find_window_fuzzy(TARGET_WINDOW_KEYWORD)
    if not game_window: 
        messagebox.showerror("Error", "ไม่พบหน้าต่างเกม")
        return

    print(f"✅ พบ: '{game_window.title}'")
    if game_window.isMinimized: game_window.restore()
    try: game_window.activate()
    except: pass
    time.sleep(0.5)

    card_slots = []
    card_memory = {}
    grid_locked = False 

    def toggle_auto():
        global AUTO_PLAY_ENABLED
        AUTO_PLAY_ENABLED = not AUTO_PLAY_ENABLED
        print(f"🤖 Auto Play: {'ON' if AUTO_PLAY_ENABLED else 'OFF'}")

    def reset_grid():
        nonlocal grid_locked, card_slots, card_memory
        grid_locked = False
        card_slots = []
        card_memory.clear()
        print("🔄 Grid Reset")

    keyboard.add_hotkey('f', toggle_auto)
    keyboard.add_hotkey('r', reset_grid)
    keyboard.add_hotkey('q', lambda: os._exit(0))

    with mss.mss() as sct:
        while True:
            monitor = {
                "top": game_window.top + 35, 
                "left": game_window.left + 5, 
                "width": game_window.width - 10, 
                "height": game_window.height - 40
            }
            if monitor["width"] <= 0: continue
            
            try: screenshot = np.array(sct.grab(monitor))
            except: break

            frame = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
            display_frame = frame.copy()

            if grid_locked:
                check_auto_reset(frame, reset_grid)

            # --- PHASE 1 ---
            if not grid_locked:
                raw_rects = find_contours_hybrid(frame)
                unique_rects = reconstruct_grid(raw_rects)
                for (x,y,w,h) in unique_rects: 
                    cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0,0,255), 1)

                if len(unique_rects) >= TOTAL_CARDS:
                    best_rects = sorted(unique_rects, key=lambda x: x[2]*x[3], reverse=True)[:TOTAL_CARDS]
                    try:
                        card_slots = sort_grid_generic(best_rects, GRID_COLS)
                        grid_locked = True
                        card_memory.clear()
                        print("✅ Grid Locked!")
                    except: pass
                else:
                    cv2.putText(display_frame, f"Scanning Grid... Found {len(unique_rects)}", (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

            # --- PHASE 2---
            if grid_locked:
                for i, (x, y, w, h) in enumerate(card_slots):
                    p = 6
                    if y+p < 0 or x+p < 0 or y+h-p > frame.shape[0] or x+w-p > frame.shape[1]: continue
                    roi = frame[y+p:y+h-p, x+p:x+w-p]
                    if roi.size == 0: continue
                    roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

                    diff_score = 0
                    if back_card_ref_gray is not None:
                        diff_score = mse(roi_gray, back_card_ref_gray)

                    is_back_card = False
                    if diff_score < 2500: is_back_card = True
                    elif diff_score < MIN_DIFF_TO_UPDATE: is_back_card = True 

                    if not is_back_card:
                        already_known = False
                        if i in card_memory:
                            verified, _ = card_memory[i]
                            if verified: already_known = True
                        
                        if not already_known:
                            found_in_db, matched_img = identify_card_fast(roi)
                            if found_in_db:
                                card_memory[i] = (True, matched_img)
                            else:
                                card_memory[i] = (True, roi) 
                    
                    if i in card_memory:
                        verified, memo_img = card_memory[i]
                        try:
                            display_img = cv2.resize(memo_img, (w, h))
                            display_frame[y:y+h, x:x+w] = display_img
                            cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                        except: pass
                    else:
                        cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0, 0, 255), 1)

                auto_play_execution(card_memory, card_slots, game_window)

            status_text = f"Auto play: {'ON' if AUTO_PLAY_ENABLED else 'OFF'} (Press F)"
            status_text2 = f"Press R to Reset Grid | Press Q to Quit"
            color = (0, 255, 0) if AUTO_PLAY_ENABLED else (0, 0, 255)
            cv2.putText(display_frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            cv2.putText(display_frame, status_text2, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            h, w = display_frame.shape[:2]
            new_w, new_h = int(w * VIEW_SCALE), int(h * VIEW_SCALE)
            if new_w > 0: cv2.imshow("Bot View", cv2.resize(display_frame, (new_w, new_h)))

            key = cv2.waitKey(1)
            if key & 0xFF == ord('q'): break

    cv2.destroyAllWindows()

if __name__ == "__main__":
    root = tkinter.Tk()
    root.withdraw()

    try:
        top = tkinter.Toplevel(root)
        top.withdraw()
        
        icon_path = resource_path("icon.ico")
        
        if os.path.exists(icon_path):
            top.iconbitmap(default=icon_path)
        else:
            print(f"⚠️ Warning: ไม่พบไฟล์ {icon_path} (รันต่อโดยไม่มีไอคอน)")
            
    except Exception as e:
        print(f"⚠️ Warning: ไม่สามารถโหลดไอคอนได้ ({e})")

    process_game_screen()