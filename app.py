"""OSU P-card audit explorer. Run with: streamlit run app.py"""
import os
import re
import sqlite3
from pathlib import Path
from urllib import request, error
import json
import zipfile

import pandas as pd
import streamlit as st

st.set_page_config(page_title="OSU P-card Audit Explorer", page_icon="🔎", layout="wide")
ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("PCARD_DB_PATH", str(ROOT / "osu_pcards.db")))
if not DB_PATH.exists() and (ROOT / "osu_pcards.db.zip").exists():
    with zipfile.ZipFile(ROOT / "osu_pcards.db.zip") as archive:
        archive.extract("osu_pcards.db", ROOT)
FIELDS = {"Year", "Month", "FullName", "ID", "AgencyNumber", "AgencyName", "CardholderLastName", "CardholderFirstInitial", "Description", "Amount", "Vendor", "TransactionDate", "PostedDate", "MCC"}
DISPLAY_FIELDS = ["Year", "TransactionDate", "PostedDate", "FullName", "Vendor", "Description", "Amount", "MCC"]
CATEGORIES = {
    "Alcohol": ["alcohol", "liquor", "beer", "wine", "spirits"],
    "Cash / ATM": ["atm", "cash advance", "cash withdrawal"],
    "Decorations": ["decoration", "decorations", "ornament", "party decor"],
    "Donations / sponsorships": ["donation", "donate", "sponsor", "contribution"],
    "Gasoline": ["gasoline", "gas station", "fuel", "petrol"],
    "Gifts / gift cards": ["gift card", "gift certificate", "gift basket", "gift"],
    "Insurance": ["insurance", "premium"],
    "Late fees": ["late fee", "late charge", "penalty fee"],
    "Mail / postage": ["postage", "post office", "usps", "mailing"],
    "Moving expenses": ["moving", "relocation", "movers"],
    "Personal purchases": ["personal", "household", "private use"],
    "Individual memberships": ["membership", "member dues", "individual dues"],
    "Salaries / wages / benefits": ["salary", "payroll", "wages", "employee benefits"],
    "Service / incentive awards": ["incentive award", "service award", "employee award", "recognition award"],
}

@st.cache_data(show_spinner=False)
def years_available():
    with sqlite3.connect(DB_PATH) as con:
        return [int(r[0]) for r in con.execute('SELECT DISTINCT "Year" FROM pcards WHERE "Year" IS NOT NULL ORDER BY "Year" DESC')]

@st.cache_data(show_spinner=False, ttl=600)
def run_sql(sql: str, params=()):
    """Enforce read-only SQL at the SQLite engine, not only by string matching."""
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.I):
        raise ValueError("Only SELECT queries are permitted.")
    if ";" in sql.rstrip().rstrip(";"):
        raise ValueError("Only one statement is permitted.")
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        def authorize(action, p1, p2, dbname, source):
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
            return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
        con.set_authorizer(authorize)
        con.set_progress_handler(lambda: 1 if __import__('time').monotonic() > deadline[0] else 0, 10000)
        deadline = [__import__('time').monotonic() + 8]
        return pd.read_sql_query(sql, con, params=params)

