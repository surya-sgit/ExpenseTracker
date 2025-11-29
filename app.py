import streamlit as st
import asyncio
import sys
import os
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
st.set_page_config(page_title="Financial Analytics", layout="wide")

# Professional Styling
st.markdown("""
<style>
    header {visibility: hidden;}
    .main {background-color: #0E1117;}
    div[data-testid="stMetric"] {
        background-color: #262730; 
        border: 1px solid #41424C; 
        border-radius: 5px; 
        padding: 15px;
    }
    .stChatInput {border-radius: 10px;}
</style>
""", unsafe_allow_html=True)

load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# Update this with your specific FastMCP URL (ensure it ends in /sse)
SERVER_URL = "https://expensetracker-backend-cjxj.onrender.com/sse" 

if not API_KEY or not DATABASE_URL:
    st.error("Critical Error: Missing configuration secrets (GOOGLE_API_KEY or DATABASE_URL).")
    st.stop()

# Load Categories
try:
    with open("categories.json", "r") as f:
        CATEGORIES_STR = json.dumps(json.load(f), indent=2)
except:
    st.error("Configuration Error: categories.json file not found.")
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
    st.title("Dashboard")
    df = load_data()
    
    if not df.empty:
        col1, col2 = st.columns(2)
        col1.metric("Total Spend", f"INR {df['amount'].sum():,.2f}")
        col2.metric("Transactions", len(df))
        
        st.markdown("---")
        
        # Charts
        st.subheader("Category Breakdown")
        fig = px.pie(df, values='amount', names='main_category', hole=0.4, 
                     color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), height=250, paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig)

        # Recent Activity Table
        st.subheader("Recent Activity")
        mini_df = df[['date', 'amount', 'description']].head(5)
        mini_df['date'] = mini_df['date'].dt.strftime('%b %d')
        
        st.dataframe(
            mini_df, 
            hide_index=True, 
            use_container_width=True,
            column_config={
                "date": "Date",
                "amount": st.column_config.NumberColumn("Amount", format="INR %.2f"),
                "description": "Description"
            }
        )
    
    if st.button("Refresh Data"): 
        st.rerun()

# --- CHAT INTERFACE ---
st.title("Financial Assistant")

if "messages" not in st.session_state: 
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): 
        st.markdown(msg["content"])

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
            You are a Financial Analyst. DATE: {today} | CURRENCY: INR
            1. MEMORY: Utilize context from previous messages.
            2. READ: Use `analyze_database` for data retrieval (SQL).
            3. WRITE: Use `add_expense` immediately if details are provided.
            4. EDIT: Search for the record first, then use the ID to update.
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

if prompt := st.chat_input("Enter command (e.g., 'Log 500 INR for lunch')"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): 
        st.markdown(prompt)
    
    with st.chat_message("assistant"):
        with st.spinner("Processing request..."):
            try:
                res = asyncio.run(run_agent(prompt))
                st.markdown(res)
                st.session_state.messages.append({"role": "assistant", "content": res})
                st.rerun()
            except Exception as e:
                st.error(f"Connection Error: {e}. Verify Backend Status.")