from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.database_connections.models import DatabaseConnectionStatus, DatabaseEngine
from app.visibility import ResourceVisibility


class DatabaseFileCreateDB(SQLModel):
    workspace_id: UUID
    owner_id: UUID
    original_name: str
    stored_name: str
    size_bytes: int


class DatabaseConnectionCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    group: str | None = Field(default=None, max_length=255)
    engine: DatabaseEngine
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=255)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, exclude=True)
    sqlite_file_id: UUID | None = None
    ssl_mode: str | None = Field(default=None, max_length=64)
    connection_timeout: int = Field(default=10, ge=1, le=300)
    query_timeout: int = Field(default=30, ge=1, le=3600)
    readonly: bool = True
    max_rows: int = Field(default=500, ge=1, le=10000)
    visibility: ResourceVisibility = ResourceVisibility.workspace
    team_ids: list[UUID] = Field(default_factory=list, exclude=True)


class DatabaseConnectionPatch(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    group: str | None = Field(default=None, max_length=255)
    engine: DatabaseEngine | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=255)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, exclude=True)
    sqlite_file_id: UUID | None = None
    ssl_mode: str | None = Field(default=None, max_length=64)
    connection_timeout: int | None = Field(default=None, ge=1, le=300)
    query_timeout: int | None = Field(default=None, ge=1, le=3600)
    readonly: bool | None = None
    max_rows: int | None = Field(default=None, ge=1, le=10000)
    visibility: ResourceVisibility | None = None
    team_ids: list[UUID] | None = Field(default=None, exclude=True)


class DatabaseConnectionResponse(SQLModel):
    id: UUID
    mcp_server_id: UUID
    name: str
    icon_url: str
    image_revision: UUID | None = None
    description: str | None = None
    group: str | None = None
    engine: DatabaseEngine
    host: str | None
    port: int | None
    database: str
    username: str | None
    sqlite_file_id: UUID | None = None
    sqlite_file_name: str | None = None
    sqlite_stored_name: str | None = None
    sqlite_runtime_path: str | None = None
    sqlite_file_size_bytes: int | None = None
    ssl_mode: str | None = None
    connection_timeout: int
    query_timeout: int
    readonly: bool
    max_rows: int
    visibility: ResourceVisibility
    team_ids: list[UUID] = Field(default_factory=list)
    status: DatabaseConnectionStatus
    last_error: str | None = None
    has_password: bool = True
    desired_revision: int
    applied_revision: int
    last_applied_at: datetime | None = None
    created_at: datetime | None
    updated_at: datetime


class DatabaseConnectorStatusResponse(SQLModel):
    enabled: bool
    reachable: bool
    desired_revision: int
    applied_revision: int
    source_count: int
    last_error: str | None = None
    last_applied_at: datetime | None = None


class SQLiteFileResponse(SQLModel):
    id: UUID
    original_name: str
    stored_name: str
    runtime_path: str
    size_bytes: int
