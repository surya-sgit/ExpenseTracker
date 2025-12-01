import streamlit as st
import asyncio
import sys
import os
import json
import datetime
import pandas as pd
import plotly.express as px
import psycopg2
import bcrypt
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession
from mcp.client.sse import sse_client

# --- CONFIG ---
st.set_page_config(page_title="FinAI Enterprise", layout="wide", page_icon="🔐")
load_dotenv()

API_KEY = os.getenv("GOOGLE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
# ⚠️ UPDATE THIS URL AFTER DEPLOYING SERVER
SERVER_URL = "https://expensetracker-backend-cjxj.onrender.com/sse" 

# --- STYLING ---
st.markdown("""
<style>
    div[data-testid="stMetric"] {background-color: #262730; border-radius: 5px; padding: 10px;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# --- AUTH HELPERS (Frontend Local Check) ---
def login_user(username, password):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
        user = c.fetchone()
        conn.close()
        if user and bcrypt.checkpw(password.encode('utf-8'), bytes(user[1])):
            return str(user[0]) # Convert UUID to string
    except: pass
    return None

def register_user_direct(username, password):
    try:
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        conn = psycopg2.connect(DATABASE_URL)
        c = conn.cursor()
        # Postgres needs to know we want the UUID generated
        c.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, hashed))
        conn.commit()
        conn.close()
        return True
    except: return False

# --- SESSION ---
if "user_id" not in st.session_state: st.session_state.user_id = None
if "username" not in st.session_state: st.session_state.username = None
if "messages" not in st.session_state: st.session_state.messages = []

# --- LOGIN SCREEN ---
if not st.session_state.user_id:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("🔐 Enterprise Login")
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        with tab1:
            u = st.text_input("Username", key="l_u")
            p = st.text_input("Password", type="password", key="l_p")
            if st.button("Log In"):
                uid = login_user(u, p)
                if uid:
                    st.session_state.user_id = uid
                    st.session_state.username = u
                    st.rerun()
                else: st.error("Invalid credentials")
        with tab2:
            ru = st.text_input("New Username", key="r_u")
            rp = st.text_input("New Password", type="password", key="r_p")
            if st.button("Create Account"):
                if register_user_direct(ru, rp): st.success("Created! Login now.")
                else: st.error("Username taken.")
    st.stop()

# --- MAIN APP ---
try:
    with open("categories.json", "r") as f: CAT_STR = json.dumps(json.load(f))
except: CAT_STR = "General"

with st.sidebar:
    st.write(f"User: **{st.session_state.username}**")
    if st.button("Log Out"):
        st.session_state.user_id = None
        st.rerun()
    st.divider()
    
    # Load User Data (UUID aware)
    conn = psycopg2.connect(DATABASE_URL)
    df = pd.read_sql("SELECT * FROM expenses WHERE user_id = %s ORDER BY date DESC", conn, params=(st.session_state.user_id,))
    conn.close()
    
    if not df.empty:
        st.metric("Total Spend", f"₹{df['amount'].sum():,.0f}")
        fig = px.pie(df, values='amount', names='main_category', hole=0.4)
        st.plotly_chart(fig)

st.title("💬 Financial Analyst")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

async def run_agent(user_prompt, uid):
    async with sse_client(SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            tools = await session.list_tools()
            f_decls = [types.FunctionDeclaration(name=t.name, description=t.description, parameters=t.inputSchema) for t in tools.tools]
            gemini_tools = [types.Tool(function_declarations=f_decls)]
            client = genai.Client(api_key=API_KEY)
            
            # --- THE ANALYST PROMPT ---
            sys_instr = f"""
            You are an Expert Financial Analyst for User UUID: {uid}.
            CURRENCY: INR.
            
            YOUR TOOLS:
            1. `run_secure_query(user_id, sql_logic)`: 
               - Use this for complex questions (Highest, Lowest, Averages, Filtering).
               - The `sql_logic` is appended to: "SELECT * FROM expenses WHERE user_id = '{uid}' ..."
               - Ex: "Show highest expense" -> sql_logic="ORDER BY amount DESC LIMIT 1"
            
            2. `summarize_expenses(user_id)`: Use for "Spending breakdown" or "Summary".
            
            3. `add_expense`: Call immediately if details provided.
            
            4. `delete_expense`: Requires UUID. Search first to find it.
            
            FORMATTING:
            - The database returns MARKDOWN TABLES. Display them directly.
            - Do not ask clarifying questions. Guess the category from: {CAT_STR}
            """

            history = []
            for m in st.session_state.messages[:-1]:
                role = "model" if m["role"]=="assistant" else "user"
                history.append(types.Content(role=role, parts=[types.Part.from_text(text=str(m["content"]))]))

            chat = client.chats.create(model="gemini-2.0-flash", config=types.GenerateContentConfig(tools=gemini_tools, system_instruction=sys_instr), history=history)
            response = chat.send_message(user_prompt)

            while response.function_calls:
                parts = []
                for call in response.function_calls:
                    res = await session.call_tool(call.name, arguments=call.args)
                    parts.append(types.Part.from_function_response(name=call.name, response={"result": res.content[0].text}))
                response = chat.send_message(parts)
            return response.text

if prompt := st.chat_input("Ex: 'Show my highest expense'"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Analyzing..."):
            try:
                res = asyncio.run(run_agent(prompt, st.session_state.user_id))
                st.markdown(res)
                st.session_state.messages.append({"role": "assistant", "content": res})
                st.rerun()
            except Exception as e: st.error(f"Error: {e}")