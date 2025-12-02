import math
from io import StringIO

import requests
import pandas as pd
import streamlit as st


# -----------------------------
# TABLE EXTRACTION USING read_html
# -----------------------------

def extract_ranking_table(html):
    """Extract the LTA ranking table as a clean DataFrame."""
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        return None

    for df in tables:
        cols = [str(c).strip() for c in df.columns]
        df.columns = cols

        # Must have Rank + Player columns
        if "Rank" not in cols or "Player" not in cols:
            continue

        # Remove pager/summary rows that sneak into the table
        rank_str = df["Rank"].astype(str)
        is_bad = rank_str.str.contains("page|results", case=False, na=False)
        df = df[~is_bad]

        # Remove blank / header-style "Player" rows
        player_str = df["Player"].astype(str).str.strip()
        df = df[player_str.ne("") & player_str.ne("Player")]

        # Drop unnamed junk columns
        df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]

        # Normalise column names
        rename_map = {
            "Singles points": "Singles Points",
            "Doubles points": "Doubles Points",
        }
        df.rename(columns=rename_map, inplace=True)

        return df

    return None


def extract_online_entries_table(html):
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
            # We only want the ONLINE ENTRIES table with a date column
            continue

        # Exclude withdrawn players if a Status column exists
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
# SCRAPERS (requests-based for Streamlit)
# -----------------------------

def fetch_rankings(url, max_players, results_per_page=25):
    """
    Fetch rankings table from LTA rankings pages using plain HTTP requests.

    NOTE: This may fail (HTTP 404) if the LTA site requires login or
    blocks requests from Streamlit Cloud.
    """
    all_tables = []
    pages_needed = math.ceil(max_players / results_per_page)

    for page in range(1, pages_needed + 1):
        if page == 1:
            page_url = url
        else:
            # Same pattern as your Tkinter tool:
            #   &p={page}&ps={results_per_page}
            page_url = f"{url}&p={page}&ps={results_per_page}"

        st.write(f"➡️ Fetching rankings page {page}: `{page_url}`")

        try:
            resp = requests.get(page_url, timeout=20)
        except Exception as e:
            st.warning(f"Page {page}: request error {e}")
            continue

        if resp.status_code != 200:
            st.warning(f"Page {page}: HTTP {resp.status_code}, skipping.")
            continue

        df_page = extract_ranking_table(resp.text)
        if df_page is not None and not df_page.empty:
            st.write(f"✅ Found {len(df_page)} ranking rows on this page.")
            all_tables.append(df_page)
        else:
            st.warning("⚠️ No ranking rows found on this page.")

        total_rows = sum(len(t) for t in all_tables)
        if total_rows >= max_players:
            break

    if not all_tables:
        return pd.DataFrame()

    combined = pd.concat(all_tables, ignore_index=True)
    combined = combined.iloc[:max_players]

    if "Rank.1" in combined.columns:
        combined = combined.drop(columns=["Rank.1"])

    return combined


def fetch_tournament_players(url):
    """
    Fetch tournament ONLINE ENTRIES players using plain HTTP requests.
    """
    st.write("➡️ Fetching tournament ONLINE ENTRIES from:")
    st.code(url, language="text")

    try:
        resp = requests.get(url, timeout=20)
    except Exception as e:
        st.error(f"Request error: {e}")
        return pd.DataFrame()

    if resp.status_code != 200:
        st.error(f"HTTP {resp.status_code} when fetching the page.")
        return pd.DataFrame()

    df_online = extract_online_entries_table(resp.text)

    if df_online is None or df_online.empty:
        st.error("Could not find an 'Online entries' table with Name + Date.")
        return pd.DataFrame()

    # ✅ Final clean just like in the Tkinter version
    df_online = df_online.dropna(subset=["Name"])
    df_online["Name"] = df_online["Name"].astype(str).str.strip()

    invalid_names = {"", "nan", "none"}
    df_online = df_online[~df_online["Name"].str.lower().isin(invalid_names)]

    return df_online.reset_index(drop=True)


