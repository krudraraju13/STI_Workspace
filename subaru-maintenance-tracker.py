import os
import sys
import json
import datetime
import pandas as pd
import re
import requests

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subaru_maintenance_history.json")

# Attempt to import optional libraries
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

try:
    import rich
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.prompt import Prompt, Confirm, IntPrompt
    HAS_RICH = True
except ImportError:
    HAS_RICH = False



def load_history():
    # 1. Load local records from HISTORY_FILE
    local_records = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                local_records = json.load(f)
        except Exception:
            pass
            
    # Normalize local_records list structure
    if not isinstance(local_records, list):
        local_records = []

    # 2. Get API URL from secrets
    api_url = None
    if HAS_STREAMLIT:
        try:
            api_url = st.secrets.get("gsheets_api_url")
        except Exception:
            pass

    cloud_records = None
    loaded_from_cloud = False
    if api_url:
        try:
            # Prevent caching by appending a unique Unix timestamp query parameter
            import time
            cb_url = f"{api_url}&_={int(time.time())}" if "?" in api_url else f"{api_url}?_={int(time.time())}"
            response = requests.get(cb_url, timeout=6)
            if response.status_code == 200:
                cloud_records = response.json()
                if isinstance(cloud_records, list):
                    loaded_from_cloud = True
        except Exception as e:
            print(f"Error fetching Google Sheets history: {str(e)}")
            pass

    # Helper function to check if two entries are equal
    def are_entries_equal(e1, e2):
        # Date match
        d1 = str(e1.get("date", "")).split("T")[0].strip()
        d2 = str(e2.get("date", "")).split("T")[0].strip()
        if d1 != d2:
            return False
            
        # Mileage match
        try:
            m1 = int(e1.get("mileage", 0))
        except Exception:
            m1 = 0
        try:
            m2 = int(e2.get("mileage", 0))
        except Exception:
            m2 = 0
        if m1 != m2:
            return False
            
        # Completed items match
        def clean_items(it):
            if it is None:
                return []
            if isinstance(it, str):
                it_strip = it.strip()
                if it_strip.startswith("[") and it_strip.endswith("]"):
                    try:
                        import json
                        parsed = json.loads(it_strip)
                        if isinstance(parsed, list):
                            return sorted([str(x).strip() for x in parsed if x is not None])
                    except Exception:
                        pass
                if ";" in it_strip:
                    return sorted([x.strip() for x in it_strip.split(";") if x.strip()])
                if "," in it_strip:
                    return sorted([x.strip() for x in it_strip.split(",") if x.strip()])
                return [it_strip] if it_strip else []
            if isinstance(it, list):
                return sorted([str(x).strip() for x in it if x is not None])
            return []
            
        return clean_items(e1.get("completed_items")) == clean_items(e2.get("completed_items"))

    merged_data = []
    if loaded_from_cloud:
        # Merge local and cloud records
        matched_cloud_indices = set()
        
        # 1. Process local records and check if they exist in cloud
        for local_entry in local_records:
            if not isinstance(local_entry, dict):
                continue
                
            # Find matching entry in cloud
            match_index = None
            for idx, cloud_entry in enumerate(cloud_records):
                if idx in matched_cloud_indices:
                    continue
                if are_entries_equal(local_entry, cloud_entry):
                    match_index = idx
                    break
                    
            if match_index is not None:
                # Exists in BOTH local and cloud -> Indicator should be shown as Cloud!
                matched_cloud_indices.add(match_index)
                entry_copy = dict(local_entry)
                entry_copy["_source_of_data"] = "☁ Cloud"
                merged_data.append(entry_copy)
            else:
                # Exists ONLY in local
                entry_copy = dict(local_entry)
                entry_copy["_source_of_data"] = "▤ Local"
                merged_data.append(entry_copy)
                
        # 2. Add remaining cloud records that do not exist in local (or have been auto-synced)
        for idx, cloud_entry in enumerate(cloud_records):
            if idx not in matched_cloud_indices:
                if isinstance(cloud_entry, dict):
                    entry_copy = dict(cloud_entry)
                    entry_copy["_source_of_data"] = "☁ Cloud"
                    merged_data.append(entry_copy)
                    
        # Update local file with the newly merged and synced list
        try:
            with open(HISTORY_FILE, "w") as f:
                import json
                json.dump(merged_data, f, indent=4)
        except Exception:
            pass
    else:
        # We are offline or cloud fetch failed, so we use local_records directly
        for local_entry in local_records:
            if not isinstance(local_entry, dict):
                continue
            entry_copy = dict(local_entry)
            # If the entry was previously marked as synced, keep it! Otherwise fall back to Local
            if "_source_of_data" not in entry_copy:
                entry_copy["_source_of_data"] = "▤ Local"
            merged_data.append(entry_copy)

    # Sanitize merged_data before returning to the UI to ensure robust display
    sanitized_data = []
    for entry in merged_data:
        if not isinstance(entry, dict):
            continue
            
        # Ensure date exists and is a string
        if "date" not in entry or not entry["date"]:
            entry["date"] = datetime.date.today().isoformat()
            
        # Ensure mileage exists and is an int
        try:
            entry["mileage"] = int(entry.get("mileage", 0))
        except (ValueError, TypeError):
            entry["mileage"] = 0
            
        # Ensure severe_mode exists and is boolean
        entry["severe_mode"] = bool(entry.get("severe_mode", False))
        
        # Ensure time exists in HH:MM format
        if "time" not in entry or not entry["time"]:
            entry["time"] = "00:00"
            
        # Ensure completed_items exists and is a proper list of strings
        completed = entry.get("completed_items")
        if completed is None:
            entry["completed_items"] = []
        elif isinstance(completed, str):
            completed_strip = completed.strip()
            if completed_strip.startswith("[") and completed_strip.endswith("]"):
                try:
                    import json
                    parsed = json.loads(completed_strip)
                    if isinstance(parsed, list):
                        entry["completed_items"] = [str(x) for x in parsed if x is not None]
                    else:
                        entry["completed_items"] = [completed_strip]
                except Exception:
                    entry["completed_items"] = [completed_strip]
            elif ";" in completed_strip:
                entry["completed_items"] = [x.strip() for x in completed_strip.split(";") if x.strip()]
            elif "," in completed_strip:
                entry["completed_items"] = [x.strip() for x in completed_strip.split(",") if x.strip()]
            elif completed_strip:
                entry["completed_items"] = [completed_strip]
            else:
                entry["completed_items"] = []
        elif isinstance(completed, list):
            entry["completed_items"] = [str(x) for x in completed if x is not None]
        else:
            entry["completed_items"] = []
            
        sanitized_data.append(entry)
        
    return sanitized_data

def get_cached_history():
    if not HAS_STREAMLIT:
        return load_history()
    if "history_cache" not in st.session_state:
        st.session_state["history_cache"] = load_history()
    return st.session_state["history_cache"]

def save_history(entry):
    # Dynamic Google Sheets Integration via Apps Script API
    api_url = None
    if HAS_STREAMLIT:
        try:
            api_url = st.secrets.get("gsheets_api_url")
        except Exception:
            pass
            
    # Set dynamic source indicator for session consistency
    entry["_source_of_data"] = "☁ Cloud" if api_url else "▤ Local"

    if HAS_STREAMLIT:
        if "history_cache" not in st.session_state:
            st.session_state["history_cache"] = load_history()
        st.session_state["history_cache"].append(entry)
            
    if api_url:
        try:
            # Append row to Google Sheets via secure HTTPS POST
            headers = {"Content-Type": "application/json"}
            response = requests.post(api_url, json=entry, headers=headers, timeout=8)
        except Exception as e:
            pass

    # Always maintain a complete local JSON cache as a physical backup
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            pass
    history.append(entry)
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=4)
    except Exception:
        pass

class MaintenanceScheduler:
    def __init__(self, mileage, severe=False, primary_mode=True):
        self.mileage = mileage
        self.severe = severe
        self.primary_mode = primary_mode

    def get_schedule(self):
        items = []
        history = get_cached_history()
        
        # Define standard intervals and info
        # Structure: (Name, Base Interval, Severe Interval, Part Number, Quantity, Description)
        maintenance_defs = [
            (
                "Replace Engine Oil & Filter", 
                6000, 
                3000, 
                "15208AA100 (Tokyo Roki JDM Black)", 
                "4.5 Quarts 5W-30/5W-40 + 1 Crush Washer (11126AA000)",
                "Drain plug torque: 33-34 ft-lb. Under severe conditions, replace every 3,000 miles."
            ),
            (
                "Rotate Tires & Check Pressures", 
                6000, 
                6000, 
                "N/A", 
                "N/A",
                "Ensure even tread wear. Tighten lug nuts strictly to 88.5 ft-lb (120 Nm)."
            ),
            (
                "Replace Cabin Air Filter", 
                12000, 
                12000, 
                "72880FG000", 
                "1 Filter",
                "Protects HVAC and passenger air quality from pollen and dust."
            ),
            (
                "Inspect Front & Rear Brake Pads & Rotors", 
                12000, 
                6000, 
                "N/A", 
                "N/A",
                "Check pad thickness. Front Brembos mount torque: 84.3 ft-lb; Rears: 47.2 ft-lb."
            ),
            (
                "Replace Engine Air Filter", 
                30000, 
                15000, 
                "16546AA12A", 
                "1 Filter",
                "Ensure clean induction air flow. Replace more often in dusty/sandy areas."
            ),
            (
                "Replace Brake Fluid", 
                30000, 
                15000, 
                "N/A", 
                "~1.0 Liter (DOT 3 or DOT 4 Premium)",
                "Flush moisture and contaminants from the Brembo caliper hydraulic system."
            ),
            (
                "Replace Manual Transmission Gear Oil", 
                30000, 
                30000, 
                "API GL-5 SAE 75W-90", 
                "Service Fill: ~3.5 Quarts (Dry: 4.1 Quarts)",
                "Gearbox and front diff share oil bath. Plug torque: 32.5 ft-lb (T70 Torx)."
            ),
            (
                "Replace Rear Differential Gear Oil", 
                30000, 
                30000, 
                "API GL-5 SAE 75W-90", 
                "1.0 Quart",
                "Protects hypoid gears. Fill/drain plug torque: 36–43 ft-lb."
            ),
            (
                "Inspect Fuel Lines and Connections", 
                30000, 
                30000, 
                "N/A", 
                "N/A",
                "Verify security and check for any leakage or deterioration."
            ),
            (
                "Inspect Steering & Suspension Systems", 
                30000, 
                30000, 
                "N/A", 
                "N/A",
                "Check steering gearbox, linkage, tie rods, boot seals, and suspension joints."
            ),
            (
                "Replace Spark Plugs", 
                6000, # Wait, check standard spark plug interval: 60,000 miles
                60000, 
                "22401AA670 (NGK SILFR6A Laser Iridium)", 
                "4 Spark Plugs",
                "Use dry threads. Torque strictly to 13–17 ft-lb to protect aluminum heads."
            ),
            (
                "Replace Timing Belt (EJ257 DOHC)", 
                105000, 
                105000, 
                "13028AA250 (Aisin Kit TKF-012)", 
                "1 Timing Belt Kit",
                "Critical interference engine component. Replace timing belt, tensioner, water pump."
            ),
            (
                "Replace Engine Coolant (Super Coolant)", 
                137500, 
                137500, 
                "Super Coolant (Pre-Mixed Blue)", 
                "8.1 Quarts + 1 bottle Conditioner (SOA635065)",
                "First change at 137,500 mi / 11 years; subsequent changes every 75,000 mi / 6 years."
            )
        ]
        
        # Override spark plug interval if defined wrong
        for idx, item_def in enumerate(maintenance_defs):
            if item_def[0] == "Replace Spark Plugs":
                maintenance_defs[idx] = (
                    "Replace Spark Plugs", 
                    60000, 
                    60000, 
                    "22401AA670 (NGK SILFR6A Laser Iridium)", 
                    "4 Spark Plugs",
                    "Use dry threads. Torque strictly to 13–17 ft-lb to protect aluminum heads."
                )

        for name, base_int, sev_int, p_num, qty, desc in maintenance_defs:
            interval = sev_int if self.severe else base_int
            
            # Find last completed mileage
            last_mi = None
            if history:
                completions = [entry["mileage"] for entry in history if name in entry.get("completed_items", [])]
                if completions:
                    last_mi = max(completions)
            
            # Calculate due status
            if name == "Replace Engine Coolant (Super Coolant)":
                if last_mi is None:
                    due = self.mileage >= 137500
                else:
                    due = (self.mileage - last_mi) >= 75000
            else:
                if last_mi is None:
                    due = self.mileage >= interval
                else:
                    due = (self.mileage - last_mi) >= interval
            
            items.append({
                "name": name,
                "interval": interval,
                "due": due,
                "part_number": p_num,
                "quantity": qty,
                "description": desc,
                "last_completed": last_mi
            })
            
        return items

