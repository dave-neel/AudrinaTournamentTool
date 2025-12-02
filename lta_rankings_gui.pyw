import math
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from io import StringIO

import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# -----------------------------
# TABLE EXTRACTION USING read_html
# -----------------------------

def extract_ranking_table(html: str) -> pd.DataFrame | None:
    """Extract the LTA ranking table as a clean DataFrame."""
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        return None

    for df in tables:
        cols = [str(c).strip() for c in df.columns]
        df.columns = cols

        if "Rank" not in cols or "Player" not in cols:
            continue

        rank_str = df["Rank"].astype(str)
        is_bad = rank_str.str.contains("page|results", case=False, na=False)
        df = df[~is_bad]

        player_str = df["Player"].astype(str).str.strip()
        df = df[player_str.ne("") & player_str.ne("Player")]

        df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]

        rename_map = {
            "Singles points": "Singles Points",
            "Doubles points": "Doubles Points",
        }
        df.rename(columns=rename_map, inplace=True)

        return df

    return None


def extract_online_entries_table(html: str) -> pd.DataFrame | None:
    """
    Extract the 'Online entries' table from a tournament event page.

    - Must have 'Name' column.
    - Must have a 'Date...' column (e.g. 'Date of entry').
    - We return a single clean column: Name.
    - We drop withdrawn players if a 'Status' column exists.
    """
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        return None

    for df in tables:
        cols = [str(c).strip() for c in df.columns]
        df.columns = cols

        if "Name" not in cols:
            continue
        if not any("date" in c.lower() for c in cols):
            continue

        # If there's a Status column, exclude Withdrawn
        if "Status" in df.columns:
            status_str = df["Status"].astype(str).str.lower()
            df = df[~status_str.str.contains("withdrawn", na=False)]

        # ✅ Clean up Name column robustly
        # 1) Drop real NaN values first
        df = df.dropna(subset=["Name"])

        # 2) Convert to string and strip spaces
        df["Name"] = df["Name"].astype(str).str.strip()

        # 3) Remove blanks, header row, and "nan"/"none" artefacts
        invalid_names = {"", "name", "nan", "none"}
        mask_valid = ~df["Name"].str.lower().isin(invalid_names)
        df = df[mask_valid]

        if df.empty:
            continue

        return df[["Name"]]

    return None


# -----------------------------
# SCRAPERS
# -----------------------------

def create_driver():
    options = webdriver.ChromeOptions()
    # Uncomment to hide browser window:
    # options.add_argument("--headless=new")
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options,
    )
    return driver


def scrape_rankings(url, max_players, results_per_page, output_csv, log_fn, done_fn):
    log_fn(f"Fetching up to {max_players} players from rankings URL:\n{url}\n")

    driver = create_driver()
    all_tables = []
    pages_needed = math.ceil(max_players / results_per_page)

    try:
        for page in range(1, pages_needed + 1):
            page_url = url if page == 1 else f"{url}&p={page}&ps={results_per_page}"
            log_fn(f"\n→ Opening rankings page {page}: {page_url}")
            driver.get(page_url)

            if page == 1:
                messagebox.showinfo(
                    "LTA login",
                    "Chrome has opened the LTA rankings page.\n\n"
                    "If needed, log in to your LTA account and accept cookies.\n"
                    "Make sure the rankings table is visible,\n"
                    "then click OK here to continue.",
                )

            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.TAG_NAME, "table"))
                )
            except Exception:
                log_fn("  WARNING: No table detected on this page.")
                continue

            time.sleep(2)

            html = driver.page_source
            df_page = extract_ranking_table(html)

            if df_page is not None and not df_page.empty:
                log_fn(f"  Found {len(df_page)} ranking rows on this page.")
                all_tables.append(df_page)
            else:
                log_fn("  WARNING: No ranking rows found on this page.")

            total_rows = sum(len(t) for t in all_tables)
            if total_rows >= max_players:
                break
    finally:
        driver.quit()

    if not all_tables:
        log_fn("\nERROR: No data scraped for rankings.")
        done_fn(False, None)
        return

    combined = pd.concat(all_tables, ignore_index=True)
    combined = combined.iloc[:max_players]

    if "Rank.1" in combined.columns:
        combined.drop(columns=["Rank.1"], inplace=True)

    combined.to_csv(output_csv, index=False, encoding="utf-8-sig")
    log_fn(f"\nDone! Saved {len(combined)} ranking rows to:\n{output_csv}")
    done_fn(True, output_csv)