def parse_players_from_text(raw: str) -> pd.DataFrame:
    """
    Parse pasted text of 'Player [tab or spaces] Date of entry' into a clean Name list.

    Works for lines like:
    - 'Olivia Adamska\\tTue 11/11/2025 12:30'
    - 'Olivia Adamska   Tue 11/11/2025 12:30'
    """
    if not raw:
        return pd.DataFrame(columns=["Name"])

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    names = []

    for ln in lines:
        lower = ln.lower()
        # Skip header lines
        if "player" in lower and "date" in lower:
            continue

        name = ""

        # Case 1: tab-separated
        if "\t" in ln:
            name = ln.split("\t", 1)[0].strip()
        else:
            # Case 2: space-separated: take words before first token containing a digit
            parts = ln.split()
            name_tokens = []
            for tok in parts:
                if any(ch.isdigit() for ch in tok):
                    break
                name_tokens.append(tok)
            if name_tokens:
                name = " ".join(name_tokens).strip()
            else:
                # Fallback: whole line
                name = ln.strip()

        if not name:
            continue
        if name.lower() in {"players", "name"}:
            continue

        names.append(name)

    df = pd.DataFrame({"Name": names})
    df["Name"] = df["Name"].astype(str).str.strip()
    df = df[df["Name"] != ""]
    df = df.drop_duplicates().reset_index(drop=True)
    return df


# -----------------------------
# STREAMLIT PAGE UI
# -----------------------------

