"""
project_2: A very basic calculator MCP server.

WHAT THIS FILE IS
-----------------
This is an MCP *server*. On its own it does nothing visible: it waits for an
MCP *client* (living inside a *host* app like Claude Code or Claude Desktop)
to start it, ask what tools it has, and then call those tools.

The flow looks like this:

    Host (Claude Code)  --spawns-->  this script (python main.py)
         |                                   |
         |  <---- JSON-RPC over stdin/stdout ---->
         |
    1. "initialize"   -> server replies with its name + capabilities
    2. "tools/list"   -> server replies with every @mcp.tool() below,
                         including a JSON schema built from the type hints
    3. "tools/call"   -> server runs the Python function and returns the result

The LLM never runs this code directly. It only sees the tool names,
descriptions (docstrings) and input schemas, then asks the host to call a tool.
The host forwards that request here, and our return value goes back to the LLM.

HOW TO RUN IT
-------------
    pip install "mcp[cli]"          # the official MCP Python SDK
    python main.py                  # starts the server on stdio (it will just wait)

Normally you do NOT run it by hand. The host launches it for you (see .mcp.json
at the repo root).
"""

import cmath  # math for complex numbers (needed when a quadratic has no real roots)
import math   # regular math functions, like sqrt

# MCPServer is the high-level API in the official SDK (v2+). It hides the
# JSON-RPC plumbing so we only write normal Python functions.
# (In SDK v1 this class was called FastMCP, which is why older tutorials use
# "from mcp.server.fastmcp import FastMCP".)
from mcp.server.mcpserver import MCPServer

# Create the server. The name is what the host shows in its list of servers.
mcp = MCPServer("calculator")


# -----------------------------------------------------------------------------
# TOOLS
# -----------------------------------------------------------------------------
# @mcp.tool() registers the function as an MCP tool. MCPServer reads:
#   - the function name       -> the tool's name ("add", "divide", ...)
#   - the docstring           -> the tool's description (the LLM reads this to
#                                decide WHEN to use the tool, so make it clear)
#   - the type hints          -> the tool's JSON input schema (so the client
#                                knows a and b must be numbers)
#   - the return type         -> the tool's output
#
# If a tool raises an exception, MCPServer catches it and sends it back as a tool
# error (isError: true) instead of crashing the server. The LLM then sees the
# error message and can explain it or try again.


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers and return a + b."""
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    """Subtract b from a and return a - b."""
    return a - b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers and return a * b."""
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide a by b and return a / b. Fails if b is zero."""
    if b == 0:
        # A clear message here is what the LLM will see, so be specific.
        raise ValueError("Cannot divide by zero.")
    return a / b


@mcp.tool()
def sqrt(x: float) -> float:
    """Return the square root of x. x must be zero or positive."""
    if x < 0:
        raise ValueError("Cannot take the square root of a negative number.")
    return math.sqrt(x)


@mcp.tool()
def solve_quadratic(a: float, b: float, c: float) -> dict:
    """
    Solve the quadratic equation a*x^2 + b*x + c = 0.

    Returns the discriminant (b^2 - 4ac) and the roots. Real roots are numbers.
    Complex roots are strings like "-1.0 + 2.0i".
    """
    # If a is 0 there is no x^2 term, so this is not a quadratic.
    if a == 0:
        raise ValueError("'a' must not be zero, or the equation is not quadratic.")

    # The discriminant tells us what kind of roots we get:
    #   > 0  -> two different real roots
    #   = 0  -> one repeated real root
    #   < 0  -> two complex roots
    discriminant = b**2 - 4 * a * c

    if discriminant >= 0:
        # Quadratic formula: x = (-b ± sqrt(discriminant)) / 2a
        root = math.sqrt(discriminant)
        x1 = (-b + root) / (2 * a)
        x2 = (-b - root) / (2 * a)
        # When discriminant == 0 both roots are equal, so only return one.
        roots = [x1] if discriminant == 0 else [x1, x2]
    else:
        # cmath.sqrt handles negative numbers by returning a complex number.
        root = cmath.sqrt(discriminant)
        z1 = (-b + root) / (2 * a)
        z2 = (-b - root) / (2 * a)
        # Complex numbers are not valid JSON, so turn them into readable strings.
        roots = [
            f"{z.real} {'+' if z.imag >= 0 else '-'} {abs(z.imag)}i" for z in (z1, z2)
        ]

    # Returning a dict gives the LLM structured, labeled output.
    return {"discriminant": discriminant, "roots": roots}


# -----------------------------------------------------------------------------
# ENTRY POINT
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # transport="stdio" means we talk to the host over stdin/stdout.
    # IMPORTANT: because stdout carries the protocol messages, never use
    # print() in a stdio server. It would corrupt the JSON-RPC stream.
    # Log to stderr instead if you need debug output.
    mcp.run(transport="stdio")
