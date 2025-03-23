import os
import json
import requests
import logging
import asyncio
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from pathlib import Path
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Resource, Tool, TextContent
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("slack_mcp_server")

########################################################
# Slack Client
########################################################

class SlackClient:

    def __init__(self, client_id: str, client_secret: str, team_id: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.team_id = team_id
        self.user_token = None
        self.bot_headers = None

    def to_dict(self) -> dict:
        return {
            "client_id": self.client_id,
            "team_id": self.team_id,
            "has_user_token": self.user_token is not None
        }

    def authenticate_user(self, code: str) -> dict:
        """Authenticate a user using OAuth2 code flow."""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": "http://localhost:3000/callback"  # You might want to make this configurable
        }
        
        response = requests.post("https://slack.com/api/oauth.v2.access", json=data)
        result = response.json()
        
        if result.get("ok"):
            self.user_token = result.get("access_token")
            self.bot_headers = {
                "Authorization": f"Bearer {self.user_token}",
                "Content-Type": "application/json",
            }
            return result
        else:
            raise Exception(f"Authentication failed: {result.get('error')}")

    def get_auth_url(self) -> str:
        """Generate the OAuth2 authorization URL."""
        scopes = [
            "channels:read",
            "chat:write",
            "reactions:write",
            "users:read",
            "users:read.email"
        ]
        
        return (
            f"https://slack.com/oauth/v2/authorize"
            f"?client_id={self.client_id}"
            f"&scope={','.join(scopes)}"
            f"&user_scope={','.join(scopes)}"
            f"&redirect_uri=http://localhost:3000/callback"
        )
    
    def set_user_token(self, user_token: str):
        self.user_token = user_token
        self.bot_headers = {
            "Authorization": f"Bearer {self.user_token}",
            "Content-Type": "application/json",
        }

    def get_channels(self, limit=100, cursor=None):
        if not self.bot_headers:
            raise Exception("Not authenticated. Please authenticate first.")
        params = {
            "types": "public_channel",
            "exclude_archived": "true",
            "limit": min(limit, 200),
            "team_id": self.team_id,
        }
        if cursor:
            params["cursor"] = cursor

        response = requests.get("https://slack.com/api/conversations.list", headers=self.bot_headers, params=params)
        return response.json()
    

    def post_message(self, channel_id: str, text: str):
        data = {"channel": channel_id, "text": text}
        response = requests.post("https://slack.com/api/chat.postMessage", headers=self.bot_headers, json=data)
        return response.json()
    

    def post_reply(self, channel_id: str, thread_ts: str, text: str):
        data = {"channel": channel_id, "thread_ts": thread_ts, "text": text}
        response = requests.post("https://slack.com/api/chat.postMessage", headers=self.bot_headers, json=data)
        return response.json()
    

    def add_reaction(self, channel_id: str, timestamp: str, reaction: str):
        data = {"channel": channel_id, "timestamp": timestamp, "name": reaction}
        response = requests.post("https://slack.com/api/reactions.add", headers=self.bot_headers, json=data)
        return response.json()
    

    def get_channel_history(self, channel_id: str, limit=10):
        params = {"channel": channel_id, "limit": limit}
        response = requests.get("https://slack.com/api/conversations.history", headers=self.bot_headers, params=params)
        return response.json()


    def get_thread_replies(self, channel_id: str, thread_ts: str):
        params = {"channel": channel_id, "ts": thread_ts}
        response = requests.get("https://slack.com/api/conversations.replies", headers=self.bot_headers, params=params)
        return response.json()
    

    def get_users(self, limit=100, cursor=None):
        params = {"limit": min(limit, 200), "team_id": self.team_id}
        if cursor:
            params["cursor"] = cursor
        response = requests.get("https://slack.com/api/users.list", headers=self.bot_headers, params=params)
        return response.json()
    

    def get_user_profile(self, user_id: str):
        params = {"user": user_id, "include_labels": "true"}
        response = requests.get("https://slack.com/api/users.profile.get", headers=self.bot_headers, params=params)
        return response.json()


########################################################
# Server Configuration
########################################################

def get_server_config():
    """Get server configuration from environment variables and .env file."""
    # Try to load .env file if it exists
    env_path = Path(__file__).parent.parent.parent.joinpath('.env')
    logger.info(f"Loading configuration from {env_path}")
    if env_path.exists():
        load_dotenv(env_path)

    # Debug logging to see all environment variables
    logger.info("Available environment variables:")
    for key, value in os.environ.items():
        if any(slack_key in key.upper() for slack_key in ['SLACK']):
            logger.info(f"{key}: {'*' * len(value)}")  # Mask the actual values for security
    
    config = {
        "organization_id": os.getenv("SLACK_ORGANIZATION_ID"),
        "client_id": os.getenv("SLACK_CLIENT_ID"),
        "client_secret": os.getenv("SLACK_CLIENT_SECRET"),
    }
    
    # Debug logging to see which specific variables are missing
    missing_vars = [key for key, value in config.items() if not value]
    if missing_vars:
        logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.error("Please check environment variables or .env file:")
        logger.error("SLACK_ORGANIZATION_ID, SLACK_CLIENT_ID, and SLACK_CLIENT_SECRET are required")
        raise ValueError("Missing required Slack configuration")
    
    return config


########################################################
# Dataclass definitions
########################################################

