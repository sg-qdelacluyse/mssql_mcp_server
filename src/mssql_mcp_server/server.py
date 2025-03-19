import asyncio
import logging
import os
import struct
import adal
import pyodbc
import pandas as pd
import io
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator
from pathlib import Path
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Resource, Tool, TextContent
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mssql_mcp_server")


class MicrosoftAzureSQL:
    """Class for interacting with Azure SQL database."""
    
    SQL_COPT_SS_ACCESS_TOKEN = 1256 
    BASE_AUTHORITY_URL = 'https://login.microsoftonline.com/'

    def __init__(self, server: str, database: str, client_id: str, client_secret: str, tenant_id: str) -> None:
        """Initializes the class with the necessary credentials."""
        self.server = server
        self.database = database
        self.__client_id = client_id
        self.__client_secret = client_secret
        self.__tenant_id = tenant_id
        self.__authority_url = f"{ self.BASE_AUTHORITY_URL }{ self.__tenant_id }/"
        self.__driver = '{ODBC Driver 17 for SQL Server}'
        self.__connection_string = f"Driver={ self.__driver };SERVER={ self.server };DATABASE={ self.database }"
        self.__connection = None


    def __convert_token(self,token: dict) -> bytes:
        """Converts a token obtained from Azure AD to a format usable by pyodbc."""
    
        #get bytes from token obtained
        tokenb = bytes(token["accessToken"], "UTF-8")
        exptoken = b''

        for i in tokenb:
            exptoken += bytes({i})
            exptoken += bytes(1)

        tokenstruct = struct.pack("=i", len(exptoken)) + exptoken

        return tokenstruct


    def connect(self) -> None:
        """Connects to the Azure SQL database."""

        logger.info(f"Connecting to {self.__connection_string}")

        context = adal.AuthenticationContext(
            self.__authority_url, api_version=None
        )

        token = context.acquire_token_with_client_credentials(
            resource='https://database.windows.net/',
            client_id=self.__client_id,
            client_secret=self.__client_secret
        )

        converted_token = self.__convert_token(token)

        self.__connection = pyodbc.connect(self.__connection_string, attrs_before = { self.SQL_COPT_SS_ACCESS_TOKEN:converted_token })
    

    def disconnect(self) -> None:
        """Disconnects from the Azure SQL database."""

        self.__connection.close()


    def execute_query(self, query: str, params: tuple = ()) -> list[dict]:
        """Executes a query on the Azure SQL database with optional parameters and returns a list of dictionaries with column names as keys."""

        cursor = self.__connection.cursor()
        cursor.execute(query, params)
        columns = [column[0] for column in cursor.description]
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))
        return results
    
    
    def execute_insert_instant(self, query: str, params: tuple = ()) -> None:
        """Executes an insert query on the Azure SQL database with optional parameters."""

        cursor = self.__connection.cursor()
        cursor.execute(query, params)
        self.__connection.commit()


    def execute_insert(self, query: str, params: tuple = ()) -> None:
        """Executes an insert query on the Azure SQL database with optional parameters."""

        cursor = self.__connection.cursor()
        cursor.execute(query, params)


    def commit(self) -> None:
        """Commits the transaction."""
        self.__connection.commit()


def get_db_config():
    """Get database configuration from environment variables and .env file."""
    # Try to load .env file if it exists
    env_path = Path(__file__).parent.parent.parent.joinpath('.env')
    logger.info(f"Loading configuration from {env_path}")
    if env_path.exists():
        load_dotenv(env_path)

    # Debug logging to see all environment variables
    logger.info("Available environment variables:")
    for key, value in os.environ.items():
        if any(azure_key in key.upper() for azure_key in ['AZURE', 'SQL']):
            logger.info(f"{key}: {'*' * len(value)}")  # Mask the actual values for security
    
    config = {
        "server": os.getenv("AZURE_SQL_HOST"),
        "database": os.getenv("AZURE_SQL_DATABASE"),
        "client_id": os.getenv("AZURE_CLIENT_ID"),
        "client_secret": os.getenv("AZURE_CLIENT_SECRET"),
        "tenant_id": os.getenv("AZURE_TENANT_ID")
    }
    
    # Debug logging to see which specific variables are missing
    missing_vars = [key for key, value in config.items() if not value]
    if missing_vars:
        logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.error("Please check environment variables or .env file:")
        logger.error("AZURE_SQL_HOST, AZURE_SQL_DATABASE, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, and AZURE_TENANT_ID are required")
        raise ValueError("Missing required database configuration")
    
    return config

def dict_list_to_csv(data: list[dict]) -> str:
    """Convert a list of flat dictionaries to CSV string.
    
    Args:
        data: List of dictionaries where each dictionary has the same keys
            and only contains simple values (no nested structures)
            
    Returns:
        String containing CSV data with headers
    """
    if not data:
        return ""
        

    # Convert list of dicts to DataFrame
    df = pd.DataFrame(data)
    
    # Write DataFrame to CSV string buffer
    output = io.StringIO()
    df.to_csv(output, index=False)
    
    return output.getvalue()

@dataclass
class ServerContext:
    db: MicrosoftAzureSQL

