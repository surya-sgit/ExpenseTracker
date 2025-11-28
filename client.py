import asyncio
import sys
import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 1. Load Secrets
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    print("❌ Error: GOOGLE_API_KEY not found in .env")
    sys.exit(1)

# 2. Load Categories
try:
    with open("categories.json", "r") as f:
        CATEGORIES_DATA = json.load(f)
        # Convert JSON to a string so we can feed it to the AI
        CATEGORIES_STR = json.dumps(CATEGORIES_DATA, indent=2)
except FileNotFoundError:
    print("❌ Error: categories.json file not found!")
    sys.exit(1)

async def run():
    # Connect to Server
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Get Tools
            tools = await session.list_tools()
            
            # Convert Tools for Gemini
            function_declarations = []
            for t in tools.tools:
                function_declarations.append(
                    types.FunctionDeclaration(
                        name=t.name,
                        description=t.description,
                        parameters=t.inputSchema
                    )
                )
            gemini_tools = [types.Tool(function_declarations=function_declarations)]

            # Setup Gemini
            client = genai.Client(api_key=API_KEY)
            
            # --- THE BRAIN UPGRADE ---
            # We inject your exact categories into the prompt.
            system_instruction = f"""
            You are an intelligent accountant. 
            
            RULES:
            1. You have access to a database tool 'add_expense'.
            2. When the user logs an expense, you MUST categorize it strictly using the JSON list below.
            3. Find the best matching 'main_category' and 'sub_category'.
            4. If uncertain, use 'misc' -> 'uncategorized'.
            
            VALID CATEGORIES LIST:
            {CATEGORIES_STR}
            """

            chat = client.chats.create(
                model="gemini-2.0-flash",
                config=types.GenerateContentConfig(
                    tools=gemini_tools,
                    system_instruction=system_instruction
                )
            )

            print("\n💰 Expense Tracker Pro (Loaded categories.json)")
            print("Type 'quit' to exit.\n")
            
            while True:
                user_input = input("You: ")
                if user_input.lower() in ["quit", "exit"]:
                    break

                # Send message
                response = chat.send_message(user_input)

                # Agentic Loop
                while response.function_calls:
                    print(f"🤖 Processing {len(response.function_calls)} actions...")
                    api_response_parts = []
                    
                    for call in response.function_calls:
                        # Print what category the AI picked (for debugging)
                        if call.name == "add_expense":
                            args = call.args
                            print(f"   > Categorized as: {args.get('main_category')} / {args.get('sub_category')}")

                        # Execute
                        result = await session.call_tool(call.name, arguments=call.args)
                        
                        api_response_parts.append(
                            types.Part.from_function_response(
                                name=call.name,
                                response={"result": result.content[0].text}
                            )
                        )
                    
                    # Return results
                    response = chat.send_message(api_response_parts)
                
                print(f"Assistant: {response.text}\n")

if __name__ == "__main__":
    asyncio.run(run())