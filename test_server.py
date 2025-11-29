from fastmcp import FastMCP

# Initialize Server
mcp = FastMCP("Test Server")

@mcp.tool()
def say_hello() -> str:
    return "Hello! The server is working."

if __name__ == "__main__":
    mcp.run()