@asynccontextmanager
async def server_lifespan(server: Server) -> AsyncIterator[ServerContext]:
    """Manage server startup and shutdown lifecycle."""
    # Initialize resources on startup
    config = get_db_config()
    
    try:
        db = MicrosoftAzureSQL(
            server=config["server"],
            database=config["database"],
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            tenant_id=config["tenant_id"]
        )
        await db.connect()
        yield ServerContext(db=db)
    finally:
        # Clean up on shutdown
        await db.disconnect()


# Initialize server
server = Server("mssql_mcp_server", lifespan=server_lifespan)

# @app.list_resources()
# async def list_resources() -> list[Resource]:
#     """List MSSQL tables as resources."""
#     config = get_db_config()
#     try:
#         db = MicrosoftAzureSQL(
#             server=config["server"],
#             database=config["database"],
#             client_id=config["client_id"],
#             client_secret=config["client_secret"],
#             tenant_id=config["tenant_id"]
#         )
#         db.connect()
        
#         # Use INFORMATION_SCHEMA to list tables in MSSQL
#         results = db.execute_query("""
#             SELECT TABLE_NAME 
#             FROM INFORMATION_SCHEMA.TABLES 
#             WHERE TABLE_TYPE = 'BASE TABLE'
#                 AND TABLE_NAME LIKE '%DIM%';
#         """)
#         logger.info(f"Found tables: {results}")
        
#         resources = []
#         for table in results:
#             resources.append(
#                 Resource(
#                     uri=f"mssql://{table['TABLE_NAME']}/data",
#                     name=f"Table: {table['TABLE_NAME']}",
#                     mimeType="text/plain",
#                     description=f"Data in table: {table['TABLE_NAME']}"
#                 )
#             )
#         db.disconnect()
#         return resources
#     except Exception as e:
#         logger.error(f"Failed to list resources: {str(e)}")
#         return []

# @app.read_resource()
# async def read_resource(uri: AnyUrl) -> str:
#     """Read table contents."""
#     config = get_db_config()
#     uri_str = str(uri)
#     logger.info(f"Reading resource: {uri_str}")
    
#     if not uri_str.startswith("mssql://"):
#         raise ValueError(f"Invalid URI scheme: {uri_str}")
        
#     parts = uri_str[8:].split('/')
#     table = parts[0]
    
#     try:
#         db = MicrosoftAzureSQL(
#             server=config["server"],
#             database=config["database"],
#             client_id=config["client_id"],
#             client_secret=config["client_secret"],
#             tenant_id=config["tenant_id"]
#         )
#         db.connect()
        
#         results = db.execute_query(f"SELECT * FROM log.EDWAllTablesVw")
#         if not results:
#             return ""
            
#         # Convert results to CSV format
#         return dict_list_to_csv(results)
                
#     except Exception as e:
#         logger.error(f"Database error reading resource {uri}: {str(e)}")
#         raise RuntimeError(f"Database error: {str(e)}")
#     finally:
#         db.disconnect()

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Azure SQL tools."""
    logger.info("Listing tools...")
    return [
        Tool(
            name="get_tables",
            description="Get all tables in the Azure SQL server"
        ),
        Tool(
            name="execute_sql",
            description="Execute an SQL query on the Azure SQL server",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The SQL query to execute"
                    }
                },
                "required": ["query"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute SQL commands."""

    ctx = server.request_context
    db: MicrosoftAzureSQL = ctx.lifespan_context.db

    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    
    if name not in ["execute_sql", "get_tables"]:
        raise ValueError(f"Unknown tool: {name}")
    
    if name == "get_tables":
        results = db.execute_query("SELECT * FROM log.EDWAllTablesVw")
        return dict_list_to_csv(results)
    
    query = arguments.get("query")
    if not query:
        raise ValueError("Query is required")
    
    try:
       
        # Special handling for listing tables in MSSQL
        if query.strip().upper() == "SHOW TABLES":
            results = db.execute_query("SELECT * FROM log.EDWAllTablesVw")
            return dict_list_to_csv(results)
        
        # Regular SELECT queries
        elif query.strip().upper().startswith("SELECT"):
            results = db.execute_query(query)
            if not results:
                return [TextContent(type="text", text="No results found")]
                
            columns = results[0].keys()
            rows = [[row[col] for col in columns] for row in results]
            return [TextContent(type="text", text="\n".join([",".join(columns)] + [",".join(map(str, row)) for row in rows]))]
        
        # Non-SELECT queries
        else:
            db.execute_insert_instant(query)
            return [TextContent(type="text", text="Query executed successfully")]
                
    except Exception as e:
        logger.error(f"Error executing SQL '{query}': {e}")
        return [TextContent(type="text", text=f"Error executing query: {str(e)}")]
    

async def main():
    """Main entry point to run the MCP server."""
    from mcp.server.stdio import stdio_server
    
    logger.info("Starting MSSQL MCP server...")
    config = get_db_config()
    logger.info(f"Database config: {config['server']}/{config['database']}")
    
    async with stdio_server() as (read_stream, write_stream):
        try:
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="edw_mcp_server",
                    server_description="EDW MCP Server",
                    server_version="1.0.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={}
                    )
                )
            )
        except Exception as e:
            logger.error(f"Server error: {str(e)}", exc_info=True)
            raise


if __name__ == "__main__":
    asyncio.run(main())