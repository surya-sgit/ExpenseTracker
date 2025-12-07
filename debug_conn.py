import asyncio
from mcp.client.sse import sse_client

# ⚠️ REPLACE THIS with your actual Render URL
# Make sure it starts with https:// and ends with /sse
SERVER_URL = "https://expensetracker-backend-cjxj.onrender.com/sse" 

async def test_connection():
    print(f"🔌 Connecting to: {SERVER_URL}")
    print("⏳ Waiting for handshake (this allows us to check for timeouts)...")
    
    try:
        # We try to connect. If this works, the problem is Streamlit Cloud.
        # If this fails, the problem is the Render Server Config.
        async with sse_client(SERVER_URL) as (read, write):
            print("✅ SUCCESS! Connected to the server.")
            print("The Backend is working perfectly.")
            
    except Exception as e:
        print("\n❌ CONNECTION FAILED")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Details: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())