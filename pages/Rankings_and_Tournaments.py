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
