import streamlit as st
import pandas as pd
import altair as alt

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

    # Numeric versions for sorting / calculations
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
    #  RANKING / WTN VISUALISATIONS
    # ------------------------------
    st.markdown("---")
    st.subheader("Visualise tournament strength")

    # WTN distribution chart
    if "WTN_num" in merged.columns and merged["WTN_num"].notna().any():
        st.write("**WTN Singles distribution (lower is stronger)**")
        wtn_data = merged[merged["WTN_num"].notna()][["Name", "WTN_num"]]

        wtn_hist = (
            alt.Chart(wtn_data)
            .mark_bar()
            .encode(
                x=alt.X("WTN_num:Q", bin=alt.Bin(maxbins=20), title="WTN Singles"),
                y=alt.Y("count():Q", title="Number of players"),
            )
            .properties(height=250)
        )

        st.altair_chart(wtn_hist, use_container_width=True)
    else:
        st.info("No valid WTN Singles data available to plot.")

    # Ranking distribution chart
    if "Rank_num" in merged.columns and merged["Rank_num"].notna().any():
        st.write("**LTA Combined Ranking (smaller number is stronger)**")
        rank_data = merged[merged["Rank_num"].notna()][["Name", "Rank_num"]]

        rank_chart = (
            alt.Chart(rank_data)
            .mark_bar()
            .encode(
                x=alt.X(
                    "Rank_num:Q",
                    bin=alt.Bin(maxbins=25),
                    title="LTA Combined Ranking",
                ),
                y=alt.Y("count():Q", title="Number of players"),
            )
            .properties(height=250)
        )

        st.altair_chart(rank_chart, use_container_width=True)
    else:
        st.info("No valid ranking data available to plot.")

    # ------------------------------
    #  DRAW STRUCTURE + POSITION CHECKER
    # ------------------------------
    st.markdown("---")
    st.subheader("Check position of a player in this tournament")

    # Selection basis
    selection_basis = st.radio(
        "Tournament selection is based on:",
        ["WTN (with ranking as tie-break)", "Ranking only"],
    )

    # Draw structure inputs
    st.markdown("**Draw structure**")
    dc1, dc2, dc3 = st.columns(3)
    with dc1:
        main_draw_size = st.number_input(
            "Main draw size", min_value=1, value=32, step=1
        )
    with dc2:
        qual_draw_size = st.number_input(
            "Qualifying draw size (0 if none)", min_value=0, value=0, step=1
        )
    with dc3:
        qualifiers_to_main = st.number_input(
            "Qualifiers into main draw", min_value=0, value=0, step=1
        )

    dc4, dc5 = st.columns(2)
    with dc4:
        wildcards_main = st.number_input(
            "Wildcards in main draw", min_value=0, value=0, step=1
        )
    with dc5:
        wildcards_qual = st.number_input(
            "Wildcards in qualifying draw", min_value=0, value=0, step=1
        )

    st.caption(
        "Example: 24Q / 32M with 8 qualifiers → main draw size 32, qualifying draw size 24, "
        "qualifiers into main 8."
    )

    # Player inputs
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

    # Helper to classify position vs draw
    def classify_position(position: int | None):
        if position is None:
            return "No valid position calculated."

        # effective spots
        direct_main = max(
            0, int(main_draw_size) - int(wildcards_main) - int(qualifiers_to_main)
        )
        direct_qual = max(0, int(qual_draw_size) - int(wildcards_qual))

        # Clamp if user puts silly numbers
        total_spots = direct_main + direct_qual

        if total_spots == 0:
            return "No available draw spots configured (check draw sizes and wildcards)."

        if position <= direct_main:
            return (
                f"✅ **Directly in main draw** (position {position} within main-draw acceptances; "
                f"{direct_main} direct main spots)."
            )
        elif qual_draw_size > 0 and position <= direct_main + direct_qual:
            qual_position = position - direct_main
            return (
                f"✅ **In qualifying draw** (position {qual_position} within qualifying; "
                f"{direct_qual} qualifying spots)."
            )
        else:
            if qual_draw_size > 0:
                return (
                    f"⚠️ **Outside draw** – on alternates list. "
                    f"Position {position} but only {total_spots} total spots "
                    f"({direct_main} main + {direct_qual} qualifying)."
                )
            else:
                return (
                    f"⚠️ **Outside main draw** – on alternates list. "
                    f"Position {position} but only {direct_main} main-draw spots."
                )

    # Main button logic
    if st.button("Calculate position"):
        full_name = (first_name + " " + surname).strip()
        st.write(f"**Player:** {full_name or '(no name entered)'}")

        position_wtn = None
        position_rank = None

        # --- By WTN ---
        if wtn_input.strip() != "" and "WTN_num" in merged.columns:
            try:
                player_wtn = float(wtn_input)
                valid_wtn = merged[merged["WTN_num"].notna()].copy()

                # If ranking available, use for tie-break
                if rank_input.strip() != "" and "Rank_num" in merged.columns:
                    try:
                        player_rank_val = int(rank_input)
                    except ValueError:
                        player_rank_val = None
                else:
                    player_rank_val = None

                # players with strictly better WTN
                better = valid_wtn[valid_wtn["WTN_num"] < player_wtn]

                # same WTN but better ranking (only if we know player's ranking)
                if player_rank_val is not None and "Rank_num" in valid_wtn.columns:
                    better_ties = valid_wtn[
                        (valid_wtn["WTN_num"] == player_wtn)
                        & (valid_wtn["Rank_num"].notna())
                        & (valid_wtn["Rank_num"] < player_rank_val)
                    ]
                    better = pd.concat([better, better_ties])

                position_wtn = int(len(better)) + 1
                total_with_wtn = len(valid_wtn)

                st.write(
                    f"- **WTN basis**: position **{position_wtn}** out of {total_with_wtn} players "
                    f"with a WTN Singles value."
                )

                num_stronger = len(better)
                st.write(
                    f"  → {num_stronger} players have a **better (lower)** WTN (and tie-break if used); "
                    f"{total_with_wtn - position_wtn} have a **worse (higher)** WTN."
                )

                # WTN distribution with player marker
                wtn_data = valid_wtn[["Name", "WTN_num"]]
                base = (
                    alt.Chart(wtn_data)
                    .mark_bar()
                    .encode(
                        x=alt.X(
                            "WTN_num:Q",
                            bin=alt.Bin(maxbins=20),
                            title="WTN Singles",
                        ),
                        y=alt.Y("count():Q", title="Number of players"),
                    )
                    .properties(title="WTN Singles distribution with player highlighted")
                )
                marker = (
                    alt.Chart(pd.DataFrame({"WTN_num": [player_wtn]}))
                    .mark_rule(color="red", strokeWidth=2)
                    .encode(x="WTN_num:Q")
                )
                st.altair_chart(base + marker, use_container_width=True)

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

                # Ranking chart with player's rank marked
                rank_data = valid_rank[["Name", "Rank_num"]]
                base_rank = (
                    alt.Chart(rank_data)
                    .mark_bar()
                    .encode(
                        x=alt.X(
                            "Rank_num:Q",
                            bin=alt.Bin(maxbins=25),
                            title="LTA Combined Ranking",
                        ),
                        y=alt.Y("count():Q", title="Number of players"),
                    )
                    .properties(title="Ranking distribution with player highlighted")
                )
                marker_rank = (
                    alt.Chart(pd.DataFrame({"Rank_num": [player_rank]}))
                    .mark_rule(color="red", strokeWidth=2)
                    .encode(x="Rank_num:Q")
                )
                st.altair_chart(base_rank + marker_rank, use_container_width=True)

            except ValueError:
                st.error("Ranking entered is not a valid whole number.")

        elif rank_input.strip() != "":
            st.warning("No 'Rank' column found in the rankings data.")

        # ------------------------------
        #  ENTRY CHANCE SUMMARY
        # ------------------------------
        st.markdown("### Entry chance summary")

        if selection_basis.startswith("WTN"):
            summary = classify_position(position_wtn)
            if position_wtn is None:
                st.warning(
                    "Selection basis is WTN, but I couldn't calculate a WTN-based position. "
                    "Check that you entered a valid WTN and that the rankings file contains WTN Singles."
                )
            else:
                st.write(summary)
        else:  # Ranking only
            summary = classify_position(position_rank)
            if position_rank is None:
                st.warning(
                    "Selection basis is Ranking, but I couldn't calculate a ranking-based position. "
                    "Check that you entered a valid ranking and that the rankings file contains Rank."
                )
            else:
                st.write(summary)

    # Download button for full result
    csv_data = result.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download full result as CSV",
        data=csv_data,
        file_name="tournament_with_rankings.csv",
        mime="text/csv",
    )
