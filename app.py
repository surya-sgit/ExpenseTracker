import streamlit as st
import asyncio
import sys
import os
import json
import datetime
import pandas as pd
import sqlite3
import plotly.express as px
import psycopg2
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession
from mcp.client.sse import sse_client # <--- NEW: For Remote Connection

# --- CONFIG ---
st.set_page_config(page_title="FinAI Pro", layout="wide", page_icon="💳")
st.markdown("""
<style>
    header {visibility: hidden;}
    .main {background-color: #0E1117;}
    div[data-testid="stMetric"] {background-color: #262730; border: 1px solid #41424C; border-radius: 10px; padding: 10px;}
    .stChatInput {border-radius: 20px;}
</style>
""", unsafe_allow_html=True)

load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# ⚠️ REPLACE THIS WITH YOUR DEPLOYED BACKEND URL FROM FASTMCP
SERVER_URL = "https://your-backend-name.fastmcp.cloud/sse" 

if not API_KEY or not DATABASE_URL:
    st.error("❌ Secrets missing (GOOGLE_API_KEY or DATABASE_URL).")
    st.stop()

# Load Categories
try:
    with open("categories.json", "r") as f:
        CATEGORIES_STR = json.dumps(json.load(f), indent=2)
except:
    st.error("❌ categories.json missing!")
    st.stop()

# --- SIDEBAR (Direct DB Connection) ---
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
    st.title("💳 Dashboard")
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

        st.subheader("Recent")
        mini_df = df[['date', 'amount', 'description']].head(5)
        mini_df['date'] = mini_df['date'].dt.strftime('%b %d')
        st.dataframe(mini_df, hide_index=True, use_container_width=True)
    
    if st.button("Refresh"): st.rerun()

# --- CHAT INTERFACE ---
st.title("💬 Financial Assistant")

if "messages" not in st.session_state: st.session_state.messages = []
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

async def run_agent(user_prompt):
    # CONNECT TO REMOTE SERVER (SSE)
    async with sse_client(SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            tools = await session.list_tools()
            f_decls = [types.FunctionDeclaration(name=t.name, description=t.description, parameters=t.inputSchema) for t in tools.tools]
            gemini_tools = [types.Tool(function_declarations=f_decls)]

            client = genai.Client(api_key=API_KEY)
            
            # Context
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            sys_instr = f"""
            You are a Financial Analyst. TODAY: {today} | CURRENCY: INR
            1. MEMORY: Remember past context.
            2. READ: Use `analyze_database` (SQL).
            3. WRITE: Use `add_expense` immediately if details provided.
            4. EDIT: Search first, then use ID.
            CATEGORIES: {CATEGORIES_STR}
            """

            # Memory Injection
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
                st.error(f"Connection Error: {e}. Check if Backend is running.")