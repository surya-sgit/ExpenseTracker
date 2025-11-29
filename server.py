import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

# Initialize Server
mcp = FastMCP("Expense Tracker Cloud")
DATABASE_URL = os.getenv("DATABASE_URL")

# --- HELPER: Database Connection ---
def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is missing! Check your Secrets.")
    return psycopg2.connect(DATABASE_URL)

# --- INIT: Create Table ---
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            amount REAL,
            main_category TEXT,
            sub_category TEXT,
            description TEXT,
            date DATE DEFAULT CURRENT_DATE
        )
    ''')
    conn.commit()
    conn.close()

# Run init on startup
try:
    init_db()
except Exception as e:
    print(f"DB Init Warning: {e}")

# --- TOOL 1: ANALYST (Read-Only) ---
@mcp.tool()
def analyze_database(query: str) -> str:
    """Read-only SQL analysis. Table: expenses."""
    cleaned = query.strip().upper()
    if not cleaned.startswith("SELECT"): return "❌ Error: Read-only access."
    if "LIMIT" not in cleaned: query += " LIMIT 20"

    try:
        conn = get_db_connection()
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute(query)
        rows = c.fetchall()
        conn.close()
        
        if not rows: return "No results."
        
        results = f"🔍 Found {len(rows)} rows:\n"
        if rows:
            cols = rows[0].keys()
            results += " | ".join(cols) + "\n" + "-"*50 + "\n"
            for row in rows:
                results += " | ".join(str(row[c]) for c in cols) + "\n"
        return results
    except Exception as e:
        return f"❌ SQL Error: {e}"

# --- TOOL 2: ADD ---
@mcp.tool()
def add_expense(amount: float, main_category: str, sub_category: str, description: str, date: str = None) -> str:
    """Records expense. Date: YYYY-MM-DD."""
    conn = get_db_connection()
    c = conn.cursor()
    if not date: date = datetime.now().strftime("%Y-%m-%d")
    
    c.execute("INSERT INTO expenses (amount, main_category, sub_category, description, date) VALUES (%s, %s, %s, %s, %s) RETURNING id", 
              (amount, main_category, sub_category, description, date))
    eid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return f"✅ Saved ID #{eid}: ₹{amount} for {description}"

# --- TOOL 3: DELETE ---
@mcp.tool()
def delete_expense(expense_id: int) -> str:
    """Deletes expense by ID."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM expenses WHERE id=%s", (expense_id,))
    if not c.fetchone(): 
        conn.close()
        return "❌ ID not found."
    c.execute("DELETE FROM expenses WHERE id=%s", (expense_id,))
    conn.commit()
    conn.close()
    return f"🗑️ Deleted ID #{expense_id}"

# --- TOOL 4: UPDATE ---
@mcp.tool()
def update_expense(expense_id: int, field: str, new_value: str) -> str:
    """Updates field (amount, description, date)."""
    allowed = ['amount', 'description', 'main_category', 'sub_category', 'date']
    if field not in allowed: return "❌ Invalid field."
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE expenses SET {field} = %s WHERE id = %s", (new_value, expense_id))
    conn.commit()
    conn.close()
    return f"✅ Updated ID #{expense_id}"

if __name__ == "__main__":
    mcp.run()