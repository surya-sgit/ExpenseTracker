import streamlit as st
import asyncio
import sys
import os
import json
import datetime
import pandas as pd
import sqlite3
import plotly.express as px
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --- 1. PAGE CONFIG & STYLING ---
st.set_page_config(page_title="FinAI Pro", layout="wide", page_icon="💳")

# Custom CSS for a modern "Glassmorphism" look
st.markdown("""
<style>
    header {visibility: hidden;}
    .main {background-color: #0E1117;}
    div[data-testid="stMetric"] {
        background-color: #262730;
        border: 1px solid #41424C;
        padding: 15px;
        border-radius: 10px;
        color: white;
    }
    .stChatInput {border-radius: 20px;}
</style>
""", unsafe_allow_html=True)

# --- 2. SETUP ---
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    st.error("❌ Critical Error: GOOGLE_API_KEY not found.")
    st.stop()

# Load Categories
try:
    with open("categories.json", "r") as f:
        CATEGORIES_DATA = json.load(f)
        CATEGORIES_STR = json.dumps(CATEGORIES_DATA, indent=2)
except FileNotFoundError:
    st.error("❌ categories.json missing!")
    st.stop()

# --- 3. DATA LOADING FUNCTION ---
def load_data():
    try:
        conn = sqlite3.connect("expenses.db")
        df = pd.read_sql_query("SELECT id, date, amount, main_category, sub_category, description FROM expenses ORDER BY date DESC", conn)
        conn.close()
        df['date'] = pd.to_datetime(df['date'])
        return df
    except:
        return pd.DataFrame()

# --- 4. SIDEBAR DASHBOARD ---
with st.sidebar:
    st.title("💳 FinAI Dashboard")
    
    df = load_data()
    
    if not df.empty:
        # --- METRICS ---
        total_spend = df['amount'].sum()
        transaction_count = len(df)
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Spent", f"₹{total_spend:,.0f}")
        with col2:
            st.metric("Transactions", transaction_count)
            
        st.markdown("---")
        
        # --- SPENDING CHART (FIXED LABELS) ---
        st.subheader("🍩 Spending by Category")
        if total_spend > 0:
            fig = px.pie(df, values='amount', names='main_category', hole=0.4, 
                         color_discrete_sequence=px.colors.qualitative.Pastel)
            
            # FIX: Show Labels + Percent inside the chart
            fig.update_traces(textposition='inside', textinfo='percent+label')
            
            fig.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=250, paper_bgcolor="rgba(0,0,0,0)")
            
            # FIX: Removed deprecated parameter
            st.plotly_chart(fig)

        # --- RECENT TRANSACTIONS (FIXED WIDTH) ---
        st.subheader("🕒 Recent Activity")
        mini_df = df[['date', 'amount', 'description']].head(5)
        mini_df['date'] = mini_df['date'].dt.strftime('%b %d')
        
        st.dataframe(
            mini_df, 
            hide_index=True, 
            column_config={
                "date": "Date",
                "amount": st.column_config.NumberColumn("₹", format="₹%d"),
                "description": "Item"
            },
            # FIX: Replaced use_container_width with default behavior (Streamlit now auto-stretches mostly)
            # If you want to force it, use width=None or remove the arg entirely.
        )
        
        st.caption(f"💡 ID #1 is the newest. ID #{df['id'].max()} is the oldest.")
    else:
        st.info("No data yet. Chat to add expenses!")

    # Button usually still supports use_container_width, but if it warns, remove it.
    if st.button("🔄 Refresh Dashboard"):
        st.rerun()

# --- 5. MAIN CHAT INTERFACE ---
st.title("💬 Financial Assistant")
st.markdown("Ask me to log expenses, analyze trends, or edit records.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- 6. INTELLIGENT AGENT ---
async def run_agent(user_prompt):
    server_params = StdioServerParameters(command=sys.executable, args=["server.py"])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            tools = await session.list_tools()
            function_declarations = []
            for t in tools.tools:
                function_declarations.append(types.FunctionDeclaration(
                    name=t.name, description=t.description, parameters=t.inputSchema))
            gemini_tools = [types.Tool(function_declarations=function_declarations)]

            client = genai.Client(api_key=API_KEY)
            
            now = datetime.datetime.now()
            current_date_str = now.strftime("%Y-%m-%d")
            
            system_instruction = f"""
            You are a Secure Financial Data Analyst with MEMORY.
            TODAY: {current_date_str} | CURRENCY: INR (₹)
            
            BEHAVIOR:
            1. MEMORY: Remember previous turns.
            2. ANALYSIS: Use `analyze_database` for reading.
            3. ACTION: If user gives Amount + Desc, call `add_expense` IMMEDIATELY.
            4. CATEGORIES: Map strictly to the list below.
            
            CATEGORIES: {CATEGORIES_STR}
            """

            chat_history = []
            for msg in st.session_state.messages[:-1]:
                role = "model" if msg["role"] == "assistant" else "user"
                chat_history.append(types.Content(
                    role=role, parts=[types.Part.from_text(text=str(msg["content"]))]))

            chat = client.chats.create(
                model="gemini-2.0-flash",
                config=types.GenerateContentConfig(
                    tools=gemini_tools, 
                    system_instruction=system_instruction),
                history=chat_history
            )

            response = chat.send_message(user_prompt)

            while response.function_calls:
                api_response_parts = []
                for call in response.function_calls:
                    result = await session.call_tool(call.name, arguments=call.args)
                    api_response_parts.append(types.Part.from_function_response(
                        name=call.name, response={"result": result.content[0].text}))
                response = chat.send_message(api_response_parts)

            return response.text

# --- 7. INPUT ---
if prompt := st.chat_input("Ex: 'Add 150rs for coffee', 'Show total spending', 'Delete ID 5'"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response_text = asyncio.run(run_agent(prompt))
                st.markdown(response_text)
                st.session_state.messages.append({"role": "assistant", "content": response_text})
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")