# --- STREAMLIT WEB APP RUNTIME ---
if HAS_STREAMLIT and st.runtime.exists():
    import base64
    import os
    import urllib.request

    STI_FILE = "sti_logo.svg"
    SUBARU_FILE = "subaru_logo.svg"


    # Direct GitHub raw URLs for files based on the user's workspace repository
    STI_URLS = [
        "https://raw.githubusercontent.com/krudraraju13/STI_Workspace/main/sti_logo.svg",
        "https://raw.githubusercontent.com/krudraraju13/STI_Workspace/main/sti_logo.svg.png"
    ]
    SUBARU_URLS = [
        "https://raw.githubusercontent.com/krudraraju13/STI_Workspace/main/subaru_logo.svg",
        "https://raw.githubusercontent.com/krudraraju13/STI_Workspace/main/subaru_logo.svg.png"
    ]


    # Direct GitHub raw URLs for both files based on the user's workspace repository
    STI_URLS = [
        "https://raw.githubusercontent.com/krudraraju13/STI_Workspace/main/sti_logo.svg",
        "https://raw.githubusercontent.com/krudraraju13/STI_Workspace/main/sti_logo.svg.png"
    ]
    SUBARU_URLS = [
        "https://raw.githubusercontent.com/krudraraju13/STI_Workspace/main/subaru_logo.svg",
        "https://raw.githubusercontent.com/krudraraju13/STI_Workspace/main/subaru_logo.svg.png"
    ]

    def download_asset(urls, filepath):
        for url in urls:
            try:
                req = urllib.request.Request(
                    url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                )
                with urllib.request.urlopen(req, timeout=8) as response:
                    data = response.read()
                    if data:
                        with open(filepath, "wb") as f:
                            f.write(data)
                        return True
            except Exception:
                continue
        return False



    # Robust file size and semantic validation for assets
    def is_valid_svg(filepath):
        if not os.path.exists(filepath):
            return False
        try:
            # SVG files should be at least 1KB
            if os.path.getsize(filepath) < 1000:
                return False
            with open(filepath, "rb") as f:
                content = f.read()
            # If the file is actually a PNG (even with .svg extension), check PNG header
            if content.startswith(b"\x89PNG") or content.startswith(b"\x89\x50\x4e\x47"):
                return True
            # For SVG files, must contain the closing tag
            if b"</svg>" in content.lower():
                return True
            return False
        except Exception:
            return False

    def is_valid_png(filepath):
        if not os.path.exists(filepath):
            return False
        try:
            if os.path.getsize(filepath) < 5000:
                return False
            with open(filepath, "rb") as f:
                header = f.read(8)
            if header.startswith(b"\x89PNG") or header.startswith(b"\x89\x50\x4e\x47"):
                return True
            return False
        except Exception:
            return False

    # Force auto-heal of any corrupted, truncated, or failed local asset downloads
    if os.path.exists(STI_FILE) and not is_valid_svg(STI_FILE):
        try:
            os.remove(STI_FILE)
        except Exception:
            pass
    if os.path.exists(SUBARU_FILE) and not is_valid_svg(SUBARU_FILE):
        try:
            os.remove(SUBARU_FILE)
        except Exception:
            pass


    # Download missing or validated-and-cleared corrupted files
    if not os.path.exists(STI_FILE):
        download_asset(STI_URLS, STI_FILE)
    if not os.path.exists(SUBARU_FILE):
        download_asset(SUBARU_URLS, SUBARU_FILE)


    # Base64 loading logic with content-first robust MIME-type detection
    def determine_mime(filepath, file_data):
        if file_data.startswith(b"\x89PNG") or file_data.startswith(b"\x89\x50\x4e\x47") or file_data.startswith(b"\x89PNG\r\n\x1a\n") or file_data.startswith(b"\x89PNG\r\n\x1a\n") or file_data[:4] == b"\x89PNG" or file_data[:4] == b"\x89\x50\x4e\x47":
            return "image/png"
        elif file_data.startswith(b"GIF8"):
            return "image/gif"
        elif b"<svg" in file_data[:500] or b"<SVG" in file_data[:500]:
            return "image/svg+xml"
        elif filepath.lower().endswith(".png"):
            return "image/png"
        elif filepath.lower().endswith(".svg"):
            return "image/svg+xml"
        return "image/png"

    sti_src = ""
    try:
        if os.path.exists(STI_FILE):
            with open(STI_FILE, "rb") as f:
                sti_data = f.read()
            sti_mime = determine_mime(STI_FILE, sti_data)
            sti_b64 = base64.b64encode(sti_data).decode("utf-8")
            sti_src = f"data:{sti_mime};base64,{sti_b64}"
    except Exception:
        pass

    subaru_src = ""
    try:
        if os.path.exists(SUBARU_FILE):
            with open(SUBARU_FILE, "rb") as f:
                subaru_data = f.read()
            subaru_mime = determine_mime(SUBARU_FILE, subaru_data)
            subaru_b64 = base64.b64encode(subaru_data).decode("utf-8")
            subaru_src = f"data:{subaru_mime};base64,{subaru_b64}"
    except Exception:
        pass



    # Clean minimal geometric text fallbacks in case of offline launch without files
    if not sti_src:
        sti_fallback = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">
            <rect width="100%" height="100%" fill="#111111" rx="8"/>
            <text x="50%" y="58%" font-family="'Montserrat', sans-serif" font-size="28" font-weight="800" fill="#FF007F" text-anchor="middle">STI</text>
        </svg>"""
        sti_b64 = base64.b64encode(sti_fallback.encode("utf-8")).decode("utf-8")
        sti_src = f"data:image/svg+xml;base64,{sti_b64}"

    if not subaru_src:
        subaru_fallback = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 140" width="280" height="140">
            <rect width="100%" height="100%" fill="#111111" rx="8"/>
            <text x="50%" y="58%" font-family="'Montserrat', sans-serif" font-size="28" font-weight="800" fill="#0066cc" text-anchor="middle">SUBARU</text>
        </svg>"""
        subaru_b64 = base64.b64encode(subaru_fallback.encode("utf-8")).decode("utf-8")
        subaru_src = f"data:image/svg+xml;base64,{subaru_b64}"

    # Set page layout config
    st.set_page_config(page_title="Subaru STI Maintenance Tracker", page_icon="⚙", layout="wide")

    # Global CSS customization for fonts, responsiveness, align, spacing, and colors
    st.markdown(
        """
        <style>
        /* Import premium system fonts */
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&family=Roboto:wght@400;500;700&display=swap');
        
        /* Base dark/light compatible styling */
        html, body, [data-testid="stAppViewContainer"] {
            font-family: 'Roboto', sans-serif;
            color: var(--text-color) !important;
        }

        h1, h2, h3, h4, h5, h6, [class*="header"] {
            font-family: 'Montserrat', sans-serif;
            font-weight: 700;
            color: var(--text-color) !important;
        }

        /* Hide the link/anchor icons next to all titles */
        h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {
            display: none !important;
        }
        [data-testid="stHeaderActionElements"] {
            display: none !important;
        }

        /* Customize Streamlit Tabs with STI theme colors */
        button[data-baseweb="tab"] {
            font-family: 'Montserrat', sans-serif !important;
            font-weight: 600 !important;
            font-size: 14px !important;
            color: var(--text-color) !important;
            opacity: 0.6;
            border-bottom: 2px solid transparent !important;
            padding: 10px 16px !important;
            transition: all 0.3s ease !important;
        }

        button[data-baseweb="tab"]:hover {
            color: #FF007F !important;
            opacity: 1;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            color: #FF007F !important;
            opacity: 1;
            border-bottom: 3px solid #FF007F !important;
            background-color: rgba(255, 0, 127, 0.08) !important;
            border-top-left-radius: 4px !important;
            border-top-right-radius: 4px !important;
        }

        /* Custom cards styled around the STI color scheme */
        .custom-card {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-left: 5px solid #FF007F !important; /* STI Cherry Blossom Pink */
            border-radius: 8px;
            padding: 20px;
            margin: 15px 0;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            color: var(--text-color) !important;
        }
        .custom-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.15);
            border-color: #FF007F !important;
        }

        /* Highlight card for crucial warnings */
        .warning-card {
            background-color: rgba(255, 0, 127, 0.05);
            border: 1px solid rgba(255, 0, 127, 0.2);
            border-left: 5px solid #FF007F !important;
            border-radius: 8px;
            padding: 18px;
            margin: 15px 0;
            color: var(--text-color) !important;
        }

        /* Styled list elements */
        ul {
            padding-left: 20px !important;
            margin-bottom: 10px !important;
        }
        li {
            margin-bottom: 6px !important;
            line-height: 1.5 !important;
        }

        /* Align center util */
        .align-center {
            text-align: center;
        }

        /* Make dataframes highly readable and fit containers */
        div[data-testid="stDataFrame"] {
            background-color: var(--secondary-background-color) !important;
            border-radius: 8px !important;
            border: 1px solid rgba(128, 128, 128, 0.2) !important;
            overflow: hidden !important;
        }
        
        /* Adjust expander headers */
        .streamlit-expanderHeader {
            font-family: 'Montserrat', sans-serif !important;
            font-weight: 600 !important;
            font-size: 15px !important;
            background-color: var(--secondary-background-color) !important;
            border: 1px solid rgba(128, 128, 128, 0.2) !important;
            border-radius: 4px !important;
            margin-bottom: 5px !important;
            color: var(--text-color) !important;
        }
        .streamlit-expanderContent {
            background-color: var(--background-color) !important;
            border: 1px solid rgba(128, 128, 128, 0.2) !important;
            border-top: none !important;
            border-bottom-left-radius: 4px !important;
            border-bottom-right-radius: 4px !important;
            padding: 15px !important;
            color: var(--text-color) !important;
        }


        </style>
        """,
        unsafe_allow_html=True
    )

    @st.dialog("Confirm Service Log")
    def confirm_save_dialog(completed_list, mileage, severe):
        st.markdown("##### Are you sure you want to save the completed services to your history?")
        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Confirm", type="primary", use_container_width=True):
                # Calculate current time in US/Eastern timezone
                from zoneinfo import ZoneInfo
                current_time_est = datetime.datetime.now(ZoneInfo("US/Eastern")).strftime("%H:%M")
                new_entry = {
                    "date": datetime.date.today().isoformat(),
                    "time": current_time_est,
                    "mileage": mileage,
                    "severe_mode": severe,
                    "completed_items": completed_list
                }
                save_history(new_entry)
                
                # Force-clear checkbox states from Streamlit session_state so they are unchecked on rerun
                for item_name in completed_list:
                    key = f"check_{item_name}"
                    if key in st.session_state:
                        st.session_state[key] = False
                        
                st.success("✓ Service logged successfully!")
                st.rerun()
        with col2:
            if st.button("Cancel", use_container_width=True):
                st.rerun()


        # Responsive Brand Logo Header Block (STI & Subaru Logos flanking the Title)
    logo_left_col, title_col, logo_right_col = st.columns([1.0, 3.4, 1.6], vertical_alignment="center")
    with logo_left_col:
        st.markdown(
            f"""
            <div style="display: flex; justify-content: flex-start; align-items: center; height: auto; min-height: 100px; max-height: 140px; width: 100%;">
                <img src="{sti_src}" style="width: 100%; max-width: 200px; height: auto; max-height: 100px; object-fit: contain; display: block;"/>
            </div>
            """,
            unsafe_allow_html=True
        )
    with title_col:
        st.markdown(
            """
            <div style='padding-top:10px; text-align: center;'>
                <h1 style='color:var(--text-color);margin:0;font-size:2.2em;letter-spacing:-0.5px;'>⚙ Subaru STI Maintenance Tracker</h1>
                <p style='color:#FF007F;margin:5px 0 0 0;font-size:1.15em;font-family:"Montserrat",sans-serif;font-weight:700;'>
                    Symmetrical All-Wheel Drive Performance Suite &bull; Factory Specifications &bull; Interactive Log
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )
    with logo_right_col:
        st.markdown(
            f"""
            <div style="display: flex; justify-content: flex-end; align-items: center; height: auto; min-height: 100px; max-height: 140px; width: 100%;">
                <img src="{subaru_src}" style="width: 100%; max-width: 320px; height: auto; max-height: 115px; object-fit: contain; display: block; margin-left: auto;"/>
            </div>
            """,
            unsafe_allow_html=True
        )
    st.markdown("<hr style='margin:10px 0 20px 0; border-color:#334155;'/>", unsafe_allow_html=True)

    # Tabs layout
    tab_checklist, tab_procedures, tab_parts, tab_fluids, tab_history, tab_manual = st.tabs([
        "⌖ Status",
        "⚙ Procedures",
        "⎔ OEM Parts",
        "⛢ Fluids & Grades",
        "▤ Service Log",
        "☰ Reference Guide"
    ])

    with tab_checklist:
        st.markdown("### ⌖ Odometer & Operating Conditions")
        st.markdown(
            """
            <style>
            div[data-testid="stNumberInput"] input {
                font-size: 22px !important;
                height: 52px !important;
                font-weight: bold !important;
            }
            /* Clean up any default spacing since label is removed */
            div[data-testid="stNumberInput"] label {
                display: none !important;
            }
            div[data-testid="stNumberInput"] {
                margin-top: 0px !important;
            }
            </style>
            """,
            unsafe_allow_html=True
        )
        col_mil, col_sev = st.columns(2, vertical_alignment="center")
        with col_mil:
            mileage = st.number_input("", min_value=0, max_value=500000, value=None, step=1000, placeholder="Enter current mileage")
        with col_sev:
            severe = st.checkbox(
                "Severe Driving Conditions", 
                value=False,
                help="Trigger shorter intervals (e.g., oil every 3,000 miles). Conditions include repeated short distances (< 5 mi), rough/mudy/salty/snowy roads, high humidity/mountains, or extremely cold weather."
            )
        st.markdown("<hr style='margin:15px 0; border-color:#eee;'/>", unsafe_allow_html=True)

    is_primary = True

    # Always initialize scheduler so that other tabs work independently of Odometer input
    current_mileage = mileage if mileage is not None else 0
    scheduler = MaintenanceScheduler(current_mileage, severe, primary_mode=is_primary)
    schedule_items = scheduler.get_schedule()

    # Load history to filter checked/completed items at the current mileage
    history = get_cached_history()
    completed_items_at_current_mileage = set()
    if history and mileage is not None:
        for entry in history:
            if entry.get("mileage") == mileage:
                for item in entry.get("completed_items", []):
                    completed_items_at_current_mileage.add(item)

    with tab_checklist:
        if mileage is not None:
            st.markdown("### ⌖ Maintenance Checklist")
            st.write("Check the items you have completed at your current mileage, then click **Save Checked Services** at the bottom to log them.")

            # Categorize items by criticality
            high_crit_items = []
            med_crit_items = []
            low_crit_items = []

            high_names = {
                "Replace Engine Oil & Filter",
                "Replace Timing Belt (EJ257 DOHC)",
                "Replace Spark Plugs",
                "Inspect Front & Rear Brake Pads & Rotors",
                "Replace Brake Fluid"
            }
            low_names = {
                "Replace Cabin Air Filter"
            }

            for item in schedule_items:
                if item["name"] in completed_items_at_current_mileage:
                    continue  # Skip already completed items
                if item["name"] in high_names:
                    high_crit_items.append(item)
                elif item["name"] in low_names:
                    low_crit_items.append(item)
                else:
                    med_crit_items.append(item)

            categories = [
                ("[!] High", high_crit_items),
                ("[~] Medium", med_crit_items),
                ("[.] Low", low_crit_items)
            ]
            
            if not high_crit_items and not med_crit_items and not low_crit_items:
                st.success("[✓] All scheduled services for this mileage have been completed and logged!")

            completed_list = []

            for cat_title, cat_items in categories:
                if cat_items:
                    st.markdown(f"#### {cat_title}")
                    for item in cat_items:
                        last_str = f" (Last: {item['last_completed']:,} mi)" if item['last_completed'] is not None else ""
                        label = f"**{item['name']}**{last_str} — every {item['interval']:,} mi"
                        
                        checked = st.checkbox(label, key=f"check_{item['name']}")
                        if checked:
                            completed_list.append(item["name"])
                    
                    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

            st.markdown("<hr style='margin:15px 0; border-color:#eee;'/>", unsafe_allow_html=True)
            
            # Action button
            if completed_list:
                if st.button("Save Checked Services", type="primary", use_container_width=True):
                    confirm_save_dialog(completed_list, mileage, severe)
            else:
                st.button("Save Checked Services", type="primary", disabled=True, use_container_width=True, help="Check one or more items above to enable logging.")


    # Procedures Tab
    with tab_procedures:
        st.subheader("⚙ Maintenance Procedures Guide")
        st.write("Step-by-step DIY instructions and crucial checks for WRX STI owners.")
        
        proc_selection = st.selectbox(
            "Select Procedure:",
            [
                "Select a procedure...",
                "Engine Oil & Filter Swap",
                "Manual Transmission Gear Oil Replacement",
                "Rear Differential Oil Swap",
                "Spark Plug Installation (DOHC Boxer)",
                "Timing Belt (EJ257) Overview"
            ],
            label_visibility="collapsed"
        )
        
        if proc_selection == "Engine Oil & Filter Swap":
            st.markdown(
                """
                ### ⛢ Engine Oil & Filter Swap Procedure
                **Target Thread Torque:** Drain plug: `33-34 ft-lb` (Ensure a new OEM metal crush washer P/N `11126AA000` is used).
                
                **Step-by-Step Instructions:**
                1. Ensure engine is warm. Park on flat ground and jack up front of car (use heavy duty jack stands and tire chocks).
                2. Position oil catch pan under the drain plug (14mm). Carefully remove plug and drain oil completely.
                3. Clean the drain plug threads, fit the new **Subaru Crush Washer** with its flat face against the oil pan, and hand thread. Torque to **33-34 ft-lb**.
                4. Use a filter wrench to remove the engine oil filter. Clean the contact surface on the engine block.
                5. Apply a light film of fresh engine oil to the rubber O-ring of the **Tokyo Roki Black Filter (15208AA100)**. Hand tighten the filter until seal contacts, then turn it exactly 3/4 to 1 full turn further.
                6. Add **4.5 quarts** of synthetic oil (5W-30 or 5W-40). Wait 5 minutes, check dipstick, start car, and check for leaks.
                """
            )
        elif proc_selection == "Manual Transmission Gear Oil Replacement":
            st.markdown(
                """
                ### ⚙ Manual Transmission Gear Oil Swap
                **Target Thread Torque:** T70 Torx drain plug: `32.5 ft-lb`. Fill plug: `23.5 ft-lb`.
                
                **Step-by-Step Instructions:**
                1. Elevate car flat on all four jack stands.
                2. Locate the transmission case. Remove the intercooler if filling from top, or use a fluid transfer pump from underneath.
                3. Remove the fill plug (10mm) first to ensure you can fill, then remove the lower T70 Torx drain plug.
                4. Clean the magnetic drain plug thoroughly of wear debris. Install with a new seal and torque to **32.5 ft-lb**.
                5. Fill with **~3.5 quarts** of SAE 75W-90 GL-5 gear oil (e.g. Motul Gear 300).
                6. Reinstall fill plug and torque to specifications.
                """
            )
        elif proc_selection == "Rear Differential Oil Swap":
            st.markdown(
                """
                ### ⚙ Rear Differential Oil Swap
                **Target Thread Torque:** Fill and drain plugs: `36.2 ft-lb`.
                
                **Step-by-Step Instructions:**
                1. Elevate the rear end. Locate the rear diff case.
                2. Remove the top fill plug (1/2\" drive or 13mm socket) to verify you can fill, then remove the lower drain plug.
                3. Allow 1.0 quart to drain completely. Clean the magnet on the drain plug.
                4. Apply thread sealant (like liquid Teflon) to the plug threads. Reinstall drain plug and torque to **36.2 ft-lb**.
                5. Use a pump to inject exactly **1.0 quart** of SAE 75W-90 GL-5 hypoid gear oil into the fill hole until it begins to seep out.
                6. Reinstall fill plug with thread sealant and torque to **36.2 ft-lb**.
                """
            )
        elif proc_selection == "Spark Plug Installation (DOHC Boxer)":
            st.markdown(
                """
                ### ⌱ Spark Plug Replacement
                **Target Thread Torque:** NGK Spark Plugs: `13–17 ft-lb` (Dry threads!).
                
                **Step-by-Step Instructions:**
                1. Disconnect battery. Remove air intake box (right side) and battery/washer fluid reservoir bracket components (left side) to access coil packs.
                2. Remove the 10mm bolts holding the ignition coils, and pull out the coil packs.
                3. Use a 5/8\" spark plug socket, a 3\" extension, and a swivel ratchet to carefully break loose and retrieve the old plugs.
                4. Ensure the new spark plugs (**NGK Laser Iridium SILFR6A**) are gapped correctly. Hand thread them into the cylinder head to prevent cross-threading.
                5. Torque strictly dry to **13-17 ft-lb**. *Do not use anti-seize*, as it acts as a lubricant and will lead to over-torquing and cylinder head strip out.
                """
            )
        elif proc_selection == "Timing Belt (EJ257) Overview":
            st.markdown(
                """
                ### ⚙ Timing Belt DOHC EJ257 Overview
                The EJ257 utilizes a DOHC layout with four camshafts. A snapped or jumped timing belt will cause instant, catastrophic valve-to-piston contact.
                
                **Key Advice:**
                *   Interval is **105,000 miles**.
                *   Always replace the complete assembly (Timing belt `13028AA250`, water pump, hydraulic tensioner, and all idler pulleys).
                *   Use high quality kits such as **Aisin TKF-012** to prevent premature idler bearing lockups.
                """
            )
        else:
            st.info("INFO: Select a maintenance procedure from the dropdown menu above to read detailed instructions and torque specifications.")

    # OEM Parts Tab
    with tab_parts:
        st.subheader("⎔ OEM Parts & Part Numbers Reference")
        st.write("Browse and search through the consolidated catalog of OEM parts, including pricing and real-time maintenance service requirements.")
        
        # Insert parts catalog

        # Expanded Genuine OEM Parts Database with Category, Name, P/N, Qty, and Price (USD)
        parts_catalog = [
            # Engine and Cooling
            {"Category": "Engine and Cooling", "Part Name": "Tokyo Roki JDM Black Engine Oil Filter", "OEM Part Number": "15208AA100", "Quantity": 1, "Price": 12.00, "Notes": "Calibrated 23 PSI metal bypass valve matches high Subaru oil pump relief pressure."},
            {"Category": "Engine and Cooling", "Part Name": "Oil Pan Drain Crush Washer", "OEM Part Number": "11126AA000", "Quantity": 1, "Price": 1.50, "Notes": "Direct fit copper crush ring. Prevents oil pan thread stripout."},
            {"Category": "Engine and Cooling", "Part Name": "Mitsuboshi Timing Belt (Individual)", "OEM Part Number": "13028AA250", "Quantity": 1, "Price": 85.00, "Notes": "High-tensile reinforced timing belt for DOHC EJ257 engines."},
            {"Category": "Engine and Cooling", "Part Name": "Complete Timing Belt Kit (Aisin)", "OEM Part Number": "TKF-012", "Quantity": 1, "Price": 280.00, "Notes": "Aisin timing kit with water pump, tensioners, and NSK/Koyo pulleys."},
            {"Category": "Engine and Cooling", "Part Name": "Water Pump Assembly (Aisin)", "OEM Part Number": "21111AA240", "Quantity": 1, "Price": 120.00, "Notes": "Aisin WPF-023 water pump with premium gasket."},
            {"Category": "Engine and Cooling", "Part Name": "Hydraulic Belt Tensioner", "OEM Part Number": "13033AA042", "Quantity": 1, "Price": 95.00, "Notes": "GMB / OEM-supplier hydraulic timing belt tensioner."},
            {"Category": "Engine and Cooling", "Part Name": "Thermostat Gasket", "OEM Part Number": "21236AA050", "Quantity": 1, "Price": 5.50, "Notes": "Molded rubber thermostat housing seal ring."},
            {"Category": "Engine and Cooling", "Part Name": "Engine Air Filter Element", "OEM Part Number": "16546AA12A", "Quantity": 1, "Price": 22.00, "Notes": "Pleated dry fiber element for optimal engine intake filtration."},
            {"Category": "Engine and Cooling", "Part Name": "Exhaust Gasket (Manifold to Head)", "OEM Part Number": "44011AC030", "Quantity": 2, "Price": 14.50, "Notes": "Multi-layer steel gasket between block and exhaust manifold."},
            {"Category": "Engine and Cooling", "Part Name": "Center Pipe Gasket (Donut)", "OEM Part Number": "44616AA200", "Quantity": 1, "Price": 18.00, "Notes": "Exhaust center pipe sealing gasket."},
            {"Category": "Engine and Cooling", "Part Name": "Intake Manifold Gasket", "OEM Part Number": "14035AA580", "Quantity": 2, "Price": 12.50, "Notes": "High-temperature gasket between intake runners and head."},
            {"Category": "Engine and Cooling", "Part Name": "EGR Pipe Gasket", "OEM Part Number": "14852AA040", "Quantity": 1, "Price": 6.00, "Notes": "Metal gasket for exhaust gas recirculation pipe."},
            {"Category": "Engine and Cooling", "Part Name": "Water Pipe O-Ring", "OEM Part Number": "14738AA150", "Quantity": 1, "Price": 3.50, "Notes": "Engine cooling bypass pipe sealing ring."},
            {"Category": "Engine and Cooling", "Part Name": "Chain Cover O-Ring", "OEM Part Number": "806912190", "Quantity": 3, "Price": 2.50, "Notes": "Sealing O-ring for front timing chain/belt cover."},
            {"Category": "Engine and Cooling", "Part Name": "Chain Cover O-Ring (Small)", "OEM Part Number": "806924120", "Quantity": 1, "Price": 1.80, "Notes": "Smaller timing cover fluid passage seal."},
            {"Category": "Engine and Cooling", "Part Name": "Tensioner O-Ring", "OEM Part Number": "806916080", "Quantity": 1, "Price": 2.20, "Notes": "Fluid block off O-ring for hydraulic timing tensioner."},
            {"Category": "Engine and Cooling", "Part Name": "Spark Plug Tube Seal", "OEM Part Number": "10966AA040", "Quantity": 4, "Price": 7.50, "Notes": "Rubber gasket sealing spark plug wells inside valve cover."},
            {"Category": "Engine and Cooling", "Part Name": "Rocker Cover Gasket (RH)", "OEM Part Number": "13270AA27A", "Quantity": 1, "Price": 24.00, "Notes": "Premium rubber valve cover gasket (passenger side)."},
            {"Category": "Engine and Cooling", "Part Name": "Rocker Cover Gasket (LH)", "OEM Part Number": "13272AA21A", "Quantity": 1, "Price": 24.00, "Notes": "Premium rubber valve cover gasket (driver side)."},
            {"Category": "Engine and Cooling", "Part Name": "Cam Carrier O-Ring", "OEM Part Number": "806915170", "Quantity": 4, "Price": 3.20, "Notes": "Sealing ring for EJ257 camshaft carrier housing."},
            {"Category": "Engine and Cooling", "Part Name": "Cylinder Head Gasket (RH)", "OEM Part Number": "11044AA790", "Quantity": 1, "Price": 55.00, "Notes": "Multi-layer steel (MLS) head gasket for extreme combustion pressures."},
            {"Category": "Engine and Cooling", "Part Name": "Cylinder Head Gasket (LH)", "OEM Part Number": "10944AA080", "Quantity": 1, "Price": 55.00, "Notes": "Multi-layer steel (MLS) head gasket (driver side)."},
            {"Category": "Engine and Cooling", "Part Name": "Connecting Rod Bolt", "OEM Part Number": "12109AA120", "Quantity": 8, "Price": 8.50, "Notes": "High-tensile Torque-to-Yield (TTY) connecting rod bolt (must replace once used)."},
            {"Category": "Engine and Cooling", "Part Name": "Upper Oil Pan O-Ring", "OEM Part Number": "806932030", "Quantity": 3, "Price": 4.50, "Notes": "Crankcase-to-oil-pan fluid passage sealing ring."},
            {"Category": "Engine and Cooling", "Part Name": "Crankshaft Extension O-Ring", "OEM Part Number": "806939060", "Quantity": 1, "Price": 3.00, "Notes": "Timing gear snout spacer seal."},
            {"Category": "Engine and Cooling", "Part Name": "Front Crankshaft Oil Seal", "OEM Part Number": "806750080", "Quantity": 1, "Price": 9.50, "Notes": "Vital oil seal located behind the crankshaft timing sprocket."},
            {"Category": "Engine and Cooling", "Part Name": "Fuel Injector O-Ring (Upper)", "OEM Part Number": "16608KA000", "Quantity": 4, "Price": 4.50, "Notes": "Seal between top fuel rail and fuel injector."},
            {"Category": "Engine and Cooling", "Part Name": "Fuel Injector O-Ring (Lower)", "OEM Part Number": "16698AA110", "Quantity": 4, "Price": 5.00, "Notes": "Seal between injector nozzle and intake manifold."},
            {"Category": "Engine and Cooling", "Part Name": "Oil Filter Assembly (Domestic Blue)", "OEM Part Number": "15208AA15A", "Quantity": 1, "Price": 8.50, "Notes": "Alternative standard blue paper-endcap filter element."},
            {"Category": "Engine and Cooling", "Part Name": "Oil Drain Plug Gasket (Copper Flat)", "OEM Part Number": "803916010", "Quantity": 1, "Price": 1.50, "Notes": "Alternative flat metal drain plug washer."},
            {"Category": "Engine and Cooling", "Part Name": "Turbo Oil Return Line Hose", "OEM Part Number": "K04535-TurboHose", "Quantity": 1, "Price": 21.00, "Notes": "Heat-resistant hose routing oil from turbo back to cylinder head block."},
            {"Category": "Engine and Cooling", "Part Name": "Intercooler Stay Grommet", "OEM Part Number": "K04535-Grommet", "Quantity": 1, "Price": 10.00, "Notes": "Rubber isolation stay grommet for top-mount intercooler."},
            {"Category": "Engine and Cooling", "Part Name": "Upper Evap/Vacuum Line", "OEM Part Number": "GD-EvapLine", "Quantity": 1, "Price": 9.22, "Notes": "Evaporative purge vacuum line assembly."},
            {"Category": "Engine and Cooling", "Part Name": "PCV Hose Assembly", "OEM Part Number": "11815AA120", "Quantity": 1, "Price": 28.00, "Notes": "Standard PCV hose routing for crankcase ventilation."},
            {"Category": "Engine and Cooling", "Part Name": "Timing Belt Idler Pulley (Smooth)", "OEM Part Number": "13073AA142", "Quantity": 2, "Price": 45.00, "Notes": "Smooth idler pulley for DOHC EJ timing chain/belt assembly."},
            {"Category": "Engine and Cooling", "Part Name": "Timing Belt Idler Pulley (Toothed)", "OEM Part Number": "13085AA080", "Quantity": 1, "Price": 52.00, "Notes": "Toothed idler pulley to guide the timing belt."},
            {"Category": "Engine and Cooling", "Part Name": "Mishimoto X-Line Aluminum Radiator", "OEM Part Number": "Mishimoto-Rad", "Quantity": 1, "Price": 285.00, "Notes": "All-aluminum dual-core high performance radiator."},
            {"Category": "Engine and Cooling", "Part Name": "Cylinder 4 Chamber Cooling System Kit", "OEM Part Number": "GDT-Cooling", "Quantity": 1, "Price": 79.00, "Notes": "Bypasses hot coolant from rear cylinder head to heater core line."},
            {"Category": "Engine and Cooling", "Part Name": "IAG Air/Oil Separator (AOS)", "OEM Part Number": "IAG-AOS", "Quantity": 1, "Price": 399.00, "Notes": "Centrifugal swirl pot returning blow-by oil to the oil pan."},
            {"Category": "Engine and Cooling", "Part Name": "Tomei Expreme Ti Titanium Cat-Back Exhaust", "OEM Part Number": "Tomei-Expreme", "Quantity": 1, "Price": 1090.00, "Notes": "Full titanium lightweight cat-back exhaust system."},
            {"Category": "Engine and Cooling", "Part Name": "Invidia Gemini R400 Quad Tip Exhaust", "OEM Part Number": "Invidia-R400", "Quantity": 1, "Price": 1150.00, "Notes": "High-performance stainless steel exhaust with deep quad tips."},
            {"Category": "Engine and Cooling", "Part Name": "COBB SF Intake + Airbox Combo", "OEM Part Number": "COBB-Intake", "Quantity": 1, "Price": 375.00, "Notes": "Air filter intake assembly with protective composite heat shield."},
            {"Category": "Engine and Cooling", "Part Name": "GrimmSpeed StealthBox Cold Air Intake", "OEM Part Number": "GrimmSpeed-Stealth", "Quantity": 1, "Price": 325.00, "Notes": "Red cold air intake with low-profile high-flow box layout."},
            {"Category": "Engine and Cooling", "Part Name": "Perrin Top Mount Intercooler (TMIC)", "OEM Part Number": "Perrin-TMIC", "Quantity": 1, "Price": 690.00, "Notes": "Large high-capacity intercooler core resists heat soak."},

            # Maintenance
            {"Category": "Maintenance", "Part Name": "Spark Plug Set (NGK Laser Iridium)", "OEM Part Number": "22401AA670", "Quantity": 4, "Price": 60.00, "Notes": "NGK SILFR6A (7913) gapped to 0.030\". Replace every 30,000 to 60,000 miles."},
            {"Category": "Maintenance", "Part Name": "Engine Cabin Air Filter", "OEM Part Number": "72880FG000", "Quantity": 1, "Price": 25.00, "Notes": "Multi-layer HEPA Active Carbon filter. Replace every 12 to 24 months."},
            {"Category": "Maintenance", "Part Name": "Subaru OEM Touch-Up Paint", "OEM Part Number": "SOA326-Paint", "Quantity": 1, "Price": 31.00, "Notes": "Color-matched touch-up brush for chip repair."},

            # Suspension and Brakes
            {"Category": "Suspension and Brakes", "Part Name": "Front Brembo Brake Rotor (Each)", "OEM Part Number": "26300FE070", "Quantity": 2, "Price": 150.00, "Notes": "High-carbon vented cast iron 326mm brake rotor."},
            {"Category": "Suspension and Brakes", "Part Name": "Rear Brembo Brake Pad Set", "OEM Part Number": "26696FG000", "Quantity": 1, "Price": 95.00, "Notes": "High-performance pads. Includes multi-layer backing shims."},
            {"Category": "Suspension and Brakes", "Part Name": "Front Brembo Caliper Bolt (Each)", "OEM Part Number": "901120103", "Quantity": 4, "Price": 6.00, "Notes": "High-strength Grade 10.9 steel caliper-to-knuckle bolt."},
            {"Category": "Suspension and Brakes", "Part Name": "Rear Brembo Caliper Mounting Bolt", "OEM Part Number": "901120102", "Quantity": 4, "Price": 5.00, "Notes": "High-strength steel caliper mounting bolt."},
            {"Category": "Suspension and Brakes", "Part Name": "Caliper Bleeder Screws", "OEM Part Number": "M8/M10-Bleeder", "Quantity": 1, "Price": 12.00, "Notes": "Caliper hydraulic air bleed valves (Set of 4)."},
            {"Category": "Suspension and Brakes", "Part Name": "Brake Hose Banjo Bolt", "OEM Part Number": "M10-Banjo", "Quantity": 1, "Price": 8.00, "Notes": "Fluid delivery banjo bolt with fresh copper washers."},
            {"Category": "Suspension and Brakes", "Part Name": "Brembo Caliper Bolt Set", "OEM Part Number": "SOA-BremboBolt", "Quantity": 1, "Price": 6.00, "Notes": "Replacement bolt for brake bracket."},
            {"Category": "Suspension and Brakes", "Part Name": "BC Racing BR Series Coilovers (Adjustable)", "OEM Part Number": "Coilovers", "Quantity": 1, "Price": 1195.00, "Notes": "30-way damping and ride height adjustable coilover struts."},
            {"Category": "Suspension and Brakes", "Part Name": "Time-Sert M12x1.5 Metric Thread Repair Kit", "OEM Part Number": "Time-Sert-1215", "Quantity": 1, "Price": 85.00, "Notes": "Steel insert kit to repair stripped Brembo caliper ears."},
            {"Category": "Suspension and Brakes", "Part Name": "Front Sway Bar 24mm Stabilizer Bushing", "OEM Part Number": "20401VA000", "Quantity": 2, "Price": 14.00, "Notes": "Molded rubber bushing for front anti-roll bar."},
            {"Category": "Suspension and Brakes", "Part Name": "Rear Sway Bar 20mm Stabilizer Bushing", "OEM Part Number": "20451VA000", "Quantity": 2, "Price": 12.00, "Notes": "Molded rubber bushing for rear anti-roll bar."},
            {"Category": "Suspension and Brakes", "Part Name": "Front Stabilizer Sway Bar Endlink", "OEM Part Number": "20470AJ010", "Quantity": 2, "Price": 29.50, "Notes": "Heavy-duty connecting links for front stabilizer bar."},

            # Manual Transmission
            {"Category": "Manual Transmission", "Part Name": "6-Speed MT Drain Plug (T70 Torx)", "OEM Part Number": "32103AA080", "Quantity": 1, "Price": 10.00, "Notes": "Magnetic drain plug for TY856 transmission case."},
            {"Category": "Manual Transmission", "Part Name": "6-Speed MT Drain Plug Crush Washer", "OEM Part Number": "32103AA012", "Quantity": 1, "Price": 4.50, "Notes": "Sealing gasket for manual transmission drain plug."},
            {"Category": "Manual Transmission", "Part Name": "6-Speed MT Drain Plug (Early Spec)", "OEM Part Number": "32103AA070", "Quantity": 1, "Price": 15.00, "Notes": "Early model year 6-speed magnetic plug."},
            {"Category": "Manual Transmission", "Part Name": "6-Speed MT Drain Plug Gasket (Copper)", "OEM Part Number": "32103AA011", "Quantity": 1, "Price": 9.00, "Notes": "Copper sealing washer for manual transmission drain plug."},
            {"Category": "Manual Transmission", "Part Name": "Mach V Braided Clutch Line", "OEM Part Number": "MachV-ClutchLine", "Quantity": 1, "Price": 29.00, "Notes": "Stainless steel braided high-pressure clutch hydraulic line."},
            {"Category": "Manual Transmission", "Part Name": "OEM Quality Clutch Slave Cylinder", "OEM Part Number": "Slave-Cylinder", "Quantity": 1, "Price": 49.00, "Notes": "Hydraulic clutch actuator cylinder assembly."},
            {"Category": "Manual Transmission", "Part Name": "Subaru Bell Housing Bolts/Studs", "OEM Part Number": "Bellhousing-Bolt", "Quantity": 1, "Price": 4.43, "Notes": "High-tensile bellhousing to manual transmission mounting stud."},
            {"Category": "Manual Transmission", "Part Name": "Exedy Stage 1 Organic Performance Clutch Kit", "OEM Part Number": "FJK1001", "Quantity": 1, "Price": 425.00, "Notes": "Includes pressure plate, organic disc, and bearings."},
            {"Category": "Manual Transmission", "Part Name": "Standard Flywheel Assembly DOHC EJ257", "OEM Part Number": "12310AA410", "Quantity": 1, "Price": 225.00, "Notes": "Factory standard single-mass flywheel assembly."},

            # Driveline and Differential
            {"Category": "Driveline and Differential", "Part Name": "Motul STI 6-Speed Transmission Fluid Kit", "OEM Part Number": "Motul-6MT-Kit", "Quantity": 1, "Price": 165.00, "Notes": "Full fluid kit with gearbox and rear differential lubricants."},
            {"Category": "Driveline and Differential", "Part Name": "Hubcentric Rings (Set of 4)", "OEM Part Number": "Hub-Rings", "Quantity": 1, "Price": 11.00, "Notes": "Custom polymer alignment rings for aftermarket wheels."},
            {"Category": "Driveline and Differential", "Part Name": "Rear Differential Rear Crossmember Bushing Insert Kit", "OEM Part Number": "KDT903", "Quantity": 1, "Price": 45.00, "Notes": "Urethane inserts to stiffen differential cradle mounting."},
            {"Category": "Driveline and Differential", "Part Name": "Torque Solution Pitch Stop Mount", "OEM Part Number": "TS-PS-002", "Quantity": 1, "Price": 110.00, "Notes": "Billet aluminum pitch stop mount to reduce drivetrain slop."},

            # Heating and Air Conditioning
            {"Category": "Heating and Air Conditioning", "Part Name": "AC Drive Stretch Belt Kit", "OEM Part Number": "11718AA082", "Quantity": 1, "Price": 45.00, "Notes": "Replaces 11718AA081. Specialty EPDM belt (includes plastic guide installer tool)."},

            # Steering
            {"Category": "Steering", "Part Name": "Alternator / Power Steering Belt", "OEM Part Number": "809218460", "Quantity": 1, "Price": 28.00, "Notes": "V-Ribbed EPDM accessory drive belt."},
            {"Category": "Steering", "Part Name": "Hydraulic Power Steering Pump Assembly", "OEM Part Number": "34430FG010", "Quantity": 1, "Price": 295.00, "Notes": "Factory OEM hydraulic power steering pump."},
            {"Category": "Steering", "Part Name": "High-Durometer Steering Rack Bushing Kit", "OEM Part Number": "16.1010", "Quantity": 1, "Price": 35.00, "Notes": "Polyurethane bushings to eliminate play in the steering rack."},
            {"Category": "Steering", "Part Name": "Updated Steering Gearbox Rattle Tension Spring", "OEM Part Number": "34130VA000", "Quantity": 1, "Price": 12.50, "Notes": "TSB 04-17-17-R tension spring to fix gearbox rattle."},

            # Electrical
            {"Category": "Electrical", "Part Name": "Hanshin OEM Ignition Coil Pack", "OEM Part Number": "22433AA641", "Quantity": 4, "Price": 110.00, "Notes": "Hanshin OEM Service Component. Prevents misfires under boost."},
            {"Category": "Electrical", "Part Name": "Lead-Acid Group 35 Battery", "OEM Part Number": "Battery-Group35", "Quantity": 1, "Price": 140.00, "Notes": "Cold weather starting battery with 550-640 CCA."},
            {"Category": "Electrical", "Part Name": "Starlink 3G DCM Parasitic Battery Drain Bypass Harness", "OEM Part Number": "Starlink-Bypass", "Quantity": 1, "Price": 49.00, "Notes": "Loops audio around the DCM to stop battery draw."},

            # Interior
            {"Category": "Interior", "Part Name": "Glovebox Damper Clip / Hinge pin", "OEM Part Number": "Glovebox-Clip", "Quantity": 1, "Price": 8.50, "Notes": "OEM dashboard glovebox damper hinge retention pin."},
            {"Category": "Interior", "Part Name": "STI Leather/Alcantara Weighted Shift Knob", "OEM Part Number": "Shift-Knob", "Quantity": 1, "Price": 125.00, "Notes": "Genuine weighted shift knob for the TY856 transmission."},
            {"Category": "Interior", "Part Name": "Updated Clutch/Brake Pedal Bracket Assembly", "OEM Part Number": "Pedal-Assembly", "Quantity": 1, "Price": 195.00, "Notes": "TSB 12-190-15 reinforced bracket to resolve creaking noise."},

            # Body
            {"Category": "Body", "Part Name": "Transmission Crossmember Bolt Kit", "OEM Part Number": "Crossmember-Bolts", "Quantity": 1, "Price": 18.00, "Notes": "High-tensile fasteners for subframe crossmember mounting."},
            {"Category": "Body", "Part Name": "Bumper Vents Set", "OEM Part Number": "Bumper-Vents", "Quantity": 1, "Price": 43.63, "Notes": "Bumper outer vents trim kit."},
            {"Category": "Body", "Part Name": "Front Bumper Side Support", "OEM Part Number": "Bumper-Support", "Quantity": 1, "Price": 12.82, "Notes": "Bumper fascia side attachment guide bracket."},
            {"Category": "Body", "Part Name": "Under-Engine Shield Cover Splash Guard", "OEM Part Number": "56410VA000", "Quantity": 1, "Price": 75.00, "Notes": "Molded composite splash cover protecting the engine oil pan."},

            # Door
            {"Category": "Door", "Part Name": "Door Hinge Lubricant", "OEM Part Number": "White Lithium Grease", "Quantity": 1, "Price": 8.00, "Notes": "Applied to door hinge assemblies and latching pins."},
            {"Category": "Door", "Part Name": "Front Door Checker/Stay Assembly", "OEM Part Number": "61280VA000", "Quantity": 2, "Price": 24.50, "Notes": "OEM door checker stay to hold the door in open positions."},
            {"Category": "Door", "Part Name": "Door Outer Window Belt Weatherstrip (Front RH)", "OEM Part Number": "61280VA010", "Quantity": 1, "Price": 45.00, "Notes": "Molded window belt moulding to seal the door glass."},

            # Automatic Transmission
            {"Category": "Automatic Transmission", "Part Name": "N/A (STI is exclusively 6MT manual)", "OEM Part Number": "N/A", "Quantity": 0, "Price": 0.00, "Notes": "S4 tS CVT variant uses ATF-HP (system capacity ~7.7 Liters)."}
        ]


        import pandas as pd
        df_catalog = pd.DataFrame(parts_catalog)
        
        # Interactive search & filter controls
        col_search, col_cat = st.columns([2, 1])
        with col_search:
            search_query = st.text_input("⌕ Search parts, categories, or notes:", "").strip().lower()
        with col_cat:
            category_list = ["All Categories"] + sorted(list(set(df_catalog["Category"].tolist())))
            selected_category = st.selectbox("▤ Filter by category:", category_list)
        
        # Security Input Sanitization: strip HTML tags and hazardous characters to prevent XSS
        sanitized_query = "".join([c for c in search_query if c not in '<>"\'\\;']) if search_query else ""
        
        # Filter the dataframe
        filtered_df = df_catalog.copy()
        if selected_category != "All Categories":
            filtered_df = filtered_df[filtered_df["Category"] == selected_category]
        
        # Expand search functionality to search across all columns! (Service Status and Required Qty removed)
        if search_query:
            filtered_df = filtered_df[
                filtered_df["Part Name"].str.lower().str.contains(sanitized_query) |                 filtered_df["OEM Part Number"].str.lower().str.contains(sanitized_query) |                filtered_df["Category"].str.lower().str.contains(sanitized_query) |                filtered_df["Quantity"].astype(str).str.lower().str.contains(sanitized_query) |                filtered_df["Notes"].str.lower().str.contains(sanitized_query)
            ]
        
        # Format Prices and reorder columns for display
        display_df = filtered_df.copy()
        display_df["Price"] = display_df["Price"].apply(lambda x: f"${x:.2f}")
        
        # Reorder columns to showcase consolidation (Service Status and Required Qty removed)
        cols_order = ["Category", "Part Name", "OEM Part Number", "Quantity", "Price", "Notes"]
        display_df = display_df[cols_order]
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    # Fluids Tab
    with tab_fluids:
        st.subheader("⛢ Subaru Recommended Fluids, Grades & Capacities")
        st.write("Maintain exact fluid dynamics and thermal protection parameters for your symmetrical AWD drivetrain.")
        
        fluids_data = [
            {
                "Compartment": "Engine Crankcase (EJ257)",
                "Fluid Type / Specification": "API SM / SN Full Synthetic (SAE 5W-30 or 5W-40)",
                "Capacity": "4.5 Quarts (4.3 Liters) with filter"
            },
            {
                "Compartment": "Manual Transmission & Front Diff (6-Speed Transaxle)",
                "Fluid Type / Specification": "API GL-5 High Performance Gear Oil (SAE 75W-90)",
                "Capacity": "Dry Fill: 4.1 Quarts (4.1 Liters / 8.7 Pints) | Service Fill: ~3.5 Quarts (3.3 Liters)"
            },
            {
                "Compartment": "Rear Differential",
                "Fluid Type / Specification": "API GL-5 Hypoid Gear Oil (SAE 75W-90 / Motul 90PA for track)",
                "Capacity": "1.0 Quart (0.95 Liters / 2.1 Pints)"
            },
            {
                "Compartment": "Engine Cooling System",
                "Fluid Type / Specification": "Subaru Super Coolant (Pre-Mixed Blue)",
                "Capacity": "8.1 Quarts (7.7 Liters / 2.025 Gallons)"
            },
            {
                "Compartment": "Brake & Clutch Reservoirs",
                "Fluid Type / Specification": "DOT 3 or DOT 4 Hydraulic Fluid",
                "Capacity": "Fill to Max Reservoir Line (~1.0 Liter)"
            },
            {
                "Compartment": "Power Steering System (Hydraulic)",
                "Fluid Type / Specification": "Dexron III / Subaru ATF-HP",
                "Capacity": "~0.8 Liters (System capacity)"
            }
        ]
        
        import pandas as pd
        df_fluids = pd.DataFrame(fluids_data)
        st.dataframe(df_fluids, use_container_width=True, hide_index=True)

    # History Tab
    with tab_history:
        # st.subheader("Maintenance & Service Log")
        
        history = get_cached_history()
        
        # --- INDIVIDUAL ITEM COMPLETION LEDGER ---
        st.markdown("### ▤ Individual Item Completion Ledger")
        st.write("Scan the last logged date and mileage for each individual maintenance and inspection service. This ledger automatically indexes your entire history folder to prevent items from falling through the cracks.")
    
        ledger_data = []
        for item in schedule_items:
            item_name = item["name"]
            interval = f"Every {item['interval']:,} mi" if isinstance(item['interval'], int) else str(item['interval'])
        
            # Find the latest logged completion in history
            last_date = "No Record"
            last_mileage = "Never Logged"
            raw_last_mi = 0
        
            if history:
                # Search chronologically forward so the last match is the most recent
                for entry in history:
                    if item_name in entry.get("completed_items", []):
                        last_date = entry["date"]
                        last_mileage = f"{entry['mileage']:,} mi"
                        raw_last_mi = entry["mileage"]
        
            # Determine Status Badge
            if last_date == "No Record":
                status = "◇ Not Yet Logged"
            elif mileage is None:
                status = "◆ Logged"
            else:
                # If currently marked as due by the scheduler engine, mark as due/overdue
                if item["due"]:
                    status = "▲ Overdue / Due Now"
                else:
                    status = "◆ Completed & OK"
                
            ledger_data.append({
                "Maintenance Item": item_name,
                "Last Completed Date": last_date,
                "Last Completed Mileage": last_mileage,
                "Interval": interval,
                "Current Status": status
            })
        
        import pandas as pd
        df_ledger = pd.DataFrame(ledger_data)
    
        # Render clean interactive dataframe
        st.dataframe(
            df_ledger, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Current Status": st.column_config.TextColumn(
                    "Current Status",
                    help="◆ OK: Item was recently completed. ▲ Due: Needs attention based on mileage or history. ◇ Not Logged: No entry in history."
                )
            }
        )

        st.markdown("<hr style='margin:15px 0; border-color:#eee;'/>", unsafe_allow_html=True)
        st.markdown("### ▤ Chronological Service History Timeline")
        st.write("Below is a detailed timeline showing each completed service item in chronological order as logged from your checklist.")
    
        timeline_data = []
        if history:
            for entry in history:
                date_val = entry.get("date", "")
                time_val = entry.get("time", "00:00")
                mi_val = entry.get("mileage", 0)
                for item in entry.get("completed_items", []):
                    timeline_data.append({
                        "Date": date_val,
                        "Time": time_val,
                        "Odometer Mileage (mi)": mi_val,
                        "Completed Service Item": item
                    })
        
            df_timeline = pd.DataFrame(timeline_data)
            if not df_timeline.empty:
                # Always sort the timeline table descending by date and by time as default.
                df_timeline = df_timeline.sort_values(by=["Date", "Time"], ascending=[False, False])
                df_timeline["Odometer Mileage (mi)"] = df_timeline["Odometer Mileage (mi)"].apply(lambda x: f"{x:,} mi")
                
                # Reorder columns to place Time next to Date
                df_timeline = df_timeline[["Date", "Time", "Odometer Mileage (mi)", "Completed Service Item"]]
                
                st.dataframe(
                    df_timeline, 
                    use_container_width=True, 
                    hide_index=True
                )
            else:
                st.info("No timeline items logged yet.")
        else:
            st.info("No timeline items logged yet.")

        # --- LOCAL CACHE SYNC & RECOVERY TOOLS ---
        api_url = None
        if HAS_STREAMLIT:
            try:
                api_url = st.secrets.get("gsheets_api_url")
            except Exception:
                pass
                
        if api_url:
            st.markdown("<hr style='margin:15px 0; border-color:#eee;'/>", unsafe_allow_html=True)
            st.markdown("### ⚙ Local Cache Sync & Recovery Tools")
            st.write("If you have offline records saved in your local JSON file (`subaru_maintenance_history.json`) that are missing from your Google Sheet, use this tool to synchronize them.")
            
            col_merge, col_spacer = st.columns([1, 2])
            with col_merge:
                if st.button("📤 Push Local Items to Sheets", use_container_width=True, help="Scan local file and upload any missing entries to Google Sheets"):
                    # Load directly from local file (bypassing session state cache)
                    local_records = []
                    if os.path.exists(HISTORY_FILE):
                        try:
                            with open(HISTORY_FILE, "r") as f:
                                local_records = json.load(f)
                        except Exception:
                            pass
                    
                    if local_records:
                        # Fetch latest cloud records to avoid duplicates
                        cloud_records = []
                        try:
                            import time
                            cb_url = f"{api_url}&_={int(time.time())}" if "?" in api_url else f"{api_url}?_={int(time.time())}"
                            res = requests.get(cb_url, timeout=6)
                            if res.status_code == 200:
                                cloud_records = res.json()
                        except Exception:
                            pass
                        
                        # Create set of cloud keys: (date, mileage, completed_items_key)
                        cloud_keys = set()
                        for entry in cloud_records:
                            items_key = ";".join(sorted(entry.get("completed_items", [])))
                            cloud_keys.add((entry.get("date"), entry.get("mileage"), items_key))
                            
                        # Find local records not in cloud keys
                        to_upload = []
                        for entry in local_records:
                            items_key = ";".join(sorted(entry.get("completed_items", [])))
                            key = (entry.get("date"), entry.get("mileage"), items_key)
                            if key not in cloud_keys:
                                to_upload.append(entry)
                                
                        if to_upload:
                            uploaded_count = 0
                            for entry in to_upload:
                                try:
                                    headers = {"Content-Type": "application/json"}
                                    requests.post(api_url, json=entry, headers=headers, timeout=5)
                                    uploaded_count += 1
                                except Exception:
                                    pass
                            
                            st.success(f"✓ Uploaded {uploaded_count} missing records to Google Sheets!")
                            # Clear session cache to reload from cloud on rerun
                            if HAS_STREAMLIT and "history_cache" in st.session_state:
                                del st.session_state["history_cache"]
                            st.rerun()
                        else:
                            st.info("Everything is already in sync! No missing records found in local JSON.")
                    else:
                        st.warning("No local backup JSON file found or file is empty.")

    # Manual Tab
    with tab_manual:
        st.subheader("☰ Official Subaru WRX STI Reference Manual")
        
        # Section 1: Specifications
        with st.expander("☰ Subaru WRX STI Powertrain & Chassis Specifications"):
            st.markdown(
                """
                ### ☰ Official 2016 Subaru WRX STI (GUS Model) Specifications
                *Based strictly on official 2016 US market specifications.*

                ##### ⚙ Engine & Powertrain
                | Specification | Value / Detail |
                | :--- | :--- |
                | **Engine Manufacturer / Type** | Subaru flat-four horizontally opposed DOHC "Boxer" 4-cylinder, 16 valves (4 valves/cyl). |
                | **Displacement / Size** | 2.5 Liter (2,457 cc / 149.935 cu in). |
                | **Bore × Stroke** | 99.5 mm × 79.0 mm (3.92 in × 3.11 in) with 1.26 oversquare ratio. |
                | **Compression Ratio** | 8.2:1. |
                | **Fuel System / Induction** | Multi-point fuel injection (MPFI). Single-scroll turbocharger with functional hood scoop & aluminum cross-flow intercooler (14.7 PSI factory peak boost). |
                | **Engine Construction** | Cast aluminum-alloy block and cylinder heads. |
                | **Lubrication System** | Wet sumped. |
                | **Maximum Power Output** | **305 bhp (309 PS / 227 kW) @ 6,000 RPM**. |
                | **Maximum Torque Output** | **290 lb-ft (393 N·m / 40.1 kgm) @ 4,000 RPM**. |
                | **Specific Power Output** | 124.1 bhp/litre (125.9 PS/litre / 92.6 kW/litre). |
                | **Specific Torque Output** | 159.95 N·m/litre. |

                ##### ⚙ Drivetrain & Transmission
                | Component | Design Specification & Mechanical Parameters |
                | :--- | :--- |
                | **Gearbox Designation** | TY856 Series 6-speed manual, reinforced casing. Fully synchronized reverse. |
                | **Gear Ratios** | Top gear ratio: 0.76:1. Final drive ratio: 3.90:1. |
                | **Engine Position / Layout** | Front-positioned, longitudinal. |
                | **Symmetrical AWD Layout** | Symmetrical All-Wheel Drive. Multi-Mode Driver Controlled Center Differential (DCCD) coordinating an electromagnetic multi-plate clutch and mechanical LSD. |
                | **Front Differential** | Helical limited-slip differential (LSD). |
                | **Rear Differential** | Torsen limited-slip differential (LSD). |

                ##### ⌿ Dimensions & Weights
                | Dimension / Parameter | Metric Value | Imperial / US Value |
                | :--- | :--- | :--- |
                | **Wheelbase** | 2649 mm. | 104.3 inches. |
                | **Track / Tread (Front)** | 1529 mm. | 60.2 inches. |
                | **Track / Tread (Rear)** | 1539 mm. | 60.6 inches. |
                | **Overall Length** | 4595 mm. | 180.9 inches. |
                | **Overall Width** | 1796 mm. | 70.7 inches. |
                | **Overall Height** | 1476 mm. | 58.1 inches. |
                | **Ground Clearance** | Performance stance with 1.73 length-to-wheelbase ratio. | |
                | **Kerb Weight** | **1536 kg**. | **3386 lbs**. |
                | **Power-to-weight ratio** | 198.57 bhp/tonne (0.2 bhp/kg). | |
                | **Weight-to-power ratio** | 11.28 lb/bhp (6.75 kg/kW). | |

                ##### ⛢ Fluids, Capacities & Economy
                | Parameter | Metric Value | Imperial / US Value |
                | :--- | :--- | :--- |
                | **Fuel Tank Capacity** | 60.2 litres. | 15.9 US Gallons (13.2 UK Gal). |
                | **EPA Fuel Consumption** | 13.8 / 10.2 / 12.4 L/100km. | **17 / 23 / 19 MPG** (City/Highway/Combined). |
                | **Engine Oil Capacity** | 4.3 Liters. | 4.5 Quarts with filter. |
                | **Engine Coolant Capacity** | 7.7 Liters. | 8.1 Quarts. |

                ##### ⌾ Chassis, Steering, Wheels & Brakes
                | Component | Design Specification & Mechanical Parameters |
                | :--- | :--- |
                | **Steering System** | Hydraulic power-assisted rack & pinion steering with 13.3:1 quick-ratio. |
                | **Turns Lock-to-Lock** | **2.500 turns**. |
                | **Front Suspension** | Independent inverted MacPherson KYB struts with forged aluminum alloy lower suspension arm, high-durometer pillow ball mounts and bushings, 24 mm stabilizer bar. |
                | **Rear Suspension** | Independent double-wishbone design with subframe stiffener bar and 20 mm stabilizer bar. |
                | **Wheel Hub Bolt Pattern** | Standardized **5x114.3 mm** bolt pattern with **56.1 mm** center bore. |
                | **Wheel Rim Size** | 8.5J × 18 inches front and rear. |
                | **Tire Sizing** | **245/40 R18 97W** front and rear high-performance tires. |
                | **Brembo Brake Calipers** | Power-assisted Brembo brake system with 4-piston fixed front calipers and dual-piston fixed rear calipers. |
                | **Brake Rotors** | Front ventilated discs: **325 mm / 326 mm** diameter, **30 mm** thick. Rear ventilated discs: **315 mm / 316 mm** diameter, **20 mm** thick. |
                | **Braking Safety Systems** | Super Sport ABS (4-channel/4-sensor/4-wheel with g-load sensor), Active Torque Vectoring, Brake Assist, and Electronic Brake-force Distribution (EBD). |
                """
            )

        # Section 2: Torque specs
        with st.expander("⎔ Critical DIY Torque Specifications (Factory & Corrected Specs)"):
            st.markdown(
                """
                | Component Class | Fastener Description | Thread Spec | Torque Value (Imperial) | Torque Value (Metric) | Notes / Application |
                | :--- | :--- | :--- | :--- | :--- | :--- |
                | **Engine Core** | Spark Plugs (Dry Threads) | M14 | **13 to 17 ft-lbs** | 18 to 23 N-m | Factory Standard / Subimods |
                | | Spark Plugs (Pro Street Spec) | M14 | **15.5 ft-lbs** | 21 N-m | My Pro Street Ignition |
                | | Ignition Coil Pack Bolt | M6 | **11.8 ft-lbs** | 16 N-m | My Pro Street Ignition |
                | | Air Pump Duct Bolt | M6 | **6.6 ft-lbs** | 9 N-m | My Pro Street Ignition |
                | | Oil Pan Drain Plug | M20 | **33 to 34 ft-lbs** | 44 to 46 N-m | Factory Standard / Subimods |
                | | Valve Cover Fasteners | M6 | **4.7 to 5.8 ft-lbs** | 6.4 to 7.8 N-m | Factory Standard (~56-70 in-lbs) |
                | | Valve Cover Bolts (Pro Street) | M6 | **3.3 to 4.7 ft-lbs** | 4.5 to 6.4 N-m | My Pro Street Range |
                | | Intake Manifold-to-Head | M8 | **17 to 20 ft-lbs** | 23 to 27 N-m | Factory Standard / Subimods |
                | | Intake Manifold Bolts (Pro Street) | M8 | **18 ft-lbs** | 24.4 N-m | My Pro Street Spec |
                | | Exhaust Manifold-to-Head | M10 | **22 to 29 ft-lbs** | 30 to 39 N-m | Factory Standard / Subimods |
                | | Crankshaft Pulley Center Bolt | M18 | **35 ft-lbs + 60° turn** | 47 N-m + 60° turn | Factory Standard |
                | | Water Pump Mounting Bolts | M6 | **9 ft-lbs** | 12 N-m | Factory Standard |
                | **Drivetrain** | Gearbox Fill / Drain Plugs | M18 | **37 ft-lbs** | 50 N-m | Alum Washer |
                | | Gearbox Drain Plug | M18 | **52 ft-lbs** | 70 N-m | Copper Washer |
                | | Rear Diff Fill / Drain Plugs | M20 | **36 to 43 ft-lbs** | 49 to 58 N-m | Hypoid Housing |
                | | Clutch Pressure Plate | M8 | **12 ft-lbs** | 16 N-m | Clutch Cover |
                | | Flywheel Assembly Bolts | M10 | **55 ft-lbs** | 75 N-m | Crank Connection |
                | **Chassis** | Wheel Lug Nuts (Alloy Hub) | M12 x 1.25 | **89 to 94 ft-lbs** | 120 to 127 N-m | Factory Standard / Subimods |
                | | Wheel Lug Nuts (Pro Street) | M12 x 1.25 | **88.5 ft-lbs** | 120 N-m | My Pro Street |
                | | Front Upper Strut Hat Nuts | M10 | **22 ft-lbs** | 30 N-m | Strut Tower |
                | | Knuckle Lower Strut Bolts | M14 | **129 ft-lbs** | 175 N-m | Alignment Clevis |
                | | Rear Upper Strut Hat Nuts | M10 | **22 ft-lbs** | 30 N-m | Rear Hat |
                | | Rear Lower Strut Mount Bolt | M14 | **162 ft-lbs** | 220 N-m | Trailing Arm |
                | | Rear Main Subframe Bolts | M14 | **106.9 ft-lbs** | 145 N-m | Cradle Mounting |
                | **Brakes** | Front Brembo Caliper (Corrected) | M12 x 1.5 | **80 ft-lbs** | 114 N-m | Caliper-to-Knuckle |
                | | Rear Brembo Caliper Bolts | M10 x 1.5 | **52.8 ft-lbs** | 71.5 N-m | Caliper-to-Bracket |
                | | Brake Hose Banjo Bolt | M10 | **19.2 to 22 ft-lbs** | 26 to 30 N-m | Copper Crush Washers |
                | | Caliper Bleeder Screws | M8 / M10 | **14.8 ft-lbs** | 20 N-m | Bleed Screws |
                """
            )

        # Section 3: My Pro Street DIY Pitfall & Warning Guide
        with st.expander("▲ My Pro Street DIY Pitfall & Warning Guide"):
            st.markdown(
                """
                ### ▲ Why Torque Specs Matter on the Subaru STI (My Pro Street Guide)
                Improper torque on your horizontally opposed boxer engine is a major cause of mechanical failures due to its aluminum components, high vibration, and intense heat cycles. "Good-n-tight" is not an official Subaru engineering measurement—use calibrated torque wrenches to avoid expensive repairs!
                
                #### 1. Spark Plug Torque: Why It Matters
                *   **Pro Street Target Spec:** **15.5 ft-lb (21 N·m)**.
                *   **Over-tightening Hazards:** Can strip soft aluminum cylinder head threads, damage plug gaskets, crack the delicate ceramic insulators, or cause improper heat transfer. Thread repair on an EJ head is extremely difficult.
                *   **Under-tightening Hazards:** Loose spark plugs can cause severe combustion leakage, engine overheating, poor ignition performance, compression loss, or burned threads. The Subaru ignition manual explicitly notes loose plugs as a cause of overheating-related plug damage.
                
                #### 2. Ignition Coil Torque
                *   **Pro Street Target Spec:** **11.8 ft-lb (16 N·m)**.
                *   **Operational Risks:** The STI uses a direct ignition coil-on-plug system. Improper installation torque can create poor coil seating, weak spark delivery, electrical vibration issues, and misfires under boost. 
                *   *Pro Tip:* Many Subaru owners chase fueling issues for weeks only to discover the ignition coil wasn't fully seated because someone tightened it using "vibes" instead of a torque wrench!
                
                #### 3. Valve Cover Bolts
                *   **Pro Street Target Spec:** **3.3 to 4.7 ft-lb**.
                *   **The Pickle Jar Pitfall:** Valve cover leaks are extremely common on EJ engines. Because these bolts thread into soft aluminum, over-tightening can easily warp the valve covers, damage the gaskets, or strip the threads completely. 
                *   *Pro Tip:* When people see an oil leak, they instinctively tighten the bolts harder like they're trying to close a pickle jar—this is a guaranteed way to strip your engine head! Always use an **inch-pound torque wrench** for these low values.
                
                #### 4. Wheel Lug Nuts
                *   **Pro Street Target Spec:** **88.5 ft-lb**.
                *   **Operational Risks:** Improper wheel torque can warp brake rotors, cause uneven wheel clamping, damage studs, or lead to dangerous wheel vibrations.
                *   *Warning:* Impact guns set to "earthquake mode" are not scientific measuring or precision tools! Always do your final pass with a calibrated torque wrench.
                
                #### 5. Intake Manifold Bolts
                *   **Pro Street Target Spec:** **18 ft-lb**.
                *   **Operational Risks:** Improper or uneven torque on the intake manifold can cause vacuum leaks, boost leaks, uneven airflow, rough idling, or lean AFR (air-fuel ratio) conditions.
                *   *Note:* On turbocharged Subarus, even a tiny vacuum leak can create massive drivability problems that make it feel like your ECU suddenly developed major trust issues!
                
                #### 6. Turbocharger Torque Considerations
                *   **Extreme Heat Cycles:** Turbo hardware experiences intense thermal changes. This affects up-pipe fasteners, downpipe hardware, exhaust manifold bolts, and turbo oil feed banjo bolts.
                *   **Failure Modes:** Under-torquing leads to exhaust leaks and boost leaks. Over-torquing leads to broken studs and oil starvation.
                *   *Note:* Always use proper high-temperature anti-seize and perform heat-cycle inspections. This is critical because turbo studs on an older STI can easily develop the structural integrity of stale breadsticks!
                """
            )

        # Section 4: Cylinder Head sequence
        with st.expander("⎔ DOHC EJ257 Cylinder Head Bolt Tightening Sequence"):
            head_col, head_svg_col = st.columns([1.2, 1])
            with head_col:
                st.markdown(
                    '''
                    ### ⎔ 10-Step Cylinder Head Elastic-Plastic Tightening Procedure
                    Always use brand new, clean, and dry OEM **Torque-To-Yield (TTY)** head bolts lightly lubricated with engine oil on the threads and flange faces prior to insertion. Tighten strictly in the designated cross-pattern sequence (center outward) as illustrated:
                    
                    1.  **Stage 1:** Torque all bolts in sequence to **40 N-m (29.5 ft-lbs)**.
                    2.  **Stage 2:** Torque all bolts in sequence to **95 N-m (70 ft-lbs)**.
                    3.  **Stage 3:** Loosen all bolts by **180°** in reverse sequence.
                    4.  **Stage 4:** Loosen all bolts an additional **180°** to release pre-tension completely.
                    5.  **Stage 5:** Torque all bolts in sequence to **10 N-m (7.4 ft-lbs)**.
                    6.  **Stage 6:** Torque all bolts in sequence to **30 N-m (22 ft-lbs)**.
                    7.  **Stage 7:** Torque all bolts in sequence to **70 N-m (51.6 ft-lbs)**.
                    8.  **Stage 8:** Rotate all bolts **80° to 90°** in sequence.
                    9.  **Stage 9:** Rotate all bolts an additional **40° to 45°** in sequence.
                    10. **Stage 10:** Rotate center bolts (1 and 2 only) a final **40° to 45°**.
                    
                    <div class="warning-card">
                        ▲ <b>TTY Fastener Warning:</b> Never reuse stretched Torque-To-Yield (TTY) head bolts. Reusing old bolts compromises clamping force, leading to immediate head gasket failure!
                    </div>
                    ''',
                    unsafe_allow_html=True
                )
            with head_svg_col:
                st.write("")
                st.markdown('''
<svg viewBox="0 0 450 220" width="100%" height="100" style="max-width: 420px; display:block; margin:auto; background-color: var(--secondary-background-color); border-radius: 8px; border: 1px solid rgba(128, 128, 128, 0.2); padding: 12px;">
  <!-- Cylinder block outline -->
  <rect x="15" y="35" width="420" height="150" rx="8" fill="rgba(128, 128, 128, 0.05)" stroke="#FF007F" stroke-width="2"/>
  <text x="225" y="24" fill="#FF007F" font-family="'Montserrat', sans-serif" font-size="12" font-weight="bold" text-anchor="middle">DOHC EJ257 HEAD BOLT LAYOUT & SEQUENCE</text>
  
  <!-- Bolts as circles with sequence numbers inside -->
  <!-- Bolt 1 (Center top) -->
  <circle cx="225" cy="75" r="20" fill="#FF007F" stroke="#ffffff" stroke-width="2"/>
  <text x="225" y="81" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="16" font-weight="bold" text-anchor="middle">1</text>
  <text x="225" y="47" fill="#94a3b8" font-size="9" text-anchor="middle">Center Top</text>

  <!-- Bolt 2 (Center bottom) -->
  <circle cx="225" cy="145" r="20" fill="#FF007F" stroke="#ffffff" stroke-width="2"/>
  <text x="225" y="151" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="16" font-weight="bold" text-anchor="middle">2</text>
  <text x="225" y="181" fill="#94a3b8" font-size="9" text-anchor="middle">Center Btm</text>

  <!-- Bolt 3 (Left top) -->
  <circle cx="115" cy="75" r="20" fill="#94a3b8" stroke="#ffffff" stroke-width="2"/>
  <text x="115" y="81" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="16" font-weight="bold" text-anchor="middle">3</text>
  <text x="115" y="47" fill="#94a3b8" font-size="9" text-anchor="middle">Left Top</text>

  <!-- Bolt 4 (Right bottom) -->
  <circle cx="335" cy="145" r="20" fill="#94a3b8" stroke="#ffffff" stroke-width="2"/>
  <text x="335" y="151" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="16" font-weight="bold" text-anchor="middle">4</text>
  <text x="335" y="181" fill="#94a3b8" font-size="9" text-anchor="middle">Right Btm</text>

  <!-- Bolt 5 (Left bottom) -->
  <circle cx="115" cy="145" r="20" fill="#475569" stroke="#ffffff" stroke-width="2"/>
  <text x="115" y="151" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="16" font-weight="bold" text-anchor="middle">5</text>
  <text x="115" y="181" fill="#94a3b8" font-size="9" text-anchor="middle">Left Btm</text>

  <!-- Bolt 6 (Right top) -->
  <circle cx="335" cy="75" r="20" fill="#475569" stroke="#ffffff" stroke-width="2"/>
  <text x="335" y="81" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="16" font-weight="bold" text-anchor="middle">6</text>
  <text x="335" y="181" fill="#94a3b8" font-size="9" text-anchor="middle">Right Top</text>

  <!-- Center out arrows -->
  <path d="M 225,100 L 225,120" stroke="#ffffff" stroke-width="2" fill="none" marker-end="url(#sm-arrow)"/>
  <path d="M 200,75 L 140,75" stroke="#ffffff" stroke-width="2" fill="none" marker-end="url(#sm-arrow)"/>
  <path d="M 250,145 L 310,145" stroke="#ffffff" stroke-width="2" fill="none" marker-end="url(#sm-arrow)"/>

  <defs>
    <marker id="sm-arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
      <path d="M 0,1 L 10,5 L 0,9 z" fill="#ffffff"/>
    </marker>
  </defs>
</svg>''', unsafe_allow_html=True)
                st.markdown(
                    '''
                    <div style='text-align:center; padding:10px; font-size:0.9em; color:#94a3b8;'>
                        <i>Diagram: Center-out spiral tightening pattern balances thermal expansion and structural gasket load.</i>
                    </div>
                    ''',
                    unsafe_allow_html=True
                )

        # Section 5: Critical Vulnerabilities & Engineering Solutions
        with st.expander("⚙ Diagnostics of Critical Vulnerabilities & Field Engineering Solutions"):
            st.markdown(
                """
                ### ⚙ EJ257 Engineering Vulnerabilities & Proven Fixes
                
                #### 1. Cylinder 4 Overheating, Detonation, and Ringland Failure
                *   **The Cause:** The coolant jacket flow routes sequentially but reaches a stagnation zone around Cylinder 4 (rear left). Localized coolant flow drops, causing a thermal spike that lowers Cylinder 4's knock threshold. Under high load, recurring detonation cracks the brittle cast-aluminum factory piston ringlands, causing compression loss, severe blow-by, and cylinder scoring.
                *   **The Fix:** Retrofit a **Cylinder 4 Chamber Cooling System**. This integrates a coolant return hose at the rear coolant port of the Cylinder 4 head, routing hot coolant directly into the heater core return line to balance temperature gradients across all heads.
                
                #### 2. Crankcase Blow-by and Intake Octane Degradation
                *   **The Cause:** Horizontally opposed flat layout under boost creates excessive crankcase blow-by. Suspended oil mist enters the intake through the PCV system, coating the compressor, intercooler, and runners. This lower-flashpoint oil vapor degrades the fuel's effective octane rating, triggering knocking.
                *   **The Fix:** Install a high-performance, heated dual-chamber **Air-Oil Separator (AOS)**. An AOS intercepts PCV gases, separates oil, and drains it back to the pan. Routing engine coolant through the AOS base prevents moisture condensation and sludge buildup.
                
                #### 3. Firewall Pitch Stop Bracket Structural Weld Failure
                *   **The Cause:** Rotational torque reaction forces are stabilized by a pitch stop mount connecting the transmission to the firewall. In 2015-2016 models, the bracket was stamped from thin sheet-metal and secured with weak spot welds. Installing a stiff aftermarket mount fatigues and tears the bracket completely off the firewall.
                *   **The Fix:** Install a heavy-duty **pitch stop bracket brace** which anchors to the strut towers and master cylinder mounting points. If spot welds are already torn, the firewall must be prepped, realigned, and reinforced with TIG welds before brace installation.
                
                #### 4. Starlink Data Communications Module (DCM) Parasitic Battery Drain
                *   **The Cause:** Decommissioned 3G networks cause the 2016 WRX STI's telematics system to enter an infinite boot-loop searching for signal. Operating on a constant 12V non-switched power source, this causes a **120-140 mA parasitic draw** (exceeding the standard 70 mA limit), draining batteries within 24-48 hours.
                *   **The Fix:** Install a **wireless bypass harness** to route audio around the DCM, or program the DCM into "Factory Mode" using a dealer scan tool per **TSB 15-312-23R** to permanently disable the cellular transceiver.
                
                #### 5. Clutch Pedal Creaking Mechanical Noise
                *   **The Cause:** Creaking sounds during pedal depression are typically pivot wear within the clutch bracket, or a dry clutch fork pivot ball rubbing under friction.
                *   **The Fix:** Remove the intercooler, peel back the slave cylinder rubber boot, and apply high-temperature white lithium grease directly to the release fork and pivot ball socket. If noise persists, replace with an updated pedal bracket assembly per **TSB 12-190-15 and TSB 03-79-18R**.
                """
            )

        
        # Section 7: Piston Ring Gap Alignment (Reworked and Illustrated)
        with st.expander("⌾ EJ257 High-Performance Piston Ring End Gap Alignment"):
            pist_col, pist_svg_col = st.columns([1.2, 1])
            with pist_col:
                st.markdown(
                    '''
                    ### ⌾ Cylinder Wall Piston Ring End Gap Orientations
                    When assembling or rebuilding an EJ257 high-performance engine block, spacing out your ring end gaps at specific offsets is mandatory to prevent exhaust blow-by, excessive oil consumption, and localized hot spots:
                    
                    *   **Gap A (Top Compression Ring):** Positioned at **45°** to the top-right relative to the wrist-pin axis, pointing toward the right-front of the cylinder deck.
                    *   **Gap B (Second Compression Ring):** Aligned exactly **180° away** from Gap A, pointing toward the left-rear of the block.
                    *   **Gap C (Upper Oil Scraper Side Rail):** Positioned at **45°** to the top-left, pointing toward the left-front of the cylinder wall.
                    *   **Gap G (Lower Oil Scraper Side Rail):** Spaced out at **120°** relative to Gap C (pointing to bottom-right, e.g. at **45°** to the bottom-right).
                    *   **Gap F (Oil Control Spacer Expander):** Positioned directly on the lower wrist-pin vertical axis, offset from all scraper rails.
                    
                    <div class="custom-card">
                        ⚙ <b>Assembly Advice:</b> Confirm all top and second compression rings turn freely in the piston grooves prior to block insertion. Use a professional ring compressor to prevent micro-fracturing the delicate rings.
                    </div>
                    ''',
                    unsafe_allow_html=True
                )
            with pist_svg_col:
                st.write("")
                st.markdown('''
<svg viewBox="0 0 400 400" width="100%" height="100" style="max-width: 320px; display:block; margin:auto; background-color: var(--secondary-background-color); border-radius: 8px; border: 1px solid rgba(128, 128, 128, 0.2); padding: 12px;">
  <!-- Cylinder Bore -->
  <circle cx="200" cy="200" r="165" fill="none" stroke="rgba(128, 128, 128, 0.3)" stroke-width="4"/>
  <circle cx="200" cy="200" r="150" fill="rgba(128, 128, 128, 0.05)" stroke="rgba(128, 128, 128, 0.2)" stroke-width="2"/>
  
  <!-- Wrist Pin Axis -->
  <rect x="175" y="100" width="50" height="200" rx="6" fill="rgba(128, 128, 128, 0.1)" stroke="rgba(128, 128, 128, 0.3)" stroke-width="1.5" opacity="0.3"/>
  <circle cx="200" cy="200" r="8" fill="#94a3b8"/>
  <line x1="200" y1="50" x2="200" y2="350" stroke="rgba(128, 128, 128, 0.2)" stroke-width="1" stroke-dasharray="4,4"/>
  <line x1="50" y1="200" x2="350" y2="200" stroke="rgba(128, 128, 128, 0.2)" stroke-width="1" stroke-dasharray="4,4"/>

  <!-- Front of Engine Arrow -->
  <path d="M 200,90 L 200,45" stroke="#FF007F" stroke-width="3" fill="none" marker-end="url(#front-arrow)"/>
  <text x="200" y="32" fill="#FF007F" font-family="'Montserrat', sans-serif" font-size="10" font-weight="bold" text-anchor="middle">FRONT OF ENGINE (→)</text>

  <!-- Gap A: Top Compression Ring -->
  <line x1="200" y1="200" x2="306" y2="94" stroke="#FF007F" stroke-width="2" stroke-dasharray="3,3"/>
  <circle cx="306" cy="94" r="11" fill="#FF007F"/>
  <text x="306" y="100" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="11" font-weight="bold" text-anchor="middle">A</text>
  <text x="322" y="88" fill="#FF007F" font-size="11" font-weight="bold">Top Ring</text>

  <!-- Gap B: Second Compression Ring -->
  <line x1="200" y1="200" x2="94" y2="306" stroke="#94a3b8" stroke-width="2" stroke-dasharray="3,3"/>
  <circle cx="94" cy="306" r="11" fill="#94a3b8"/>
  <text x="94" y="312" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="11" font-weight="bold" text-anchor="middle">B</text>
  <text x="45" y="325" fill="#94a3b8" font-size="11" font-weight="bold">Second Ring</text>

  <!-- Gap C: Upper Side Rail -->
  <line x1="200" y1="200" x2="94" y2="94" stroke="#48bb78" stroke-width="2" stroke-dasharray="3,3"/>
  <circle cx="94" cy="94" r="10" fill="#48bb78"/>
  <text x="94" y="99" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="10" font-weight="bold" text-anchor="middle">C</text>
  <text x="45" y="80" fill="#48bb78" font-size="11" font-weight="bold">Upper Rail</text>

  <!-- Gap G: Lower Side Rail -->
  <line x1="200" y1="200" x2="306" y2="306" stroke="#3182ce" stroke-width="2" stroke-dasharray="3,3"/>
  <circle cx="306" cy="306" r="10" fill="#3182ce"/>
  <text x="306" y="311" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="10" font-weight="bold" text-anchor="middle">G</text>
  <text x="320" y="325" fill="#3182ce" font-size="11" font-weight="bold">Lower Rail</text>

  <!-- Gap F: Spacer Expander -->
  <line x1="200" y1="200" x2="200" y2="340" stroke="#94a3b8" stroke-width="2" stroke-dasharray="3,3"/>
  <circle cx="200" cy="340" r="10" fill="#94a3b8"/>
  <text x="200" y="345" fill="#ffffff" font-family="'Montserrat', sans-serif" font-size="10" font-weight="bold" text-anchor="middle">F</text>
  <text x="200" y="365" fill="#94a3b8" font-size="9" text-anchor="middle">Spacer Expander</text>

  <defs>
    <marker id="front-arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
      <path d="M 0,1 L 10,5 L 0,9 z" fill="#FF007F"/>
    </marker>
  </defs>
</svg>''', unsafe_allow_html=True)
                st.markdown(
                    '''
                    <div style='text-align:center; padding:10px; font-size:0.9em; color:#94a3b8;'>
                        <i>Diagram: Radial distribution of piston ring end gaps prevents any gas paths from aligning.</i>
                    </div>
                    ''',
                    unsafe_allow_html=True
                )

        # Section 6: Engine Class Action Settlement & Recalls
        with st.expander("☰ Regulatory Safety Recalls & The EJ257 Catastrophic Engine Settlement"):
            st.markdown(
                """
                ### ☰ EJ257 Settlement & Official Safety Recalls
                
                #### 1. The EJ257 Engine Failure Class Action Settlement (2018)
                *   **Target Scope:** 2012–2017 Subaru WRX and WRX STI equipped with the 2.5-liter turbocharged EJ257 engine built between Oct. 11, 2011, and Nov. 16, 2016.
                *   **Target VIN Ranges:** 5-door hatch models ending in **CG203168 and up**; 4-door sedan models ending in **CG006225 through H9826807**.
                *   **The Issue:** The lawsuit alleged internal defects allowed metallic debris from deteriorating bearings and oil pump failures to contaminate engine oil, restricting flow through crankshaft passages and causing bearing seizure, piston ringland fractures, and catastrophic engine failure.
                *   **Provisions:**
                    *   **Warranty Extension:** Powertrain warranty extended to **8 years or 100,000 miles**.
                    *   **Reimbursement:** 100% reimbursement for out-of-pocket parts/labor expenses for engine failures.
                    *   **CPO Warranty Program:** For secondary buyers, Certified Pre-Owned vehicles must pass a 152-point inspection to receive a 6-year/100,000-mile powertrain warranty with a **$35 USD deductible**.
                
                #### 2. Key Safety Recalls & Technical Service Bulletins
                *   **NHTSA Campaign 19V149000 (Recall WUE-90 - Brake Light Switch):** Silicone contaminants from cleaning products penetrate the brake light switch housing, preventing brake lights from illuminating and disabling push-button start. Dealers replace with a sealed unit.
                *   **NHTSA Campaign 16V162000 (Recall WTA-62 - Turbo Air Intake Duct):** 2015–2016 WRX and Forester 2.0XT plastic turbo air ducts can crack under thermal cycles and high engine movement, causing unmetered air leaks and lean stalling conditions. Dealers replace with a reinforced compound duct.
                *   **Recall WUT-05 (zinc-coated coils):** Zinc-coated springs replacement for vehicles in road-salt states to prevent coil spring corrosion and fracture.
                """
            )

# --- CLI BACKFALL RUNTIME ---
elif HAS_RICH:
    # Minimal console interface
    console = Console()
    console.print(Panel(Text("Subaru WRX STI Maintenance CLI Interface", style="bold gold1"), subtitle="Local Offline Tracker"))
    # Enter mileage
    try:
        mileage_cli = IntPrompt.ask("Enter Current Odometer Mileage (mi)")
        severe_cli = Confirm.ask("Are you operating in Severe Driving Conditions?")
        
        scheduler_cli = MaintenanceScheduler(mileage_cli, severe_cli)
        items_cli = scheduler_cli.get_schedule()
        
        due_items = [i for i in items_cli if i["due"]]
        
        table = Table(title="Maintenance Item Check-Ledger")
        table.add_column("Maintenance Item", style="cyan")
        table.add_column("Interval", style="magenta")
        table.add_column("Current Status", style="green")
        
        for item in items_cli:
            status = "[bold red]Overdue / Due Now[/]" if item["due"] else "[bold green]Completed & OK[/]"
            table.add_row(item["name"], f"every {item['interval']:,} mi", status)
        
        console.print(table)
    except KeyboardInterrupt:
        console.print("\nExiting tracker. Happy driving!")

else:
    if __name__ == "__main__":
        print("Subaru STI Maintenance App (Minimal fallback)")
        print("Please install streamlit ('pip install streamlit') or rich ('pip install rich') to run.")
