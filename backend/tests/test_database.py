import pytest
from app.database import get_psycopg_conn_string


class TestGetPsycopgConnString:
    """Tests for converting SQLAlchemy URLs to psycopg connection strings."""

    def test_standard_url(self):
        """Standard connection string is converted correctly."""
        url = "postgresql+psycopg://user:password@localhost:5432/mydb"
        result = get_psycopg_conn_string(url)
        assert result == "postgresql://user:password@localhost:5432/mydb"

    def test_username_with_at_sign(self):
        """Username containing @ (e.g. GCP IAM service accounts) is percent-encoded."""
        url = "postgresql+psycopg://sa@project.iam@127.0.0.1:5432/mydb"
        result = get_psycopg_conn_string(url)
        # The @ in the username must be encoded as %40 so psycopg doesn't
        # mistake it for the user@host separator.
        assert result == "postgresql://sa%40project.iam@127.0.0.1:5432/mydb"
        assert "sa@project.iam@" not in result

    def test_username_with_at_sign_and_password(self):
        """Username with @ and a password are both handled correctly."""
        url = "postgresql+psycopg://sa@project.iam:secret@127.0.0.1:5432/mydb"
        result = get_psycopg_conn_string(url)
        assert result == "postgresql://sa%40project.iam:secret@127.0.0.1:5432/mydb"

    def test_password_with_special_characters(self):
        """Special characters in the password are percent-encoded."""
        url = "postgresql+psycopg://user:p%40ss%3Aword@localhost:5432/mydb"
        result = get_psycopg_conn_string(url)
        assert result == "postgresql://user:p%40ss%3Aword@localhost:5432/mydb"

    def test_no_password(self):
        """URLs without a password (e.g. IAM auth) work correctly."""
        url = "postgresql+psycopg://sa@project.iam@127.0.0.1:5432/mydb"
        result = get_psycopg_conn_string(url)
        assert "postgresql://sa%40project.iam@127.0.0.1:5432/mydb" == result
        # No colon before @ (no password segment)
        assert ":%40" not in result.split("@")[0]

    def test_driver_prefix_removed(self):
        """The +psycopg dialect suffix is stripped from the drivername."""
        url = "postgresql+psycopg://user:password@localhost:5432/mydb"
        result = get_psycopg_conn_string(url)
        assert result.startswith("postgresql://")
        assert "+psycopg" not in result

    def test_plain_postgresql_url_unchanged(self):
        """A plain postgresql:// URL passes through without issues."""
        url = "postgresql://user:password@localhost:5432/mydb"
        result = get_psycopg_conn_string(url)
        assert result == "postgresql://user:password@localhost:5432/mydb"
