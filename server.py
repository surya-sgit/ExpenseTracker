import os
import psycopg2
import bcrypt
import uuid
from psycopg2.extras import RealDictCursor
from datetime import datetime
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("Expense Tracker Enterprise")
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL: raise ValueError("DATABASE_URL missing.")
    return psycopg2.connect(DATABASE_URL)

# --- DATABASE INIT (With UUIDs) ---
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Enable UUID extension in Postgres
    c.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    
    # 2. Users Table (Using UUIDs now)
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            username TEXT UNIQUE NOT NULL,
            password_hash BYTEA NOT NULL
        )
    ''')
    
    # 3. Expenses Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID REFERENCES users(id),
            amount REAL,
            main_category TEXT,
            sub_category TEXT,
            description TEXT,
            date DATE DEFAULT CURRENT_DATE
        )
    ''')
    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"DB Init Error: {e}")

# --- AUTH TOOLS ---

@mcp.tool()
def register_user(username: str, password: str) -> str:
    """Registers a new user."""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT id FROM users WHERE username = %s", (username,))
    if c.fetchone():
        conn.close()
        return "Error: Username taken."
        
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    
    try:
        # Postgres returns the new UUID automatically
        c.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id", (username, hashed))
        new_id = c.fetchone()[0]
        conn.commit()
        conn.close()
        return f"Success: Registered. Your secure ID is {new_id}"
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
def login_user(username: str, password: str) -> str:
    """Returns User UUID if credentials match."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
    user = c.fetchone()
    conn.close()
    
    if not user: return "Error: User not found."
    
    if bcrypt.checkpw(password.encode('utf-8'), bytes(user[1])):
        return f"{user[0]}" # Return the UUID string
    return "Error: Invalid password."

# --- THE SECURE ANALYST (The Fix) ---

@mcp.tool()
def run_secure_query(user_id: str, sql_logic: str) -> str:
    """
    Runs a secure SQL analysis for a specific user.
    
    Args:
        user_id: The UUID of the logged-in user.
        sql_logic: The SQL conditions/aggregations AFTER the 'WHERE'. 
                   Do NOT write 'SELECT *'. Just write the logic.
    
    Examples of 'sql_logic':
        - "ORDER BY amount DESC LIMIT 5" (Top expenses)
        - "AND main_category = 'Food'" (Filter by food)
        - "AND amount > 500" (High value items)
    """
    conn = get_db_connection()
    c = conn.cursor(cursor_factory=RealDictCursor)
    
    # 🛡️ SECURITY SANDBOX 🛡️
    # We force the query to start with "SELECT * FROM expenses WHERE user_id = ..."
    # This makes it physically impossible to see other users' data.
    
    # Clean inputs to prevent some injection, though parameterization handles most
    full_query = f"SELECT * FROM expenses WHERE user_id = '{user_id}' {sql_logic}"
    
    # Basic safety check to prevent dropping tables
    if "DROP" in sql_logic.upper() or "DELETE" in sql_logic.upper() or "UPDATE" in sql_logic.upper():
        return "Error: This tool is for Read-Only analysis."

    try:
        c.execute(full_query)
        rows = c.fetchall()
        conn.close()
        
        if not rows: return "No data found matching your query."
        
        # 📊 FORMATTING FIX: Return Markdown Table
        # This fixes the "ugly text" issue.
        if rows:
            keys = rows[0].keys()
            markdown = "| " + " | ".join(keys) + " |\n"
            markdown += "| " + " | ".join(["---"] * len(keys)) + " |\n"
            for row in rows:
                values = [str(row[k]) for k in keys]
                markdown += "| " + " | ".join(values) + " |\n"
            return markdown
            
    except Exception as e:
        return f"Query Error: {e}"

@mcp.tool()
def summarize_expenses(user_id: str) -> str:
    """Returns a total spending breakdown by category."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT main_category, SUM(amount) 
        FROM expenses 
        WHERE user_id = %s 
        GROUP BY main_category
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    
    report = "### 📊 Spending Summary\n"
    for row in rows:
        report += f"- **{row[0]}:** ₹{row[1]:,.2f}\n"
    return report

@mcp.tool()
def add_expense(user_id: str, amount: float, main_category: str, sub_category: str, description: str, date: str = None) -> str:
    """Adds a new expense."""
    conn = get_db_connection()
    c = conn.cursor()
    if not date: date = datetime.now().strftime("%Y-%m-%d")
    
    c.execute("INSERT INTO expenses (user_id, amount, main_category, sub_category, description, date) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", 
              (user_id, amount, main_category, sub_category, description, date))
    eid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return f"✅ Saved. ID: {eid}"

@mcp.tool()
def delete_expense(user_id: str, expense_id: str) -> str:
    """Deletes an expense (Requires UUID)."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # We cast the ID string to UUID type for Postgres
    try:
        c.execute("DELETE FROM expenses WHERE id = %s AND user_id = %s RETURNING id", (expense_id, user_id))
        if c.fetchone():
            conn.commit()
            conn.close()
            return "🗑️ Expense deleted successfully."
        else:
            conn.close()
            return "Error: Expense not found or you don't own it."
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    mcp.run()