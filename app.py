import math
from io import StringIO

import requests
import pandas as pd
import streamlit as st


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

def fetch_rankings(url: str, max_players: int, results_per_page: int = 25) -> pd.DataFrame:
    """
    Fetch rankings table from LTA rankings pages using plain HTTP requests.

    This assumes that the rankings are visible without login from the Streamlit environment.
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

        resp = requests.get(page_url)
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


def fetch_tournament_players(url: str) -> pd.DataFrame:
    """
    Fetch tournament ONLINE ENTRIES players using plain HTTP requests.
    """
    st.write(f"➡️ Fetching tournament ONLINE ENTRIES from:")
    st.code(url, language="text")

    resp = requests.get(url)
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


# -----------------------------
# STREAMLIT UI
# -----------------------------

def main():
    st.set_page_config(page_title="Audrina Tournament Tool", layout="wide")

    st.title("🎾 Audrina Tournament & Rankings Tool")

    tab_rankings, tab_tournament = st.tabs(
        ["📊 Rankings Downloader", "🧾 Tournament ONLINE ENTRIES"]
    )

    # -------------------------
    # TAB 1 – RANKINGS
    # -------------------------
    with tab_rankings:
        st.subheader("Download LTA Rankings")

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
                value=1000,
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
                else:
                    st.success(f"Fetched {len(df_rankings)} ranking rows.")
                    st.dataframe(df_rankings, use_container_width=True)

                    csv_bytes = df_rankings.to_csv(index=False, encoding="utf-8-sig").encode(
                        "utf-8-sig"
                    )
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


if __name__ == "__main__":
    main()