def show_results(df, label="Matching transactions"):
    st.metric(label, f"{len(df):,}")
    if df.empty:
        st.info("No matching records. Try a different year or keyword.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button("Download results as CSV", data=df.to_csv(index=False).encode("utf-8-sig"), file_name="pcard_audit_results.csv", mime="text/csv")
    st.caption("A keyword match or unusual amount is a risk indicator, not evidence that a policy violation or fraud occurred. Verify receipts, purpose, approvals, and relevant exceptions.")

def escape_like(term):
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def lookup(field, year, keyword):
    if field not in {"Description", "Vendor"}:
        raise ValueError("Invalid search field")
    sql = f'SELECT "Year", "TransactionDate", "PostedDate", "FullName", "Vendor", "Description", "Amount", "MCC" FROM pcards WHERE "Year"=? AND COALESCE("{field}", \'\') LIKE ? ESCAPE \'\\\' COLLATE NOCASE ORDER BY "TransactionDate", "FullName" LIMIT 5000'
    return run_sql(sql, (year, "%" + escape_like(keyword.strip()) + "%"))

def local_question(question, year):
    """Transparent, deterministic natural-language question support without an API key."""
    q = question.lower().strip()
    if any(w in q for w in ("top vendor", "most popular vendor", "vendors spent", "spending by vendor", "largest vendor")):
        return ('SELECT "Vendor", COUNT(*) AS Transactions, ROUND(SUM("Amount"),2) AS TotalSpent FROM pcards WHERE "Year"=? GROUP BY "Vendor" ORDER BY TotalSpent DESC LIMIT 20', (year,), "Top vendors by total net amount")
    if any(w in q for w in ("top employee", "top cardholder", "employee spent", "highest spending employee", "spending by employee", "most spent")):
        return ('SELECT "FullName", COUNT(*) AS Transactions, ROUND(SUM("Amount"),2) AS TotalSpent FROM pcards WHERE "Year"=? GROUP BY "FullName" ORDER BY TotalSpent DESC LIMIT 20', (year,), "Top employees by total net amount")
    if any(w in q for w in ("monthly", "by month", "per month", "month by month")):
        return ('SELECT "Month", COUNT(*) AS Transactions, ROUND(SUM("Amount"),2) AS TotalSpent FROM pcards WHERE "Year"=? GROUP BY "Month" ORDER BY "Month"', (year,), "Monthly spending")
    if any(w in q for w in ("over $5,000", "over 5000", "above 5000", "exceed $5,000")):
        return ('SELECT "TransactionDate", "FullName", "Vendor", "Description", "Amount", "MCC" FROM pcards WHERE "Year"=? AND "Amount">5000 ORDER BY "Amount" DESC LIMIT 500', (year,), "Transactions above $5,000")
    if any(w in q for w in ("largest transaction", "biggest transaction", "highest transaction")):
        return ('SELECT "TransactionDate", "FullName", "Vendor", "Description", "Amount", "MCC" FROM pcards WHERE "Year"=? ORDER BY "Amount" DESC LIMIT 20', (year,), "Largest transactions")
    if any(w in q for w in ("how many", "number of transactions", "transaction count", "total transactions")):
        return ('SELECT COUNT(*) AS Transactions, ROUND(SUM("Amount"),2) AS NetAmount FROM pcards WHERE "Year"=?', (year,), "Transaction count and net amount")
    if any(w in q for w in ("total spending", "total spent", "overall spend", "total amount")):
        return ('SELECT ROUND(SUM("Amount"),2) AS NetAmount, COUNT(*) AS Transactions FROM pcards WHERE "Year"=?', (year,), "Total net spending")
    return None

def secret_api_key():
    try:
        return st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        return os.environ.get("OPENAI_API_KEY", "")

def ai_question(question, year, api_key):
    """Optional API-based text-to-SQL. No key is ever sent to the browser."""
    system = ("Generate one SQLite SELECT query for an auditor. Return ONLY a JSON object with keys sql and explanation. "
              "Table: pcards(Year INTEGER, Month INTEGER, FullName TEXT, ID INTEGER, AgencyNumber INTEGER, "
              "AgencyName TEXT, CardholderLastName TEXT, CardholderFirstInitial TEXT, Description TEXT, "
              "Amount REAL, Vendor TEXT, TransactionDate TEXT, PostedDate TEXT, MCC TEXT). "
              "Year is an integer. TransactionDate and PostedDate are text in M/D/YYYY H:MM:SS format; "
              "do not use lexicographic date ordering to infer chronology. "
              f"Always filter Year = {year}; all rows belong to Oklahoma State University. "
              "Only read from pcards. Never use write operations, PRAGMA, ATTACH, extensions, or multiple statements. "
              "For detail queries LIMIT 500; aggregate queries LIMIT 100. "
              "Clearly state that findings are potential exceptions only.")
    body = json.dumps({"model": "gpt-4.1-mini", "temperature": 0, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}] }).encode()
    req = request.Request("https://api.openai.com/v1/chat/completions", data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    with request.urlopen(req, timeout=20) as resp:
        payload = json.load(resp)
    result = json.loads(payload["choices"][0]["message"]["content"])
    sql = result["sql"].strip()
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.I) or not re.search(r'\bYear\b\s*=\s*'+str(year)+r'\b', sql, re.I):
        raise ValueError("Generated query failed the year/read-only safety check.")
    return sql, result.get("explanation", "AI-generated SQL; verify the results.")

