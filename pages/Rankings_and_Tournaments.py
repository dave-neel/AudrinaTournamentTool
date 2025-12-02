import pandas as pd
import streamlit as st
from io import StringIO


# -----------------------------
# PASTE PARSER
# -----------------------------

def parse_players_from_text(raw: str) -> pd.DataFrame:
    """
    Parse pasted text of 'Player [tab or spaces] Date of entry' into a clean Name list.
    Works for lines like:
    - 'Audrina Neeladoo\\tTue 11/11/2025 12:30'
    - 'Audrina Neeladoo   Tue 11/11/2025 12:30'
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
    st.title("🎾 Tournament Player Tools")

    # Only the 2 working tabs now
    tab_upload, tab_paste = st.tabs(
        [
            "📂 Upload & Analyse CSVs",
            "✂️ Paste players from LTA",
        ]
    )

    # -------------------------
    # TAB 1 – UPLOAD & ANALYSE CSVs
    # -------------------------
    with tab_upload:
        st.subheader("Upload Rankings & Tournament Players CSVs")

        st.markdown(
            "Upload CSV files you already have (from PC tool or elsewhere)."
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

            df_tournament["Name_clean"] = df_tournament["Name"].astype(str).str.strip()
            df_rankings["Player_clean"] = df_rankings["Player"].astype(str).str.strip()

            merged = df_tournament.merge(
                df_rankings,
                left_on="Name_clean",
                right_on="Player_clean",
                how="left",
                suffixes=("_tournament", "_rankings"),
            )

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
            st.info("Upload **both** a rankings CSV and a tournament players CSV to see matches.")

    # -------------------------
    # TAB 2 – PASTE PLAYERS FROM LTA
    # -------------------------
    with tab_paste:
        st.subheader("Paste players list from LTA page")

        st.markdown(
            "1. On your iPhone, open the LTA tournament ONLINE ENTRIES page.\n"
            "2. Select and copy the players + date block.\n"
            "3. Paste it into the box below.\n"
            "4. This tool extracts **just the clean list of names**.\n"
        )

        example_text = (
            "Players                  Date of entry\n"
            "Audrina Neeladoo\tTue 11/11/2025 12:30\n"
            "Audrina Neeladoo\tSat 08/11/2025 09:25\n"
            "Audrina Neeladoo\tSun 30/11/2025 09:55\n"
            "Audrina Neeladoo\tTue 04/11/2025 15:02\n"
            "Audrina Neeladoo\tThu 27/11/2025 12:35\n"
            "Audrina Neeladoo\tTue 04/11/2025 22:29\n"
            "Audrina Neeladoo\tFri 28/11/2025 14:16\n"
            "Audrina Neeladoo\tThu 13/11/2025 09:48\n"
        )

        raw_text = st.text_area(
            "Paste the players + date text here",
            value=example_text,
            height=220,
        )

        # 🔹 New: Let you choose the file name (without .csv)
        default_name = "tournament_players_from_paste"
        file_name_input = st.text_input(
            "File name for CSV (without .csv)",
            value=default_name,
        )

        if st.button("Clean & show player names"):
            df_names = parse_players_from_text(raw_text)

            if df_names.empty:
                st.error("No valid player names found. Check the pasted text.")
            else:
                st.success(f"Found {len(df_names)} unique player names.")
                st.dataframe(df_names, use_container_width=True)

                # Ensure we always end with .csv and have something sensible
                safe_base = file_name_input.strip() or default_name
                if not safe_base.lower().endswith(".csv"):
                    download_name = f"{safe_base}.csv"
                else:
                    download_name = safe_base

                csv_bytes = df_names.to_csv(
                    index=False, encoding="utf-8-sig"
                ).encode("utf-8-sig")
                st.download_button(
                    label="⬇️ Download players CSV",
                    data=csv_bytes,
                    file_name=download_name,
                    mime="text/csv",
                )


if __name__ == "__main__":
    main()
