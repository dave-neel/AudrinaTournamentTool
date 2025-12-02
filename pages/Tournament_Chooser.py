import pandas as pd
import streamlit as st
from datetime import datetime


# -----------------------------
# Helpers
# -----------------------------

def make_template_df() -> pd.DataFrame:
    """Create an empty template for tournaments CSV."""
    cols = [
        "Tournament Name",
        "Start Date",
        "End Date",
        "Location",
        "Country",
        "Surface",
        "Grade",
        "Max Travel Time (hours)",
        "Estimated Draw Strength (1 easy – 10 very hard)",
        "Notes",
    ]
    return pd.DataFrame(columns=cols)


def load_tournaments(upload) -> pd.DataFrame:
    """Load tournaments CSV and parse dates where possible."""
    df = pd.read_csv(upload)

    # Try to parse date columns if present
    for col in ["Start Date", "End Date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def compute_suitability_score(
    df: pd.DataFrame,
    preferred_grades: list[str],
    preferred_surfaces: list[str],
) -> pd.DataFrame:
    """
    Compute a simple suitability score (lower is better).
    Factors:
      - Estimated Draw Strength (1 easy – 10 hard)
      - Max Travel Time (hours)
      - Bonus if grade in preferred_grades
      - Bonus if surface in preferred_surfaces
    """
    score = pd.Series(0.0, index=df.index, dtype="float64")

    # Difficulty: heavier weight (we prefer easier draws)
    diff_col = "Estimated Draw Strength (1 easy – 10 very hard)"
    if diff_col in df.columns:
        # If blank, treat as medium difficulty 5
        diff_vals = pd.to_numeric(df[diff_col], errors="coerce").fillna(5)
        score += diff_vals * 2.0  # difficulty is quite important

    # Travel time: we prefer lower travel time
    travel_col = "Max Travel Time (hours)"
    if travel_col in df.columns:
        travel_vals = pd.to_numeric(df[travel_col], errors="coerce").fillna(2.0)
        score += travel_vals * 1.0

    # Preferred grades: small bonus (lower score) if matches
    if "Grade" in df.columns and preferred_grades:
        grade_match = df["Grade"].astype(str).isin(preferred_grades)
        score -= grade_match.astype(float) * 1.0

    # Preferred surfaces: small bonus if matches
    if "Surface" in df.columns and preferred_surfaces:
        surf_match = df["Surface"].astype(str).isin(preferred_surfaces)
        score -= surf_match.astype(float) * 1.0

    df = df.copy()
    df["Suitability Score (lower = better)"] = score.round(2)
    return df


# -----------------------------
# Streamlit page
# -----------------------------

