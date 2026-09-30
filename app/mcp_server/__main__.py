"""python -m app.mcp_server [--demo]: o servidor MCP rodando pelo código (o executável usa `Tabimoney.exe mcp`)."""
import sys

from app.mcp_server import servidor

if __name__ == "__main__":
    servidor.main(demo="--demo" in sys.argv[1:])
