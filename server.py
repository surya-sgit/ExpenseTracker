import sqlite3
import json
from datetime import datetime
from fastmcp import FastMCP

# Initialize Server
mcp = FastMCP("Expense Tracker Secure")
DB_FILE = "expenses.db"

# --- HELPER: Database Connection ---
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

# --- INIT: Create Table ---
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL,
            main_category TEXT,
            sub_category TEXT,
            description TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- TOOL 1: THE SECURE ANALYST (Read-Only SQL) ---
@mcp.tool()
def analyze_database(query: str) -> str:
    """
    Runs a READ-ONLY SQL query to answer questions.
    Table: 'expenses'. Columns: id, amount, main_category, sub_category, description, date.
    """
    cleaned_query = query.strip().upper()
    
    # SECURITY LAYER 1: Block destructive commands
    if not cleaned_query.startswith("SELECT"):
        return "❌ SECURITY BLOCK: This tool allows READ-ONLY access (SELECT) only."

    # SECURITY LAYER 2: Prevent Data Dumping
    if "LIMIT" not in cleaned_query:
        query += " LIMIT 20"

    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(query)
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            return "No results found."
        
        # Format results nicely
        results = f"🔍 Query Result ({len(rows)} rows):\n"
        columns = rows[0].keys()
        results += " | ".join(columns) + "\n"
        results += "-" * 50 + "\n"
        
        for row in rows:
            row_str = " | ".join(str(row[col]) for col in columns)
            results += row_str + "\n"
            
        return results

    except Exception as e:
        return f"❌ SQL Error: {str(e)}"

# --- TOOL 2: ADD (Safe Structured Input) ---
@mcp.tool()
def add_expense(amount: float, main_category: str, sub_category: str, description: str, date: str = None) -> str:
    """Records a new expense. Date format: YYYY-MM-DD."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Default to Today if no date provided
    if not date: 
        date = datetime.now().strftime("%Y-%m-%d")
        
    c.execute("INSERT INTO expenses (amount, main_category, sub_category, description, date) VALUES (?, ?, ?, ?, ?)", 
              (amount, main_category, sub_category, description, date))
    eid = c.lastrowid
    conn.commit()
    conn.close()
    return f"✅ Saved ID #{eid}: ₹{amount} for {description} on {date}"

# --- TOOL 3: DELETE (Requires ID) ---
@mcp.tool()
def delete_expense(expense_id: int) -> str:
    """Permanently deletes an expense by its numeric ID."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if exists first
    c.execute("SELECT * FROM expenses WHERE id=?", (expense_id,))
    if not c.fetchone(): 
        conn.close()
        return "❌ Error: ID not found."
        
    c.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()
    return f"🗑️ Deleted Expense ID #{expense_id}"

# --- TOOL 4: UPDATE (Requires ID) ---
@mcp.tool()
def update_expense(expense_id: int, field: str, new_value: str) -> str:
    """Updates a field (amount, description, date) for a specific ID."""
    allowed_fields = ['amount', 'description', 'main_category', 'sub_category', 'date']
    if field not in allowed_fields:
        return f"❌ Error: Cannot edit '{field}'. Allowed: {allowed_fields}"

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE expenses SET {field} = ? WHERE id = ?", (new_value, expense_id))
    conn.commit()
    conn.close()
    return f"✅ Updated ID #{expense_id}: {field} -> {new_value}"

if __name__ == "__main__":
    mcp.run()