def main():
    st.title("🎯 Tournament Chooser")

    st.markdown(
        "Use this page to compare possible tournaments for Audrina.\n\n"
        "**Step 1:** Download the template CSV and fill in tournaments.\n\n"
        "**Step 2:** Upload your tournaments CSV.\n\n"
        "**Step 3:** Filter and let the tool rank the best-fit options."
    )

    st.markdown("### 1️⃣ Download tournaments CSV template")

    template_df = make_template_df()
    template_csv = template_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

    st.download_button(
        label="⬇️ Download template CSV",
        data=template_csv,
        file_name="tournament_template.csv",
        mime="text/csv",
        help="Download a blank template to fill with tournaments.",
    )

    st.markdown("---")
    st.markdown("### 2️⃣ Upload tournaments CSV")

    uploaded = st.file_uploader(
        "Upload your tournaments CSV (based on the template)",
        type="csv",
        key="tournament_chooser_csv",
    )

    if uploaded is None:
        st.info(
            "Download the template above, add your tournaments in Excel, "
            "save as CSV, then upload it here."
        )
        return

    # Load and show raw data
    try:
        df = load_tournaments(uploaded)
    except Exception as e:
        st.error(f"Could not read CSV: {e}")
        return

    if df.empty:
        st.error("The uploaded CSV has no rows. Check the file contents.")
        return

    st.success(f"Loaded {len(df)} tournaments from CSV.")
    st.expander("Show raw uploaded data").dataframe(df, use_container_width=True)

    st.markdown("---")
    st.markdown("### 3️⃣ Set your filters")

    # --- Date range filter ---
    date_filtered_df = df
    if "Start Date" in df.columns:
        valid_dates = df["Start Date"].dropna()
        if not valid_dates.empty:
            min_date = valid_dates.min().date()
            max_date = valid_dates.max().date()
            default_range = (min_date, max_date)

            start_date, end_date = st.date_input(
                "Show tournaments between these dates",
                value=default_range,
            )

            if isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, datetime):
                end_date = end_date.date()

            mask = (
                df["Start Date"].dt.date.between(start_date, end_date)
            )
            date_filtered_df = df[mask]
        else:
            st.info("No valid 'Start Date' values found; skipping date filter.")

    else:
        st.info("Column 'Start Date' not found in CSV; skipping date filter.")

    df_filtered = date_filtered_df

    # --- Surface filter ---
    preferred_surfaces = []
    if "Surface" in df_filtered.columns:
        surfaces = sorted(
            s for s in df_filtered["Surface"].dropna().astype(str).unique()
        )
        preferred_surfaces = st.multiselect(
            "Preferred surfaces (optional)",
            options=surfaces,
            default=surfaces,  # show all by default
        )

        if preferred_surfaces:
            df_filtered = df_filtered[
                df_filtered["Surface"].astype(str).isin(preferred_surfaces)
            ]

    # --- Grade filter ---
    preferred_grades = []
    if "Grade" in df_filtered.columns:
        grades = sorted(
            g for g in df_filtered["Grade"].dropna().astype(str).unique()
        )
        preferred_grades = st.multiselect(
            "Preferred grades (optional)",
            options=grades,
            default=grades,  # show all by default
        )

        if preferred_grades:
            df_filtered = df_filtered[
                df_filtered["Grade"].astype(str).isin(preferred_grades)
            ]

    # --- Travel time filter ---
    if "Max Travel Time (hours)" in df_filtered.columns:
        travel_vals = pd.to_numeric(
            df_filtered["Max Travel Time (hours)"], errors="coerce"
        )
        max_travel = travel_vals.max()
        if pd.notna(max_travel):
            max_allowed = st.slider(
                "Maximum travel time (hours)",
                min_value=0.0,
                max_value=float(max_travel),
                value=float(max_travel),
                step=0.5,
            )

            mask_travel = travel_vals <= max_allowed
            df_filtered = df_filtered[mask_travel]

    # --- Difficulty filter ---
    diff_col = "Estimated Draw Strength (1 easy – 10 very hard)"
    if diff_col in df_filtered.columns:
        diff_vals = pd.to_numeric(df_filtered[diff_col], errors="coerce")
        if diff_vals.notna().any():
            min_diff = int(diff_vals.min())
            max_diff = int(diff_vals.max())
            min_sel, max_sel = st.slider(
                "Desired draw difficulty range (1 = easy, 10 = very hard)",
                min_value=min_diff,
                max_value=max_diff,
                value=(min_diff, max_diff),
            )
            mask_diff = diff_vals.between(min_sel, max_sel)
            df_filtered = df_filtered[mask_diff]

    st.markdown("---")
    st.markdown("### 4️⃣ Recommended tournaments")

    if df_filtered.empty:
        st.warning("No tournaments match your filters. Try widening your filters.")
        return

    # Compute suitability score and sort
    df_scored = compute_suitability_score(
        df_filtered,
        preferred_grades=preferred_grades,
        preferred_surfaces=preferred_surfaces,
    )

    df_scored = df_scored.sort_values(
        by=["Suitability Score (lower = better)", "Start Date"],
        ascending=[True, True],
    )

    st.markdown(
        "These tournaments are ordered from **best fit** (top) to **less ideal** (bottom), "
        "based on difficulty, travel time, and your grade/surface preferences."
    )
    st.dataframe(df_scored, use_container_width=True)

    # Allow download of filtered + scored list
    csv_out = df_scored.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        label="⬇️ Download recommended tournaments CSV",
        data=csv_out,
        file_name="tournament_recommendations.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
