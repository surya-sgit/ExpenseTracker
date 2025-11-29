import streamlit as st
import asyncio
import sys
import os
import subprocess 

# --- FORCE INSTALL (The Cheat Code) ---
try:
    import psycopg2
except ImportError:
    # This forces Streamlit to install the missing library RIGHT NOW
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    import psycopg2

# ... continue with your other imports ...
import json
import datetime
import pandas as pd
import plotly.express as px
import psycopg2
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession
from mcp.client.sse import sse_client

# --- CONFIG ---
st.set_page_config(page_title="FinAI Pro", layout="wide")

# Styling
st.markdown("""
<style>
    header {visibility: hidden;}
    .main {background-color: #0E1117;}
    div[data-testid="stMetric"] {background-color: #262730; border: 1px solid #41424C; border-radius: 5px; padding: 15px;}
    .stChatInput {border-radius: 10px;}
</style>
""", unsafe_allow_html=True)

load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# ⚠️ ENSURE THIS IS YOUR RENDER URL (ending in /sse)
SERVER_URL = "https://expensetracker-backend-cjxj.onrender.com/sse" 

if not API_KEY or not DATABASE_URL:
    st.error("Critical Error: Missing secrets.")
    st.stop()

# Load Categories
try:
    with open("categories.json", "r") as f:
        CATEGORIES_STR = json.dumps(json.load(f), indent=2)
except:
    st.error("Error: categories.json not found. Please ensure the file is in the root folder.")
    st.stop()

# --- SIDEBAR ---
def load_data():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        df = pd.read_sql("SELECT * FROM expenses ORDER BY date DESC", conn)
        conn.close()
        df['date'] = pd.to_datetime(df['date'])
        return df
    except:
        return pd.DataFrame()

with st.sidebar:
    st.title("Dashboard")
    df = load_data()
    
    if not df.empty:
        col1, col2 = st.columns(2)
        col1.metric("Spent", f"₹{df['amount'].sum():,.0f}")
        col2.metric("Txns", len(df))
        st.markdown("---")
        fig = px.pie(df, values='amount', names='main_category', hole=0.4, 
                     color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), height=250, paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig)
        
    if st.button("Refresh Data"): st.rerun()

# --- CHAT ---
st.title("Financial Assistant")

if "messages" not in st.session_state: st.session_state.messages = []
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

async def run_agent(user_prompt):
    async with sse_client(SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            tools = await session.list_tools()
            f_decls = [types.FunctionDeclaration(name=t.name, description=t.description, parameters=t.inputSchema) for t in tools.tools]
            gemini_tools = [types.Tool(function_declarations=f_decls)]

            client = genai.Client(api_key=API_KEY)
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # --- THE FIX: STRICTER RULES ---
            sys_instr = f"""
            You are a Financial Data Analyst. DATE: {today} | CURRENCY: INR
            
            CRITICAL RULES:
            1. **NEVER ASK CLARIFYING QUESTIONS.** If the category is unclear, GUESS the best match.
            2. If you absolutely cannot guess, use 'misc' -> 'uncategorized'.
            3. ACTION: Call `add_expense` IMMEDIATELY when given an amount and item.
            4. READ: Use `analyze_database` for queries.
            
            VALID CATEGORIES: {CATEGORIES_STR}
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

if prompt := st.chat_input("Ex: 'Add 500rs for lunch'"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Processing..."):
            try:
                res = asyncio.run(run_agent(prompt))
                st.markdown(res)
                st.session_state.messages.append({"role": "assistant", "content": res})
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")