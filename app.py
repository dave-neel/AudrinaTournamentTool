import streamlit as st
import pandas as pd
import threading
import time
import os

st.title("Tournament vs LTA Rankings matcher")

st.write(
    "Upload your **tournament players CSV** (with a `Name` column) "
    "and your **LTA rankings CSV** (with a `Player` column)."
)

# File upload widgets
players_file = st.file_uploader("Tournament players CSV", type=["csv"])
rankings_file = st.file_uploader("Rankings CSV", type=["csv"])

players = None
rankings = None

if players_file is not None:
    players = pd.read_csv(players_file)
    st.subheader("Preview: tournament players")
    st.write(players.head())

if rankings_file is not None:
    rankings = pd.read_csv(rankings_file)
    st.subheader("Preview: rankings")
    st.write(rankings.head())

if players is not None and rankings is not None:
    st.markdown("---")
    st.subheader("Match and compare")

    # Normalise names
    players["Name_norm"] = players["Name"].str.strip().str.upper()
    rankings["Name_norm"] = rankings["Player"].str.strip().str.upper()

    # Merge (keep all tournament players)
    merged = players.merge(
        rankings,
        on="Name_norm",
        how="left",
        suffixes=("_tournament", "_ranking")
    )

    # Flag whether each tournament player was found in rankings
    merged["Found_in_rankings"] = ~merged["Player"].isna()

    # Make numeric versions for sorting / calculations
    if "Rank" in merged.columns:
        merged["Rank_num"] = pd.to_numeric(merged["Rank"], errors="coerce")

    if "WTN Singles" in merged.columns:
        merged["WTN_num"] = pd.to_numeric(merged["WTN Singles"], errors="coerce")

    # Clean encoding issues in Year of birth (removes Â etc.)
    if "Year of birth" in merged.columns:
        merged["Year of birth"] = (
            merged["Year of birth"]
            .astype(str)
            .str.replace("Â", "", regex=False)
            .str.replace("[^0-9]", "", regex=True)  # remove any non-digits
        )

    # Sort by Rank if available (None at the bottom)
    if "Rank" in merged.columns:
        merged = merged.sort_values("Rank_num", na_position="last")

    cols_to_keep = [
        "Name",
        "Found_in_rankings",
        "Rank",
        "Player",
        "Year of birth",
        "WTN Singles",
        "WTN Doubles",
        "Play County",
        "Singles Points",
        "Doubles Points",
        "Total points",
    ]
    cols_to_keep = [c for c in cols_to_keep if c in merged.columns]

    result = merged[cols_to_keep]

    st.write("### Result (all tournament players)")
    st.write(result)

    # --- Show players NOT found in rankings separately ---
    not_found = merged[merged["Found_in_rankings"] == False][["Name"]].sort_values("Name")

    if len(not_found) > 0:
        st.markdown("---")
        st.write("### Players NOT found in rankings.csv")
        st.write(not_found)
    else:
        st.write("All tournament players were found in rankings.csv ✅")

    # ------------------------------
    #  CHECK POSITION FOR A PLAYER
    # ------------------------------
    st.markdown("---")
    st.subheader("Check position of a player in this tournament")

    col1, col2 = st.columns(2)
    with col1:
        first_name = st.text_input("First name", "")
    with col2:
        surname = st.text_input("Surname", "")

    col3, col4 = st.columns(2)
    with col3:
        wtn_input = st.text_input("Player's WTN Singles (optional)", "")
    with col4:
        rank_input = st.text_input("Player's LTA Combined Ranking (optional)", "")

    if st.button("Calculate position"):
        full_name = (first_name + " " + surname).strip()
        st.write(f"**Player:** {full_name or '(no name entered)'}")

        # --- By WTN ---
        if wtn_input.strip() != "" and "WTN_num" in merged.columns:
            try:
                player_wtn = float(wtn_input)
                valid_wtn = merged[merged["WTN_num"].notna()].copy()
                # lower WTN is stronger
                valid_wtn = valid_wtn.sort_values("WTN_num", ascending=True)

                num_stronger = (valid_wtn["WTN_num"] < player_wtn).sum()
                position_wtn = int(num_stronger) + 1
                total_with_wtn = len(valid_wtn)

                st.write(
                    f"- **WTN basis**: position **{position_wtn}** out of {total_with_wtn} players "
                    f"with a WTN Singles value."
                )
                st.write(
                    f"  → {num_stronger} players have a **better (lower)** WTN; "
                    f"{total_with_wtn - position_wtn} have a **worse (higher)** WTN."
                )
            except ValueError:
                st.error("WTN entered is not a valid number.")

        elif wtn_input.strip() != "":
            st.warning("No 'WTN Singles' column found in the rankings data.")

        # --- By Ranking ---
        if rank_input.strip() != "" and "Rank_num" in merged.columns:
            try:
                player_rank = int(rank_input)
                valid_rank = merged[merged["Rank_num"].notna()].copy()
                valid_rank = valid_rank.sort_values("Rank_num", ascending=True)

                num_better_rank = (valid_rank["Rank_num"] < player_rank).sum()
                position_rank = int(num_better_rank) + 1
                total_with_rank = len(valid_rank)

                st.write(
                    f"- **Ranking basis**: position **{position_rank}** out of {total_with_rank} players "
                    f"who have a ranking."
                )
                st.write(
                    f"  → {num_better_rank} players are **ranked higher** (better number); "
                    f"{total_with_rank - position_rank} are **ranked lower**."
                )
            except ValueError:
                st.error("Ranking entered is not a valid whole number.")

        elif rank_input.strip() != "":
            st.warning("No 'Rank' column found in the rankings data.")

    # Download button for full result
    csv_data = result.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download full result as CSV",
        data=csv_data,
        file_name="tournament_with_rankings.csv",
        mime="text/csv",
    )

# ------------------------------
#  FINISH & CLOSE APP BUTTON
# ------------------------------
st.markdown("---")
st.subheader("Finished using the app?")

def shutdown_later():
    # small delay so the message can render
    time.sleep(1)
    os._exit(0)

if st.button("Finished – close app"):
    st.success("App is shutting down. You can now close this browser tab.")
    # run shutdown in a background thread so the message appears first
    threading.Thread(target=shutdown_later).start()
