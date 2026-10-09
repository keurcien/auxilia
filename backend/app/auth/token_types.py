from enum import StrEnum


class TokenKind(StrEnum):
    session = "access"
    scoped = "challenge"