@dataclass
class ServerContext:
    slack: SlackClient
    resources: list[Resource] | None

    def to_dict(self) -> dict:
        """Convert the ServerContext to a dictionary."""
        return {
            "slack": self.slack.to_dict(),
            "resources": [resource.to_dict() for resource in (self.resources or [])]
        }

########################################################
# Server Functions
########################################################  

@asynccontextmanager
async def server_lifespan(server: Server) -> AsyncIterator[ServerContext]:
    """Manage server startup and shutdown lifecycle."""
    # Initialize resources on startup
    config = get_server_config()
    
    try:
        logger.info("Initializing database connection and resources")

        # Initialize database connection
        slack = SlackClient(config["client_id"], config["client_secret"], config["organization_id"]) 

        # Execute query synchronously
        results = None
        resources = []

        # Log out how many resources were found
        logger.info(f"Found {len(resources)} resources")

        # Yield server context with database connection and resources
        yield ServerContext(slack=slack, resources=resources)
    finally:
        # Clean up on shutdown
        pass


# Initialize server
server = Server("slack_mcp_server", lifespan=server_lifespan)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Slack tools."""
    logger.info("Listing tools...")
    return [
        Tool(
            name="get_auth_url",
            description="Get the OAuth2 authorization URL for user authentication",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="authenticate",
            description="Authenticate a user using the OAuth2 code",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The OAuth2 code received from the authorization URL"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="get_channels",
            description="Get all channels in the Slack workspace",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "The maximum number of channels to return"
                    }
                },
                "required": ["limit"]
            }
        ),
        Tool(
            name="post_message",
            description="Post a message to a channel",
                inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                            "description": "The ID of the channel to post the message to"
                    },
                    "text": {
                        "type": "string",
                        "description": "The message to post"
                    }
                },
                "required": ["channel_id", "text"]
            }
        ),
        Tool(
            name="post_reply",
            description="Post a reply to a message in a thread",
                inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "The ID of the channel to post the reply to"
                    },
                    "thread_ts": {
                        "type": "string",
                        "description": "The timestamp of the message to reply to"
                    },
                    "text": {
                        "type": "string",
                        "description": "The message to post"
                    }
                },
                "required": ["channel_id", "thread_ts", "text"]
            }
        ),
        Tool(
            name="add_reaction",
            description="Add a reaction to a message",
                inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "The ID of the channel to add the reaction to"
                        },
                    "timestamp": {
                        "type": "string",
                        "description": "The timestamp of the message to add the reaction to"
                    },
                    "reaction": {
                        "type": "string",
                        "description": "The reaction to add"
                    }
                },
                "required": ["channel_id", "timestamp", "reaction"]
            }
        ),
        Tool(
            name="get_channel_history",
            description="Get the history of a channel",
                inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "The ID of the channel to get the history of"
                    }
                },
                "required": ["channel_id"]
            }
        ),
        Tool(
            name="get_thread_replies",
            description="Get the replies to a message in a thread",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "The ID of the channel to get the replies to"
                    },
                    "thread_ts": {
                        "type": "string",
                        "description": "The timestamp of the message to get the replies to"
                    }
                },
                "required": ["channel_id", "thread_ts"]
            }
        ),
        Tool(
            name="get_users",
            description="Get all users in the Slack workspace",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {  
                        "type": "integer",
                        "description": "The maximum number of users to return"
                    }
                },
                "required": ["limit"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute Slack commands."""

    ctx = server.request_context
    slack: SlackClient = ctx.lifespan_context.slack

    logger.info(f"Calling tool: {name} with arguments: {arguments}")

    try:
        if name == "get_auth_url":
            auth_url = slack.get_auth_url()
            return [TextContent(type="text", text=json.dumps({"auth_url": auth_url}))]
            
        elif name == "authenticate":
            results = slack.authenticate_user(arguments["code"])
            slack.set_user_token(results["access_token"])
            return [TextContent(type="text", text=json.dumps(results))]
            
        elif name == "get_channels":
            results = slack.get_channels(arguments["limit"])
            return [TextContent(type="text", text=json.dumps(results))]
    
        elif name == "post_message":
            results = slack.post_message(arguments["channel_id"], arguments["text"])
            return [TextContent(type="text", text=json.dumps(results))]
    
        elif name == "post_reply":
            results = slack.post_reply(arguments["channel_id"], arguments["thread_ts"], arguments["text"])
            return [TextContent(type="text", text=json.dumps(results))] 
    
        elif name == "add_reaction":
            results = slack.add_reaction(arguments["channel_id"], arguments["timestamp"], arguments["reaction"])
            return [TextContent(type="text", text=json.dumps(results))] 
    
        elif name == "get_channel_history":
            results = slack.get_channel_history(arguments["channel_id"])
            return [TextContent(type="text", text=json.dumps(results))]
    
        elif name == "get_thread_replies":
            results = slack.get_thread_replies(arguments["channel_id"], arguments["thread_ts"])
            return [TextContent(type="text", text=json.dumps(results))] 
    
        elif name == "get_users":
            results = slack.get_users(arguments["limit"])
            return [TextContent(type="text", text=json.dumps(results))]
    
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    except Exception as e:
        logger.error(f"Error calling tool: {name} with arguments: {arguments}")
        logger.error(f"Error: {e}")
        raise
    


async def main():
    """Main entry point to run the MCP server."""
    from mcp.server.stdio import stdio_server
    
    logger.info("Starting Slack MCP server...")
    
    async with stdio_server() as (read_stream, write_stream):
        try:
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="slack_mcp_server",
                    server_description="Slack MCP Server",
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
