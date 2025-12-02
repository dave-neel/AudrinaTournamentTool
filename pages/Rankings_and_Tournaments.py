import base64
import pandas as pd
import streamlit as st


# -----------------------------
# PASTE PARSER
# -----------------------------

def looks_like_position_label(text: str) -> bool:
    """
    Heuristic: does this look like 'Maindraw 1', 'Qualifying 3', etc.,
    i.e. not a real player name?
    """
    t = text.strip().lower()
    if not t:
        return False

    # If it contains a digit, often it's 'Maindraw 1', 'Q3', etc.
    has_digit = any(ch.isdigit() for ch in t)
    starts_like_pos = (
        t.startswith("maindraw")
        or t.startswith("main draw")
        or t.startswith("qualifying")
        or t.startswith("q ")
        or t.startswith("q-")
    )

    return has_digit or starts_like_pos


def parse_players_from_text(raw: str) -> pd.DataFrame:
    """
    Parse pasted text into a clean Name list.

    Handles formats like:
    - ONLINE ENTRIES:
        'Players        Date of entry'
        'Audrina Tennis\\tTue 11/11/2025 12:30'
    - Draw grids:
        'Player\\tStatus\\tSeed'
        'Maindraw 1\\tCiara Moore\\t'
    """
    if not raw:
        return pd.DataFrame(columns=["Name"])

    # Basic cleaned lines (keep order, drop empty)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return pd.DataFrame(columns=["Name"])

    header_idx = None
    player_col_index = None

    # First pass: try to find a header line that contains 'player'
    for idx, ln in enumerate(lines):
        lower = ln.lower()
        if "player" in lower:  # matches 'Player', 'Players', etc.
            header_idx = idx

            # Decide how to split the header row
            if "\t" in ln:
                cols = [c.strip() for c in ln.split("\t") if c.strip()]
            else:
                cols = [c.strip() for c in ln.split() if c.strip()]

            for col_i, col in enumerate(cols):
                if "player" in col.lower():
                    player_col_index = col_i
                    break

            break  # stop after first header line

    names: list[str] = []

    # Second pass: extract names from data lines
    for idx, ln in enumerate(lines):
        # Skip the header line if we identified it
        if header_idx is not None and idx == header_idx:
            continue

        if not ln:
            continue

        name = ""

        # Mode 1: Structured header found ("Player" column)
        if player_col_index is not None:
            if "\t" in ln:
                raw_parts = ln.split("\t")
            else:
                raw_parts = ln.split()

            parts = [p.strip() for p in raw_parts if p.strip()]

            if len(parts) > player_col_index:
                candidate = parts[player_col_index].strip()

                # SPECIAL CASE:
                # If the "Player" column looks like 'Maindraw 1', 'Q2', etc.,
                # and there is another column after it, treat THAT as the player name.
                if looks_like_position_label(candidate) and len(parts) > player_col_index + 1:
                    candidate = parts[player_col_index + 1].strip()

                name = candidate

        # Mode 2: Fallback – previous heuristic logic
        if not name:
            # Case: tab-separated -> take text before first tab
            if "\t" in ln:
                name = ln.split("\t", 1)[0].strip()
            else:
                # Space-separated: take tokens before the first token containing a digit
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

        # Skip obvious non-name tokens
        if name.lower() in {"players", "player", "name"}:
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
        st.subheader("Paste players list from LTA or draw sheet")

        st.markdown(
            "You can paste **different formats**, as long as there's a header containing "
            "`Player` or `Players` somewhere.\n\n"
            "- Example 1 (ONLINE ENTRIES): `Players    Date of entry`\n"
            "- Example 2 (Draw sheet): `Player    Status    Seed`\n"
        )

        example_text = (
            "Player\tStatus\tSeed\n"
            "Maindraw 1\tAudrina Tennis\t\n"
            "Maindraw 2\tAudrina Ace\t\n"
            "Maindraw 3\tAudrina Serve\t\n"
            "Maindraw 4\tAudrina Forehand\t\n"
            "Maindraw 5\tAudrina Backhand\t\n"
        )

        raw_text = st.text_area(
            "Paste the players block here",
            value=example_text,
            height=220,
        )

        # Let you choose the file name (without .csv)
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

                # Normal Streamlit download button
                csv_text = df_names.to_csv(index=False, encoding="utf-8-sig")
                csv_bytes = csv_text.encode("utf-8-sig")

                st.download_button(
                    label="⬇️ Download players CSV",
                    data=csv_bytes,
                    file_name=download_name,
                    mime="text/csv",
                )

                # Extra: Save-As link for iPhone
                b64 = base64.b64encode(csv_bytes).decode()
                href = f'<a href="data:text/csv;base64,{b64}" download="{download_name}">📥 Download via iPhone “Save As”</a>'

                st.markdown(
                    "If Safari doesn’t ask where to save, use this link instead:",
                )
                st.markdown(href, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
