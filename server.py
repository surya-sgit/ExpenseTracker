import os
import psycopg2
import bcrypt
from psycopg2.extras import RealDictCursor
from datetime import datetime
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

# Initialize Server
mcp = FastMCP("Expense Tracker Multi-User")
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("Configuration Error: DATABASE_URL is missing.")
    return psycopg2.connect(DATABASE_URL)

# --- DATABASE INITIALIZATION ---
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. Create Users Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash BYTEA NOT NULL
        )
    ''')
    
    # 2. Create Expenses Table with Foreign Key
    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            amount REAL,
            main_category TEXT,
            sub_category TEXT,
            description TEXT,
            date DATE DEFAULT CURRENT_DATE
        )
    ''')
    
    # 3. Migration: Ensure user_id exists for existing databases
    try:
        c.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)")
    except Exception:
        pass 

    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"Database Initialization Error: {e}")

# --- AUTHENTICATION TOOLS ---

@mcp.tool()
def register_user(username: str, password: str) -> str:
    """Registers a new user. Returns status message."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if username exists
    c.execute("SELECT id FROM users WHERE username = %s", (username,))
    if c.fetchone():
        conn.close()
        return "Error: Username already taken."
        
    # Hash password securely
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    
    try:
        c.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, hashed))
        conn.commit()
        conn.close()
        return "Success: User registered. Please log in."
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def login_user(username: str, password: str) -> str:
    """Verifies credentials. Returns user ID if successful."""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
    user = c.fetchone()
    conn.close()
    
    if not user:
        return "Error: User not found."
    
    # Verify hash
    stored_hash = bytes(user[1])
    if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
        return f"ID: {user[0]}"
    else:
        return "Error: Invalid password."

# --- DATA TOOLS (Scoped to User ID) ---

@mcp.tool()
def get_user_data(user_id: int) -> str:
    """
    Fetches expenses strictly for the specified user ID.
    """
    conn = get_db_connection()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM expenses WHERE user_id = %s ORDER BY date DESC LIMIT 50", (user_id,))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return "No expenses found for this user."
    
    # Format as pipe-delimited text for AI analysis
    result = "id | date | amount | category | description\n"
    result += "-" * 50 + "\n"
    for r in rows:
        result += f"{r['id']} | {r['date']} | {r['amount']} | {r['main_category']} | {r['description']}\n"
    return result

@mcp.tool()
def add_expense(user_id: int, amount: float, main_category: str, sub_category: str, description: str, date: str = None) -> str:
    """Records an expense linked to a specific user ID."""
    conn = get_db_connection()
    c = conn.cursor()
    if not date: 
        date = datetime.now().strftime("%Y-%m-%d")
    
    c.execute("INSERT INTO expenses (user_id, amount, main_category, sub_category, description, date) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", 
              (user_id, amount, main_category, sub_category, description, date))
    eid = c.fetchone()[0]
    conn.commit()
    conn.close()
    return f"Success: Saved ID #{eid}"

@mcp.tool()
def delete_expense(user_id: int, expense_id: int) -> str:
    """Deletes an expense ONLY if it belongs to the authenticated user."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Delete with user_id check to prevent unauthorized deletion
    c.execute("DELETE FROM expenses WHERE id = %s AND user_id = %s RETURNING id", (expense_id, user_id))
    deleted = c.fetchone()
    conn.commit()
    conn.close()
    
    if deleted:
        return f"Success: Deleted ID #{expense_id}"
    else:
        return "Error: ID not found or permission denied."

if __name__ == "__main__":
    mcp.run()