def scrape_tournament_players(url, output_csv, log_fn, done_fn):
    log_fn(f"Fetching tournament ONLINE ENTRIES from:\n{url}\n")

    driver = create_driver()

    try:
        log_fn(f"→ Opening tournament page: {url}")
        driver.get(url)

        messagebox.showinfo(
            "LTA login",
            "Chrome has opened the LTA tournament event page.\n\n"
            "If needed, log in to your LTA account and accept cookies.\n"
            "Make sure the ONLINE ENTRIES table is visible,\n"
            "then click OK here to continue.",
        )

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "table"))
            )
        except Exception:
            log_fn("  WARNING: No table detected on this page.")
            done_fn(False, None)
            return

        time.sleep(2)

        html = driver.page_source
        df_online = extract_online_entries_table(html)

        if df_online is None or df_online.empty:
            log_fn("ERROR: Could not find an 'Online entries' table with Name + Date.")
            done_fn(False, None)
            return

        # ✅ Final clean – drop NaNs BEFORE casting to string
        df_online = df_online.dropna(subset=["Name"])
        df_online["Name"] = df_online["Name"].astype(str).str.strip()

        # Remove blanks and "nan"/"none" artefacts just in case
        invalid_names = {"", "nan", "none"}
        df_online = df_online[~df_online["Name"].str.lower().isin(invalid_names)]

        df_online.to_csv(output_csv, index=False, encoding="utf-8-sig")

        log_fn(f"\nDone! Saved {len(df_online)} tournament players to:\n{output_csv}")
        done_fn(True, output_csv)

    finally:
        driver.quit()


# -----------------------------
# TKINTER GUI (no overlap)
# -----------------------------

