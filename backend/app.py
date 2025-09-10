from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3, os, re
from typing import Dict, List, Optional
from dotenv import load_dotenv
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from nixtlats import TimeGPT

# Load .env
load_dotenv()

app = FastAPI(title="NL to SQL (Northwind) + Forecast Detector", version="3.6")

# CORS for dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "northwind.db"))

# ================== GROQ ==================
def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GROQ client init error: {e}")

# ================== MODELS ==================
class QueryRequest(BaseModel):
    query: str

class SQLRequest(BaseModel):
    type: str
    sql: str
    periods: Optional[int] = None   # 👈 dynamic forecast horizon (months)
    used_llm: bool = False

# ================== DATABASE ==================
def connect():
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail=f"DB not found at {DB_PATH}")
    return sqlite3.connect(DB_PATH)

def get_schema_text() -> str:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [r[0] for r in cur.fetchall()]
    schema: Dict[str, List[str]] = {}
    for t in tables:
        cur.execute(f"PRAGMA table_info('{t}')")
        schema[t] = [row[1] for row in cur.fetchall()]
    conn.close()
    lines = []
    for t, cols in schema.items():
        lines.append(f'{t}: {", ".join(cols)}')
    return "\n".join(lines)

# ================== HELPERS ==================
def clean_sql(text: str) -> str:
    if not text:
        return text
    s = text.strip()
    s = re.sub(r"^```sql\s*|\s*```$", "", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"^```\s*|\s*```$", "", s, flags=re.DOTALL)
    m = re.search(r"```sql\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        s = m.group(1).strip()
    if ";" in s and "\n" in s and not s.lower().lstrip().startswith(("select","with")):
        first_stmt = s.split(";")[0] + ";"
        s = first_stmt
    return s.strip()

def enforce_forecast_columns(sql: str) -> str:
    """Ensure SQL output has 'date' and 'value' columns."""
    sql = re.sub(r"\bas\s+month\b", "AS date", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bas\s+year\b", "AS date", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bas\s+period\b", "AS date", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bas\s+(amount|sales|revenue|total|qty|quantity)\b", "AS value", sql, flags=re.IGNORECASE)

    # 👇 NEW: if SQL does not already include a GROUP BY with date, auto-convert
    if " as date" not in sql.lower() and "group by" not in sql.lower():
        sql = (
            "SELECT strftime('%Y-%m', OrderDate) AS date, "
            "COUNT(*) AS value FROM Orders GROUP BY strftime('%Y-%m', OrderDate) ORDER BY date;"
        )
    return sql

def extract_forecast_horizon(nl: str) -> int:
    """
    Detect forecast horizon (in months) from natural language.
    Examples:
      - "next 6 months" -> 6
      - "next 2 years" -> 24
      - "3 quarters" -> 9
    Defaults to 6 months if not found.
    """
    nl = nl.lower()

    # explicit months
    m = re.search(r"(\d+)\s+month", nl)
    if m:
        return int(m.group(1))

    # explicit years
    y = re.search(r"(\d+)\s+year", nl)
    if y:
        return int(y.group(1)) * 12

    # explicit quarters
    q = re.search(r"(\d+)\s+quarter", nl)
    if q:
        return int(q.group(1)) * 3

    # "next N" (assume months)
    n = re.search(r"next\s+(\d+)\b", nl)
    if n:
        return int(n.group(1))

    return 6

def fallback_sql(nl: str) -> str:
    q = nl.lower()
    if "top" in q and "customer" in q:
        return ("SELECT c.CompanyName, COUNT(o.OrderID) AS TotalOrders "
                "FROM Customers c JOIN Orders o ON c.CustomerID = o.CustomerID "
                "GROUP BY c.CustomerID, c.CompanyName "
                "ORDER BY TotalOrders DESC LIMIT 5;")
    if "how many orders" in q or "total orders" in q:
        # 👇 changed to monthly grouping for forecasting
        return ("SELECT strftime('%Y-%m', OrderDate) AS date, COUNT(*) AS value "
                "FROM Orders GROUP BY strftime('%Y-%m', OrderDate) ORDER BY date;")
    if "top" in q and "employee" in q:
        return ("SELECT e.FirstName || ' ' || e.LastName AS EmployeeName, COUNT(o.OrderID) AS OrdersHandled "
                "FROM Employees e JOIN Orders o ON e.EmployeeID = o.EmployeeID "
                "GROUP BY e.EmployeeID ORDER BY OrdersHandled DESC LIMIT 3;")
    if "by category" in q:
        return ("SELECT c.CategoryName AS Category, "
                "SUM(od.UnitPrice * od.Quantity * (1 - od.Discount)) AS SalesAmount "
                "FROM Orders o "
                "JOIN \"Order Details\" od ON od.OrderID = o.OrderID "
                "JOIN Products p ON p.ProductID = od.ProductID "
                "JOIN Categories c ON c.CategoryID = p.CategoryID "
                "GROUP BY c.CategoryName ORDER BY SalesAmount DESC;")
    return ("SELECT strftime('%Y-%m', OrderDate) AS date, COUNT(*) AS value "
            "FROM Orders GROUP BY strftime('%Y-%m', OrderDate) ORDER BY date;")

def _classify_with_llm(nl: str, client) -> str:
    system_prompt = """
    You are a query classifier. Analyze the user's question and determine if it is asking for a future prediction/forecast.
    Respond with ONLY a single word: either 'plain' or 'forecast'.
    """
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "gemma2-9b-it"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {nl}"},
        ],
        temperature=0.0,
        max_tokens=10,
    )
    classification = response.choices[0].message.content.strip().lower()
    return classification if classification in ['plain', 'forecast'] else 'plain'