def main():
    st.title("🎾 Rankings & Tournament Entries")

    tab_rankings, tab_tournament, tab_upload, tab_paste = st.tabs(
        [
            "📊 Rankings Downloader",
            "🧾 Tournament ONLINE ENTRIES",
            "📂 Upload & Analyse CSVs",
            "✂️ Paste players from LTA",
        ]
    )

    # -------------------------
    # TAB 1 – RANKINGS
    # -------------------------
    with tab_rankings:
        st.subheader("Download LTA Rankings (may not work from cloud)")

        default_rankings_url = (
            "https://competitions.lta.org.uk/ranking/category.aspx"
            "?id=49130&category=4545"
        )

        rankings_url = st.text_input(
            "Rankings URL",
            value=default_rankings_url,
            help="Paste the full LTA rankings URL.",
        )

        col1, col2 = st.columns(2)
        with col1:
            max_players = st.number_input(
                "Max players to fetch",
                min_value=1,
                max_value=5000,
                value=100,
                step=50,
            )
        with col2:
            results_per_page = st.number_input(
                "Results per page (ps parameter)",
                min_value=1,
                max_value=100,
                value=25,
                step=1,
                help="Usually 25 on the LTA rankings pages.",
            )

        if st.button("Download rankings"):
            if not rankings_url.strip():
                st.error("Please enter a rankings URL.")
            else:
                with st.spinner("Fetching rankings…"):
                    df_rankings = fetch_rankings(
                        url=rankings_url.strip(),
                        max_players=int(max_players),
                        results_per_page=int(results_per_page),
                    )

                if df_rankings.empty:
                    st.error("No rankings data found.")
                    st.info(
                        "This often happens because the LTA rankings page requires login "
                        "or blocks access from Streamlit Cloud.\n\n"
                        "You can still use this tool by uploading rankings CSV files "
                        "in the 'Upload & Analyse CSVs' tab."
                    )
                else:
                    st.success(f"Fetched {len(df_rankings)} ranking rows.")
                    st.dataframe(df_rankings, use_container_width=True)

                    csv_bytes = df_rankings.to_csv(
                        index=False, encoding="utf-8-sig"
                    ).encode("utf-8-sig")
                    st.download_button(
                        label="⬇️ Download rankings CSV",
                        data=csv_bytes,
                        file_name="rankings_downloaded.csv",
                        mime="text/csv",
                    )

    # -------------------------
    # TAB 2 – TOURNAMENT ONLINE ENTRIES
    # -------------------------
    with tab_tournament:
        st.subheader("Download Tournament ONLINE ENTRIES (Players List)")

        default_tournament_url = (
            "https://competitions.lta.org.uk/sport/event.aspx"
            "?id=8EC7F377-F52D-4342-A845-E29703AFB4BD&event=2"
        )

        tournament_url = st.text_input(
            "Tournament ONLINE ENTRIES URL",
            value=default_tournament_url,
            help="Paste the LTA tournament event URL for the ONLINE ENTRIES.",
        )

        if st.button("Download tournament players"):
            if not tournament_url.strip():
                st.error("Please enter a tournament ONLINE ENTRIES URL.")
            else:
                with st.spinner("Fetching tournament players…"):
                    df_players = fetch_tournament_players(tournament_url.strip())

                if df_players.empty:
                    st.error("No players data found.")
                    st.info(
                        "If this page also requires login or is blocked, you can copy & paste "
                        "the players list into the 'Paste players from LTA' tab."
                    )
                else:
                    st.success(f"Fetched {len(df_players)} players from ONLINE ENTRIES.")
                    st.dataframe(df_players, use_container_width=True)

                    csv_bytes = df_players.to_csv(
                        index=False, encoding="utf-8-sig"
                    ).encode("utf-8-sig")
                    st.download_button(
                        label="⬇️ Download tournament players CSV",
                        data=csv_bytes,
                        file_name="tournament_players.csv",
                        mime="text/csv",
                        )

    # -------------------------
    # TAB 3 – UPLOAD & ANALYSE CSVs
    # -------------------------
    with tab_upload:
        st.subheader("Upload Rankings & Tournament Players CSVs")

        st.markdown(
            "Use this when you already have CSV files (from your PC tool, LTA downloads, "
            "or manually built files). You can do all the analysis here on your iPhone."
        )

        col_r, col_t = st.columns(2)

        with col_r:
            rankings_file = st.file_uploader(
                "Upload rankings CSV (must include a 'Player' column)",
                type="csv",
                key="rankings_csv",
            )

        with col_t:
            tournament_file = st.file_uploader(
                "Upload tournament players CSV (must include a 'Name' column)",
                type="csv",
                key="tournament_csv",
            )

        df_rankings = None
        df_tournament = None

        if rankings_file is not None:
            try:
                df_rankings = pd.read_csv(rankings_file)
                st.success(f"Rankings CSV loaded with {len(df_rankings)} rows.")
                st.dataframe(df_rankings.head(20), use_container_width=True)
            except Exception as e:
                st.error(f"Error reading rankings CSV: {e}")

        if tournament_file is not None:
            try:
                df_tournament = pd.read_csv(tournament_file)
                st.success(f"Tournament players CSV loaded with {len(df_tournament)} rows.")
                st.dataframe(df_tournament.head(20), use_container_width=True)
            except Exception as e:
                st.error(f"Error reading tournament CSV: {e}")

        if df_rankings is not None and df_tournament is not None:
            st.markdown("---")
            st.subheader("Matched Tournament Players with Rankings")

            # Try to merge: tournament Name -> rankings Player
            df_tournament["Name_clean"] = df_tournament["Name"].astype(str).str.strip()
            df_rankings["Player_clean"] = df_rankings["Player"].astype(str).str.strip()

            merged = df_tournament.merge(
                df_rankings,
                left_on="Name_clean",
                right_on="Player_clean",
                how="left",
                suffixes=("_tournament", "_rankings"),
            )

            # Show some key columns if they exist
            cols_to_show = []
            for c in ["Name", "Rank", "Singles Points", "Doubles Points", "County", "Age group"]:
                if c in merged.columns:
                    cols_to_show.append(c)

            if not cols_to_show:
                cols_to_show = merged.columns.tolist()

            st.dataframe(merged[cols_to_show], use_container_width=True)

            csv_bytes = merged.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                label="⬇️ Download merged players + rankings CSV",
                data=csv_bytes,
                file_name="tournament_players_with_rankings.csv",
                mime="text/csv",
            )
        elif rankings_file is not None or tournament_file is not None:
            st.info("Upload **both** a rankings CSV and a tournament players CSV to see the match.")

    # -------------------------
    # TAB 4 – PASTE PLAYERS FROM LTA
    # -------------------------
    with tab_paste:
        st.subheader("Paste players list from LTA page")

        st.markdown(
            "1. On your iPhone, open the LTA tournament ONLINE ENTRIES page.\n"
            "2. Select and copy the block of text with players and dates.\n"
            "3. Paste it into the box below.\n"
            "4. I'll extract a clean list of names and let you download it as CSV."
        )

        example_text = (
            "Players                  Date of entry\n"
            "Olivia Adamska\tTue 11/11/2025 12:30\n"
            "Amira Afzal\tSat 08/11/2025 09:25\n"
            "Swasthika Arunkumar\tSun 30/11/2025 09:55\n"
            "Elena Asgill-Whalley\tTue 04/11/2025 15:02\n"
            "Valentina Bailey\tThu 27/11/2025 12:35\n"
            "Ellie Barker\tTue 04/11/2025 22:29\n"
            "Esme Bartlett\tFri 28/11/2025 14:16\n"
            "Esha Batth\tThu 13/11/2025 09:48\n"
        )

        raw_text = st.text_area(
            "Paste the players + date text here",
            value=example_text,
            height=220,
        )

        if st.button("Clean & show player names"):
            df_names = parse_players_from_text(raw_text)

            if df_names.empty:
                st.error("No valid player names found. Check the pasted text format.")
            else:
                st.success(f"Found {len(df_names)} unique player names.")
                st.dataframe(df_names, use_container_width=True)

                csv_bytes = df_names.to_csv(
                    index=False, encoding="utf-8-sig"
                ).encode("utf-8-sig")
                st.download_button(
                    label="⬇️ Download players CSV",
                    data=csv_bytes,
                    file_name="tournament_players_from_paste.csv",
                    mime="text/csv",
                )


if __name__ == "__main__":
    main()
