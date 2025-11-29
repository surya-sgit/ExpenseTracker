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

# --- CONFIGURATION ---
st.set_page_config(page_title="Financial Analytics", layout="wide")
load_dotenv()

# --- CSS STYLING ---
st.markdown("""
<style>
    .stButton>button {width: 100%; border-radius: 4px;}
    div[data-testid="stMetric"] {
        background-color: #262730; 
        border: 1px solid #4a4a4a;
        border-radius: 4px; 
        padding: 10px;
    }
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# --- ENVIRONMENT VARIABLES ---
API_KEY = os.getenv("GOOGLE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
# UPDATE THIS WITH YOUR RENDER URL
SERVER_URL = "https://expensetracker-backend-cjxj.onrender.com/sse" 

if not API_KEY or not DATABASE_URL:
    st.error("Configuration Error: Missing Secrets.")
    st.stop()

# --- SESSION MANAGEMENT ---
if "user_id" not in st.session_state: st.session_state.user_id = None
if "username" not in st.session_state: st.session_state.username = None
if "messages" not in st.session_state: st.session_state.messages = []

# --- AUTHENTICATION HELPERS ---
def login_user(username, password):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
        user = c.fetchone()
        conn.close()
        
        if user and bcrypt.checkpw(password.encode('utf-8'), bytes(user[1])):
            return user[0] 
    except Exception as e:
        st.error(f"Database connection error: {e}")
    return None

def register_user_direct(username, password):
    try:
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        conn = psycopg2.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, hashed))
        conn.commit()
        conn.close()
        return True
    except:
        return False

# ==========================================
# AUTHENTICATION VIEW
# ==========================================
if not st.session_state.user_id:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("Secure Login")
        tab1, tab2 = st.tabs(["Login", "Register"])
        
        with tab1:
            l_user = st.text_input("Username", key="l_u")
            l_pass = st.text_input("Password", type="password", key="l_p")
            if st.button("Log In"):
                uid = login_user(l_user, l_pass)
                if uid:
                    st.session_state.user_id = uid
                    st.session_state.username = l_user
                    st.rerun()
                else:
                    st.error("Invalid credentials.")
        
        with tab2:
            r_user = st.text_input("New Username", key="r_u")
            r_pass = st.text_input("New Password", type="password", key="r_p")
            if st.button("Create Account"):
                if register_user_direct(r_user, r_pass):
                    st.success("Account created successfully. Please log in.")
                else:
                    st.error("Username already exists.")
    st.stop() 

# ==========================================
# MAIN DASHBOARD VIEW
# ==========================================

# Load Categories
try:
    with open("categories.json", "r") as f:
        CATEGORIES_STR = json.dumps(json.load(f), indent=2)
except:
    CATEGORIES_STR = "General, Food, Transport, Utilities"

# Sidebar
with st.sidebar:
    st.write(f"User: **{st.session_state.username}**")
    if st.button("Log Out"):
        st.session_state.user_id = None
        st.rerun()
    
    st.markdown("---")
    
    conn = psycopg2.connect(DATABASE_URL)
    df = pd.read_sql("SELECT * FROM expenses WHERE user_id = %s ORDER BY date DESC", conn, params=(st.session_state.user_id,))
    conn.close()
    
    if not df.empty:
        st.metric("Total Expenditure", f"INR {df['amount'].sum():,.2f}")
        
        st.subheader("Distribution")
        fig = px.pie(df, values='amount', names='main_category', hole=0.4,
                     color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), height=250, paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig)
    else:
        st.info("No data available.")

# Chat Interface
st.title("Financial Analytics Assistant")

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
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # System Prompt with User Context
            sys_instr = f"""
            You are a Financial Data Analyst acting for User ID: {uid}.
            DATE: {today} | CURRENCY: INR
            
            OPERATIONAL RULES:
            1. DATA ACCESS: Use `get_user_data(user_id={uid})`. Do not assume data exists.
            2. DATA ENTRY: Use `add_expense(user_id={uid}, ...)`.
            3. DATA REMOVAL: Use `delete_expense(user_id={uid}, ...)`.
            4. CATEGORIZATION: Map inputs strictly to the provided category list.
            
            CATEGORY LIST:
            {CATEGORIES_STR}
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

if prompt := st.chat_input("Enter command (e.g., 'Log 500 INR for lunch')"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Processing..."):
            try:
                res = asyncio.run(run_agent(prompt, st.session_state.user_id))
                st.markdown(res)
                st.session_state.messages.append({"role": "assistant", "content": res})
                st.rerun()
            except Exception as e:
                st.error(f"System Error: {e}")