def _is_ambiguous(query: str) -> bool:
    ambiguous_phrases = ["look like", "will be", "what will", "how will", "going to be", "should we expect"]
    pattern = r'\b(' + '|'.join(ambiguous_phrases) + r')\b'
    return re.search(pattern, query.lower()) is not None

def classify_query_type(nl: str) -> str:
    forecast_keywords = ["forecast", "predict", "projection", "outlook",
                         "next year", "next quarter", "coming months",
                         "will be", "expected", "estimate", "trend"]
    pattern = r'\b(' + '|'.join(forecast_keywords) + r')\b'
    clear_forecast_match = re.search(pattern, nl.lower()) is not None

    plain_indicators = ["list", "show", "what are", "who are", "how many", "history", "past", "previous", "current", "today"]
    plain_pattern = r'\b(' + '|'.join(plain_indicators) + r')\b'
    clear_plain_match = re.search(plain_pattern, nl.lower()) is not None

    if clear_forecast_match:
        return "forecast"
    if clear_plain_match:
        return "plain"

    client = get_groq_client()
    if client and _is_ambiguous(nl):
        try:
            return _classify_with_llm(nl, client)
        except Exception as e:
            print(f"LLM classification failed, fallback to plain: {e}")

    return "plain"

def _coerce_date_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make sure 'date' column is a datetime; supports strings like 'YYYY' or 'YYYY-MM'.
    Raises if unparseable.
    """
    if "date" not in df.columns:
        return df
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if df["date"].isna().any():
        raise HTTPException(status_code=400, detail="Could not parse 'date' column into datetime.")
    return df

# ================== FORECASTING ==================
def run_forecast_arima(sql: str, periods: int):
    try:
        conn = connect()
        df = pd.read_sql_query(sql, conn)
        conn.close()
        df = _coerce_date_column(df)
        print(df)  # debug
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecast SQL error: {e}")

    if df.empty or "date" not in df.columns or "value" not in df.columns:
        raise HTTPException(status_code=400,
                            detail="Forecast queries must return columns [date, value].")

    df = df.sort_values("date")
    series = df.set_index("date")["value"]

    if len(series) < 3:
        raise HTTPException(status_code=400, detail="Not enough data points for forecasting.")

    try:
        model = ARIMA(series, order=(2, 1, 2))
        model_fit = model.fit()
        forecast = model_fit.forecast(steps=periods)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ARIMA forecast error: {e}")

    return {
        "historical": df.to_dict(orient="records"),
        "forecast": [{"date": str(date), "value": float(val)} for date, val in forecast.items()],
    }

def run_forecast_timegpt(sql: str, periods: int):
    try:
        conn = connect()
        df = pd.read_sql_query(sql, conn)
        conn.close()
        df = _coerce_date_column(df)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecast SQL error: {e}")

    if df.empty or "date" not in df.columns or "value" not in df.columns:
        raise HTTPException(status_code=400,
                            detail="Forecast queries must return [date, value].")

    api_key = os.getenv("TIMEGPT_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing TIMEGPT_API_KEY in .env")

    try:
        tgpt = TimeGPT(api_key=api_key)
        fcst_df = tgpt.forecast(df=df.rename(columns={"date": "ds", "value": "y"}), h=periods)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TimeGPT forecast error: {e}")

    return {
        "historical": df.to_dict(orient="records"),
        "forecast": fcst_df.to_dict(orient="records"),
    }

# ================== ROUTES ==================
@app.get("/api/ping")
def ping():
    return {"status": "ok"}

@app.post("/api/translate")
def translate(req: QueryRequest):
    schema_text = get_schema_text()
    query_type = classify_query_type(req.query)

    # Extract forecast horizon (months) from NL
    periods = extract_forecast_horizon(req.query) if query_type == "forecast" else None

    system = (
        "You are a SQLite SQL assistant for the Northwind database.\n"
        "Use EXACT table names from the provided schema. If a table name has spaces (e.g., Order Details), wrap it in double quotes.\n"
        "Return ONLY the SQL query with no explanation.\n"
        "\n"
        "IMPORTANT FOR FORECASTING QUERIES:\n"
        "- If the user asks for forecasting/prediction, return the HISTORICAL time-series needed for forecasting.\n"
        "- The SQL must return exactly two columns: 'date' (period label) and 'value' (numeric).\n"
        "- Use real period labels, not synthetic dates.\n"
        "  * Yearly:   strftime('%Y', OrderDate)        AS date\n"
        "  * Monthly:  strftime('%Y-%m', OrderDate)      AS date\n"
        "  * Quarterly: build as 'YYYY-Qn' via CASE on strftime('%m', OrderDate) and alias AS date\n"
        "- Value examples:\n"
        "  * Sales:  SUM(od.Quantity * od.UnitPrice * (1 - od.Discount)) AS value\n"
        "  * Orders: COUNT(*) AS value\n"
        "- Do NOT perform the forecast in SQL; only provide [date, value].\n"
        "- Quote table names with spaces, e.g., \"Order Details\".\n"
    )

    user = f"Schema:\n{schema_text}\n\nUser question: {req.query}\nReturn ONLY SQL."
    sql = None
    debug = {}
    used_llm = False

    client = get_groq_client()
    if client:
        try:
            resp = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "gemma2-9b-it"),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
            )
            raw = resp.choices[0].message.content
            sql = clean_sql(raw)
            used_llm = True
            debug = {"note": "groq used"}
        except Exception as e:
            debug = {"groq_error": str(e)}

    if not sql:
        sql = fallback_sql(req.query)

    if query_type == "forecast":
        sql = enforce_forecast_columns(sql)

    return {
        "type": query_type,
        "sql": sql,
        "periods": periods,   # 👈 include horizon in months
        "used_llm": used_llm,
        "debug": debug
    }

@app.post("/api/run-sql")
def run_sql(req: SQLRequest):
    sql = req.sql.strip()
    if not sql.lower().lstrip().startswith(("select", "with")):
        raise HTTPException(status_code=400, detail="Only SELECT/CTE queries are allowed.")

    if req.type == "forecast":
        # If frontend didn't pass periods, default to 6 (but ideally pass from /api/translate)
        periods = req.periods if req.periods and req.periods > 0 else 6
        print(f"📊 Forecast SQL: {sql} | Horizon: {periods} months")  # Debug log
        try:
            forecast_data = run_forecast_timegpt(sql, periods)
        except Exception as e:
            print(f"⚠️ TimeGPT failed, falling back to ARIMA: {e}")
            forecast_data = run_forecast_arima(sql, periods)

        return {"columns": ["date", "value"], "forecast_result": forecast_data}

    try:
        conn = connect()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        data = [[row[c] for c in cols] for row in rows]
        conn.close()
        return {"columns": cols, "rows": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL execution error: {e}")