def main_gui():
    root = tk.Tk()
    root.title("LTA Rankings & Tournament Downloader")
    root.minsize(900, 600)

    mainframe = ttk.Frame(root, padding=10)
    mainframe.grid(row=0, column=0, sticky="nsew")

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    # Rankings URL
    ttk.Label(mainframe, text="Rankings URL:").grid(row=0, column=0, sticky="w")
    rankings_url_var = tk.StringVar(
        value="https://competitions.lta.org.uk/ranking/category.aspx?id=49130&category=4545"
    )
    ttk.Entry(mainframe, textvariable=rankings_url_var, width=90).grid(
        row=1, column=0, columnspan=3, sticky="we", pady=(0, 8)
    )

    # Max players + rankings button
    ttk.Label(mainframe, text="Max players to fetch (rankings):").grid(
        row=2, column=0, sticky="w"
    )
    max_players_var = tk.StringVar(value="1000")
    ttk.Entry(mainframe, textvariable=max_players_var, width=10).grid(
        row=2, column=1, sticky="w"
    )

    # Tournament URL
    ttk.Label(mainframe, text="Tournament ONLINE ENTRIES URL:").grid(
        row=3, column=0, sticky="w", pady=(10, 0)
    )
    tournament_url_var = tk.StringVar(
        value="https://competitions.lta.org.uk/sport/event.aspx?id=8EC7F377-F52D-4342-A845-E29703AFB4BD&event=2"
    )
    ttk.Entry(mainframe, textvariable=tournament_url_var, width=90).grid(
        row=4, column=0, columnspan=3, sticky="we", pady=(0, 8)
    )

    # Output folder
    ttk.Label(mainframe, text="Save files to folder:").grid(row=5, column=0, sticky="w")
    output_folder_var = tk.StringVar(value=os.getcwd())

    def choose_output_folder():
        folder = filedialog.askdirectory()
        if folder:
            output_folder_var.set(folder)

    ttk.Entry(mainframe, textvariable=output_folder_var, width=60).grid(
        row=6, column=0, columnspan=2, sticky="we", pady=(0, 5)
    )
    ttk.Button(mainframe, text="Browse…", command=choose_output_folder).grid(
        row=6, column=2, sticky="e"
    )

    # Filenames
    ttk.Label(mainframe, text="Rankings CSV filename:").grid(row=7, column=0, sticky="w")
    rankings_file_var = tk.StringVar(value="rankings_downloaded.csv")
    ttk.Entry(mainframe, textvariable=rankings_file_var, width=40).grid(
        row=7, column=1, columnspan=2, sticky="we", pady=(0, 5)
    )

    ttk.Label(mainframe, text="Tournament players CSV filename:").grid(
        row=8, column=0, sticky="w"
    )
    tournament_file_var = tk.StringVar(value="tournament_players.csv")
    ttk.Entry(mainframe, textvariable=tournament_file_var, width=40).grid(
        row=8, column=1, columnspan=2, sticky="we", pady=(0, 10)
    )

    # Buttons row (no overlap now)
    buttons_frame = ttk.Frame(mainframe)
    buttons_frame.grid(row=9, column=0, columnspan=3, sticky="e", pady=(0, 10))

    # Log + status
    ttk.Label(mainframe, text="Log:").grid(row=10, column=0, sticky="w")
    log_text = tk.Text(mainframe, height=18, width=100, state="disabled")
    log_text.grid(row=11, column=0, columnspan=3, sticky="nsew")

    scrollbar = ttk.Scrollbar(mainframe, orient="vertical", command=log_text.yview)
    scrollbar.grid(row=11, column=3, sticky="ns")
    log_text["yscrollcommand"] = scrollbar.set

    mainframe.rowconfigure(11, weight=1)
    mainframe.columnconfigure(0, weight=1)

    status_var = tk.StringVar(value="Ready.")
    ttk.Label(mainframe, textvariable=status_var).grid(
        row=12, column=0, columnspan=3, sticky="w", pady=(5, 0)
    )

    # Logging helper
    def log(msg):
        log_text.configure(state="normal")
        log_text.insert("end", msg + "\n")
        log_text.see("end")
        log_text.configure(state="disabled")
        root.update_idletasks()

    def scraping_done(success, filename):
        if success:
            status_var.set(f"Finished. Saved to {filename}")
            messagebox.showinfo("Completed", f"Saved to:\n{filename}")
        else:
            status_var.set("Finished with errors. See log.")

    # Button handlers
    def start_rankings():
        try:
            max_players = int(max_players_var.get().strip())
            if max_players <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid input", "Max players must be a positive integer.")
            return

        url = rankings_url_var.get().strip()
        if not url:
            messagebox.showerror("Invalid input", "Please enter a rankings URL.")
            return

        folder = output_folder_var.get().strip()
        if not folder:
            messagebox.showerror("Invalid folder", "Please select a folder.")
            return

        filename = rankings_file_var.get().strip() or "rankings_downloaded.csv"
        if not filename.lower().endswith(".csv"):
            filename += ".csv"

        output_csv = os.path.join(folder, filename)

        log_text.configure(state="normal")
        log_text.delete("1.0", "end")
        log_text.configure(state="disabled")

        status_var.set("Downloading rankings…")
        log("Starting rankings scrape…")

        def worker():
            try:
                scrape_rankings(
                    url=url,
                    max_players=max_players,
                    results_per_page=25,
                    output_csv=output_csv,
                    log_fn=log,
                    done_fn=scraping_done,
                )
            except Exception as e:
                log(f"\nUNEXPECTED ERROR during rankings scrape: {e}")
                scraping_done(False, None)

        threading.Thread(target=worker, daemon=True).start()

    def start_tournament():
        url = tournament_url_var.get().strip()
        if not url:
            messagebox.showerror("Invalid input", "Please enter a tournament URL.")
            return

        folder = output_folder_var.get().strip()
        if not folder:
            messagebox.showerror("Invalid folder", "Please select a folder.")
            return

        filename = tournament_file_var.get().strip() or "tournament_players.csv"
        if not filename.lower().endswith(".csv"):
            filename += ".csv"

        output_csv = os.path.join(folder, filename)

        log_text.configure(state="normal")
        log_text.delete("1.0", "end")
        log_text.configure(state="disabled")

        status_var.set("Downloading tournament players…")
        log("Starting tournament ONLINE ENTRIES scrape…")

        def worker():
            try:
                scrape_tournament_players(
                    url=url,
                    output_csv=output_csv,
                    log_fn=log,
                    done_fn=scraping_done,
                )
            except Exception as e:
                log(f"\nUNEXPECTED ERROR during tournament scrape: {e}")
                scraping_done(False, None)

        threading.Thread(target=worker, daemon=True).start()

    # Buttons placed in buttons_frame so they don't overlap entries
    ttk.Button(buttons_frame, text="Download rankings", command=start_rankings).grid(
        row=0, column=0, padx=(0, 10)
    )
    ttk.Button(buttons_frame, text="Download tournament players", command=start_tournament).grid(
        row=0, column=1
    )

    root.mainloop()


if __name__ == "__main__":
    main_gui()
