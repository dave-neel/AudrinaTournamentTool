import streamlit as st
import pandas as pd
import datetime as dt
import re


# -----------------------------
# Helpers for weeks & points
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


def normalize_columns_results(df: pd.DataFrame) -> pd.DataFrame:
    """
    For player results tables.
    - any column containing 'week' -> 'Week'
    - any column containing 'point' -> 'Points'
    - keep others as trimmed originals
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


def parse_pasted_results_table(raw: str) -> pd.DataFrame:
    """
    Parse a pasted LTA-style RESULTS section (Singles or Doubles) into a DataFrame.

    - Ignore any lines BEFORE the real header row
      (we search for the first line containing 'week')
    - Assume that header row has columns separated by tabs or 2+ spaces
    - Apply the same split logic to subsequent rows
    """
    if not raw:
        return pd.DataFrame()

    # Keep all non-empty lines
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return pd.DataFrame()

    # Find header line: the first line that looks like it contains a Week column
    header_idx = None
    for idx, ln in enumerate(lines):
        if "week" in ln.lower():
            header_idx = idx
            break

    # If we never find a line with 'week', we can't reliably parse
    if header_idx is None:
        return pd.DataFrame()

    header_line = lines[header_idx]
    data_lines = lines[header_idx + 1 :]

    # Decide separator: prefer tabs, else split on 2+ spaces
    if "\t" in header_line:
        cols = [c.strip() for c in header_line.split("\t")]
        sep = "\t"
    else:
        cols = re.split(r"\s{2,}", header_line.strip())
        cols = [c.strip() for c in cols if c.strip()]
        sep = None  # use regex later

    rows = []
    for ln in data_lines:
        if sep == "\t":
            parts = [p.strip() for p in ln.split("\t")]
        else:
            parts = re.split(r"\s{2,}", ln.strip())
            parts = [p.strip() for p in parts if p.strip()]

        if not parts:
            continue

        # pad/truncate to match columns
        if len(parts) < len(cols):
            parts += [""] * (len(cols) - len(parts))
        elif len(parts) > len(cols):
            parts = parts[: len(cols)]

        rows.append(parts)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=cols)
    df = normalize_columns_results(df)
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
        "Use it to calculate a player's U16-style ranking points for a chosen week:\n\n"
        "- Best 6 **Singles** results (any category)\n"
        "- Best 6 **Doubles** results (any category)\n"
        "- Doubles counted at **25%**\n"
        "- Only tournaments within **52 weeks** of your chosen date are included."
    )

    st.markdown("### 1️⃣ Player Info")

    profile_url = st.text_input(
        "LTA player profile link (for reference)",
        value="https://competitions.lta.org.uk/ranking/player.aspx?id=49325&player=4971621",
    )

    player_name = st.text_input(
        "Player name (for your notes)",
        value="Audrina Neeladoo",
    )

    birth_year = st.number_input(
        "Year of birth",
        min_value=1900,
        max_value=2100,
        value=2011,
        step=1,
        help="Used only for your own reference here.",
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

    st.markdown("### 3️⃣ Paste Singles and Doubles results from player page")

    with st.expander("📋 Paste Singles Results section here"):
        st.markdown(
            "On the LTA page:\n"
            "- Scroll to **Singles Results**\n"
            "- Select from the header row (where it shows 'Week ...') down to the bottom of the table\n"
            "- Copy\n"
            "- Paste into this box."
        )
        singles_raw = st.text_area(
            "Singles section",
            height=220,
            placeholder="Week\tTournament\tEvent\tResult\tPoints\tMatches\n49-2025\tExample Tournament\t18U Singles\tW\t450\t5\n...",
        )

    with st.expander("📋 Paste Doubles Results section here"):
        st.markdown(
            "On the LTA page:\n"
            "- Scroll to **Doubles Results**\n"
            "- Select from the header row (where it shows 'Week ...') down to the bottom of the table\n"
            "- Copy\n"
            "- Paste into this box."
        )
        doubles_raw = st.text_area(
            "Doubles section",
            height=220,
            placeholder="Week\tTournament\tEvent\tResult\tPoints\tMatches\n49-2025\tExample Doubles\t18U Doubles\tW\t450\t4\n...",
        )

    if st.button("🔢 Calculate points"):
        if not singles_raw.strip():
            st.error("Please paste the Singles section.")
            return
        if not doubles_raw.strip():
            st.error("Please paste the Doubles section.")
            return

        # Parse player results tables
        df_singles = parse_pasted_results_table(singles_raw)
        df_doubles = parse_pasted_results_table(doubles_raw)

        if df_singles.empty:
            st.error("Could not find a header row with 'Week' in the Singles section. "
                     "Try selecting from the header row downwards.")
            return
        if df_doubles.empty:
            st.error("Could not find a header row with 'Week' in the Doubles section. "
                     "Try selecting from the header row downwards.")
            return

        st.success("Singles & Doubles tables parsed successfully.")

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

        # Apply U16+ style scoring
        result = compute_u16_style_points(df_singles_valid, df_doubles_valid)

        st.markdown("### 🧮 U16+ Style Points Summary")

        st.write(f"**Player:** {player_name}")
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