st.title("🔎 Oklahoma State University | P-card Audit Explorer")
st.write("Explore purchasing-card transactions and identify **potential** internal-control exceptions. All records in this project are from Oklahoma State University.")
if not DB_PATH.is_file():
    st.error("Database not found. Place osu_pcards.db beside app.py, or set PCARD_DB_PATH.")
    st.stop()
try:
    years = years_available()
except sqlite3.Error as ex:
    st.error(f"Unable to open database: {ex}")
    st.stop()

with st.sidebar:
    st.header("Audit settings")
    year = st.selectbox("Transaction year", years, index=years.index(2014) if 2014 in years else 0)
    st.caption("Searches use the Year field from the source database. Dates are shown as recorded.")
    st.info("For every flagged item, inspect the receipt, business purpose, approvals and policy exceptions before drawing conclusions.")

tab1, tab2 = st.tabs(["💬 Ask Questions", "🛡️ Prohibited Purchases Dashboard"])
with tab1:
    st.subheader("Ask a question in plain English")
    st.markdown("**Instructions:** Select a year in the sidebar, enter a question, and click **Run question**. Standard questions work without an API key. If a server-side OpenAI API key is configured, other questions can be translated into read-only SQL. Always review the generated query.")
    st.caption("Examples: Which employees spent the most? · Show monthly spending · How many transactions? · Show transactions over $5,000 · Which vendors received the most?")
    question = st.text_input("Your audit question", placeholder="Which employees spent the most in 2014?")
    if st.button("Run question", type="primary"):
        if not question.strip():
            st.warning("Enter a question first.")
        else:
            try:
                answer = local_question(question, year)
                if answer:
                    sql, params, description = answer
                elif secret_api_key():
                    sql, description = ai_question(question, year, secret_api_key())
                    params = ()
                else:
                    st.warning("This question is not one of the built-in patterns. Try an example above, or configure OPENAI_API_KEY in Streamlit secrets for broader natural-language support.")
                    st.stop()
                st.write("**Interpretation:**", description)
                with st.expander("View SQL query"):
                    st.code(sql, language="sql")
                show_results(run_sql(sql, params), "Rows returned")
            except (sqlite3.Error, ValueError, error.URLError, KeyError, TimeoutError) as ex:
                st.error(f"Unable to answer safely: {ex}")
with tab2:
    st.subheader("Search potentially prohibited purchases")
    st.markdown("**Instructions:** (1) Choose a year in the sidebar. (2) Choose a policy-risk category to see suggested terms, or enter your own keyword. (3) Use **Description search** to search the transaction description or **Vendor search** to search merchant names. (4) Review the transactions and export CSV for follow-up.")
    st.caption("Categories reflect the prohibited-purchase list in Part IV of the assignment. Keywords are screening indicators and may miss transactions or produce false positives.")
    category = st.selectbox("Policy risk category (optional guidance)", ["Custom keyword"] + list(CATEGORIES))
    if category != "Custom keyword":
        st.write("Suggested keywords: " + ", ".join(CATEGORIES[category]))
    keyword = st.text_input("Keyword (case-insensitive)", placeholder="e.g., alcohol, USPS, gift card")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Description search")
        desc_click = st.button("Search descriptions", use_container_width=True)
    with col2:
        st.markdown("### Vendor search")
        vendor_click = st.button("Search vendors", use_container_width=True)
    if desc_click or vendor_click:
        if not keyword.strip():
            st.warning("Enter a keyword before searching.")
        else:
            field = "Description" if desc_click else "Vendor"
            st.write(f"Searching **{field}** for **{keyword.strip()}** in **{year}** (up to 5,000 rows).")
            try:
                show_results(lookup(field, year, keyword))
            except (sqlite3.Error, ValueError) as ex:
                st.error(f"Search error: {ex}")
    st.divider()
    st.markdown("**Audit follow-up:** A match does not prove an improper purchase. Confirm the item's nature, business purpose, supporting documents, authorizations, and any policy exceptions. Some prohibited purchases cannot be reliably detected from merchant or description text alone.")
