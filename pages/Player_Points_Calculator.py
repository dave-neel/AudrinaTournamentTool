import streamlit as st
import pandas as pd
import datetime as dt
import re


# -----------------------------
# Helpers
# -----------------------------

def parse_week_string(week_str: str):
    """
    Parse strings like '49-2025' or '2025-49' into (year, week).
    Returns (year, week) or (None, None) if it can't parse.
    """
    if not isinstance(week_str, str):
        return None, None

    s = week_str.strip()
    if not s:
        return None, None

    # match two numbers separated by non-digit
    m = re.match(r"^\s*(\d{1,2})\D+(\d{4})\s*$", s)
    if m:
        a = int(m.group(1))
        b = int(m.group(2))
        # Decide which is week vs year
        if a > 100:  # e.g. 2025-49
            year, week = a, b
        elif b > 100:  # e.g. 49-2025
            week, year = a, b
        else:
            return None, None
        if 1 <= week <= 53:
            return year, week

    return None, None


def week_to_date(year: int, week: int) -> dt.date:
    """
    Convert ISO (year, week) to a date (Monday of that week).
    """
    return dt.date.fromisocalendar(year, week, 1)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make LTA headers more standard:
    - any column containing 'week' -> 'Week'
    - any column containing 'point' -> 'Points'
    - we keep others as-is (trimmed)
    """
    new_cols = []
    for c in df.columns:
        cl = str(c).strip()
        cl_low = cl.lower()
        if "week" in cl_low:
            new_cols.append("Week")
        elif "point" in cl_low:
            new_cols.append("Points")
        else:
            new_cols.append(cl)
    df = df.copy()
    df.columns = new_cols
    return df


def parse_pasted_table(raw: str) -> pd.DataFrame:
    """
    Parse a pasted LTA-style table from the website into a DataFrame.

    We assume:
    - First non-empty line is the header
    - Columns are separated by tabs (\t) or big gaps of spaces
    - Subsequent lines follow the same structure
    """
    if not raw:
        return pd.DataFrame()

    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return pd.DataFrame()

    header_line = lines[0]

    # Decide separator: prefer tabs, else split on 2+ spaces
    if "\t" in header_line:
        cols = [c.strip() for c in header_line.split("\t")]
        sep = "\t"
    else:
        cols = re.split(r"\s{2,}", header_line.strip())
        cols = [c.strip() for c in cols if c.strip()]
        sep = None  # use regex later

    rows = []
    for ln in lines[1:]:
        if sep == "\t":
            parts = [p.strip() for p in ln.split("\t")]
        else:
            parts = re.split(r"\s{2,}", ln.strip())
            parts = [p.strip() for p in parts if p.strip()]

        # pad/truncate to match columns
        if len(parts) < len(cols):
            parts += [""] * (len(cols) - len(parts))
        elif len(parts) > len(cols):
            parts = parts[: len(cols)]

        rows.append(parts)

    df = pd.DataFrame(rows, columns=cols)
    df = normalize_columns(df)
    return df


def filter_valid_weeks(df: pd.DataFrame, target_date: dt.date) -> pd.DataFrame:
    """
    Keep only tournaments within the last 52 weeks (inclusive)
    relative to target_date, based on a 'Week' column.
    If we can't find / parse weeks, we just return the df unchanged.
    """
    if "Week" not in df.columns:
        return df  # can't filter, just return as-is

    years = []
    weeks = []
    dates = []

    for val in df["Week"]:
        year, week = parse_week_string(str(val))
        if year is None:
            years.append(None)
            weeks.append(None)
            dates.append(None)
        else:
            years.append(year)
            weeks.append(week)
            d = week_to_date(year, week)
            dates.append(d)

    df = df.copy()
    df["Year"] = years
    df["WeekNum"] = weeks
    df["WeekStartDate"] = dates

    if df["WeekStartDate"].isna().all():
        # nothing parsed, don't filter
        return df

    def is_valid(row):
        d = row["WeekStartDate"]
        if not isinstance(d, dt.date):
            return False
        delta = target_date - d
        # valid if between 0 and 52 weeks old
        if delta.days < 0:
            return False
        return delta.days <= 52 * 7

    df = df[df.apply(is_valid, axis=1)]
    return df


def compute_u16_style_points(df_singles: pd.DataFrame, df_doubles: pd.DataFrame):
    """
    U16+ rule:
    - Take best 6 singles (any category)
    - Take best 6 doubles (any category)
    - Doubles count at 25%
    """
    def coerce_points(df):
        # Find a "Points" column (normalized earlier)
        if "Points" not in df.columns:
            return df.assign(PointsNum=pd.NA)
        # remove all non-digits to handle values like '1,500*'
        cleaned = df["Points"].astype(str).str.replace(r"[^\d]", "", regex=True)
        pts = pd.to_numeric(cleaned, errors="coerce")
        df = df.copy()
        df["PointsNum"] = pts
        df = df.dropna(subset=["PointsNum"])
        return df

    s = coerce_points(df_singles)
    d = coerce_points(df_doubles)

    s = s.sort_values("PointsNum", ascending=False).head(6)
    d = d.sort_values("PointsNum", ascending=False).head(6)

    singles_total = int(s["PointsNum"].sum()) if not s.empty else 0
    doubles_raw = int(d["PointsNum"].sum()) if not d.empty else 0
    doubles_weighted = doubles_raw * 0.25
    final_total = singles_total + doubles_weighted

    return {
        "singles_total": singles_total,
        "doubles_raw": doubles_raw,
        "doubles_weighted": doubles_weighted,
        "final_total": final_total,
        "df_s_used": s,
        "df_d_used": d,
    }


# -----------------------------
# Streamlit UI
# -----------------------------

def main():
    st.title("📈 Player Points Calculator (U16+ style)")

    st.markdown(
        "This tool is designed to work well on an **iPhone**.\n\n"
        "You:\n"
        "1. Open the LTA player page in Safari (e.g. Audrina's).\n"
        "2. Copy the entire **Singles Results** table.\n"
        "3. Paste it below.\n"
        "4. Copy and paste the **Doubles Results** table.\n"
        "5. Choose a target date (e.g. the Monday of Week 01-2026).\n"
        "6. I calculate the player's U16-style points (best 6 singles + best 6 doubles, doubles at 25%)."
    )

    st.markdown("### 1️⃣ Player Info")

    profile_url = st.text_input(
        "LTA player profile link (for reference)",
        value="https://competitions.lta.org.uk/ranking/player.aspx?id=49325&player=4971621",
    )

    birth_year = st.number_input(
        "Year of birth",
        min_value=1900,
        max_value=2100,
        value=2011,
        step=1,
        help="Used to understand when they transition into U16+ age group.",
    )

    st.markdown("### 2️⃣ Target ranking week")

    today = dt.date.today()
    target_date = st.date_input(
        "Pick a date within the ranking week you want to calculate for",
        value=today,
        help="For example, choose a date in Week 01-2026 to see points at the start of 2026.",
    )

    iso_year, iso_week, _ = target_date.isocalendar()
    st.info(f"Target ISO week: **{iso_week}-{iso_year}**")

    st.markdown("### 3️⃣ Paste Singles and Doubles tables from LTA")

    with st.expander("📋 Paste Singles Results table here"):
        st.markdown(
            "On the LTA page:\n"
            "- Scroll to **Singles Results**\n"
            "- Long-press → Select All → Copy\n"
            "- Paste into this box."
        )
        singles_raw = st.text_area(
            "Singles table",
            height=200,
            placeholder="Week\tTournament\tGrade\tAge Group\tPoints\n49-2025\tExample Tournament\t3\t18U\t450\n...",
        )

    with st.expander("📋 Paste Doubles Results table here"):
        st.markdown(
            "On the LTA page:\n"
            "- Scroll to **Doubles Results**\n"
            "- Long-press → Select All → Copy\n"
            "- Paste into this box."
        )
        doubles_raw = st.text_area(
            "Doubles table",
            height=200,
            placeholder="Week\tTournament\tGrade\tAge Group\tPoints\n49-2025\tExample Doubles\t3\t18U\t450\n...",
        )

    if st.button("🔢 Calculate points"):
        if not singles_raw.strip():
            st.error("Please paste the Singles table.")
            return
        if not doubles_raw.strip():
            st.error("Please paste the Doubles table.")
            return

        # Parse pasted tables
        df_singles = parse_pasted_table(singles_raw)
        df_doubles = parse_pasted_table(doubles_raw)

        if df_singles.empty:
            st.error("Could not parse Singles table. Check the format after pasting.")
            return
        if df_doubles.empty:
            st.error("Could not parse Doubles table. Check the format after pasting.")
            return

        st.success("Tables parsed successfully.")

        # Show parsed headers so you can see what it understood
        st.write("**Singles columns detected:**", list(df_singles.columns))
        st.write("**Doubles columns detected:**", list(df_doubles.columns))

        # Filter by 52-week validity
        df_singles_valid = filter_valid_weeks(df_singles, target_date)
        df_doubles_valid = filter_valid_weeks(df_doubles, target_date)

        st.markdown("#### Valid Singles Results (within last 52 weeks)")
        st.dataframe(df_singles_valid, use_container_width=True)

        st.markdown("#### Valid Doubles Results (within last 52 weeks)")
        st.dataframe(df_doubles_valid, use_container_width=True)

        # Age info (for future U14/U16 logic)
        age_at_target = iso_year - int(birth_year)
        st.info(f"Age at target year: approx **{age_at_target}**.")

        # For this first version, always apply U16+ style:
        result = compute_u16_style_points(df_singles_valid, df_doubles_valid)

        st.markdown("### 🧮 U16+ Style Points Summary")

        st.write(f"**Singles total (best 6):** {result['singles_total']}")
        st.write(f"**Doubles raw total (best 6):** {result['doubles_raw']}")
        st.write(f"**Doubles weighted @ 25%:** {result['doubles_weighted']:.1f}")
        st.write(f"**Final combined total:** `{result['final_total']:.1f}`")

        with st.expander("See singles tournaments used"):
            st.dataframe(result["df_s_used"], use_container_width=True)

        with st.expander("See doubles tournaments used"):
            st.dataframe(result["df_d_used"], use_container_width=True)


if __name__ == "__main__":
    main()
