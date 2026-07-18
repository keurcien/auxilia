"""add official mcp servers batch

Adds PandaDoc, Praiz, Kahoot, Tavily, Calendar, Gmail, and Drive to the official
MCP server catalog. Icons are served from the R2 CDN.

Revision ID: b2c3d4e5f6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ICON_BASE = "https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/"

# (name, url, auth_type, icon_file, supports_dcr, description)
# supports_dcr is None for non-OAuth servers (not applicable).
SERVERS = [
    (
        "PandaDoc",
        "https://mcp.pandadoc.com/v1/mcp",
        "oauth2",
        "pandadoc.png",
        True,
        "PandaDoc is a document automation platform for creating, sending, "
        "e-signing, and tracking business documents such as proposals, quotes, "
        "and contracts. Its MCP server connects AI assistants directly to your "
        "document and agreement workflows, letting them draft, send, and manage "
        "documents through natural-language instructions.",
    ),
    (
        "Praiz",
        "https://mcp.praiz.io/mcp",
        "oauth2",
        "praiz.png",
        True,
        "Praiz is an AI meeting platform that records and transcribes sales and "
        "customer calls across tools like Zoom, Google Meet, and Microsoft Teams, "
        "turning conversations into structured, CRM-ready data. Its read-only MCP "
        "server lets an AI assistant search and retrieve meeting videos, "
        "transcripts, participants, comments, and usage insights from a Praiz "
        "workspace.",
    ),
    (
        "Kahoot",
        "https://mcp.kahoot.it/mcp",
        "oauth2",
        "kahoot.png",
        True,
        "Kahoot! is a game-based learning platform for creating and running "
        "interactive quizzes and presentations. Its MCP server lets an AI "
        "assistant create, edit, and manage kahoots through natural-language "
        "commands, including generating quiz questions and translating content "
        "(currently multiple-choice and true/false formats).",
    ),
    (
        "Tavily",
        "https://mcp.tavily.com/mcp",
        "api_key",
        "tavily.png",
        None,
        "Tavily is a web search and data extraction API built for AI agents. Its "
        "MCP server gives an AI assistant real-time tools to search the web, "
        "extract structured content from URLs, and map or crawl websites, "
        "returning clean, LLM-ready results.",
    ),
    (
        "Calendar",
        "https://calendarmcp.googleapis.com/mcp/v1",
        "oauth2",
        "calendar.png",
        False,
        "Google Calendar is Google's scheduling and calendar service. Its MCP "
        "server lets an AI assistant list calendars and events, check "
        "availability and suggest times, and create, update, respond to, or "
        "delete events, inheriting the user's existing permissions.",
    ),
    (
        "Gmail",
        "https://gmailmcp.googleapis.com/mcp/v1",
        "oauth2",
        "gmail.png",
        False,
        "Gmail is Google's email service. Its MCP server lets an AI assistant "
        "search and read messages and threads, create drafts, and organize mail "
        "with labels, operating under the user's existing account permissions.",
    ),
    (
        "Drive",
        "https://drivemcp.googleapis.com/mcp/v1",
        "oauth2",
        "drive.png",
        False,
        "Google Drive is Google's cloud file storage and sharing service. Its MCP "
        "server lets an AI assistant search files, read and download file content "
        "and metadata, check permissions, and create or copy files, respecting "
        "the user's existing access controls.",
    ),
]


def upgrade() -> None:
    stmt = sa.text(
        """
        INSERT INTO official_mcp_servers
            (name, url, auth_type, icon_url, description, supports_dcr)
        VALUES (
            :name, :url, CAST(:auth_type AS mcp_auth_type),
            :icon_url, :description, :supports_dcr
        )
        """
    )
    for name, url, auth_type, icon_file, supports_dcr, description in SERVERS:
        op.execute(
            stmt.bindparams(
                name=name,
                url=url,
                auth_type=auth_type,
                icon_url=ICON_BASE + icon_file,
                description=description,
                supports_dcr=supports_dcr,
            )
        )


def downgrade() -> None:
    stmt = sa.text("DELETE FROM official_mcp_servers WHERE url = :url")
    for _name, url, *_rest in SERVERS:
        op.execute(stmt.bindparams(url=url))
