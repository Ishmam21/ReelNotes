import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated
from unicodedata import category
from uuid import UUID, uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from .db import accounts, get_engine, sessions

router = APIRouter(prefix="/auth", tags=["accounts"])
SESSION_COOKIE = "reelnotes_session"
SESSION_AGE = timedelta(days=7)
SECURE_COOKIE = os.getenv("WEB_ORIGIN", "").startswith("https://")
password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash(token_urlsafe(32))

SessionToken = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]


class LoginCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)


class Registration(LoginCredentials):
    password: SecretStr = Field(min_length=6, max_length=128)

    @field_validator("password")
    @classmethod
    def require_password_character_types(cls, password: SecretStr) -> SecretStr:
        categories = {category(character) for character in password.get_secret_value()}
        if not {"Lu", "Ll", "Nd"} <= categories or not any(item.startswith(("P", "S")) for item in categories):
            raise ValueError("Include an uppercase letter, a lowercase letter, a number, and a special character.")
        return password


class Account(BaseModel):
    id: UUID
    email: EmailStr


def token_hash(token: str) -> bytes:
    return sha256(token.encode("utf-8")).digest()


def create_session(conn, account_id: UUID, previous_token: str | None) -> str:
    now = datetime.now(timezone.utc)
    conn.execute(delete(sessions).where(sessions.c.expires_at <= now))
    if previous_token:
        conn.execute(delete(sessions).where(sessions.c.token_hash == token_hash(previous_token)))
    token = token_urlsafe(32)
    conn.execute(insert(sessions).values(
        token_hash=token_hash(token), account_id=account_id, expires_at=now + SESSION_AGE,
    ))
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=int(SESSION_AGE.total_seconds()),
        httponly=True, secure=SECURE_COOKIE, samesite="lax",
    )


def current_account(token: SessionToken = None) -> Account:
    if token:
        with get_engine().connect() as conn:
            account = conn.execute(
                select(accounts.c.id, accounts.c.email)
                .join(sessions, accounts.c.id == sessions.c.account_id)
                .where(sessions.c.token_hash == token_hash(token), sessions.c.expires_at > datetime.now(timezone.utc))
            ).mappings().first()
        if account:
            return Account.model_validate(account)
    raise HTTPException(401, "Log in to continue")


CurrentAccount = Annotated[Account, Depends(current_account)]


@router.post("/register", status_code=201)
def register(body: Registration, response: Response, token: SessionToken = None) -> Account:
    email = body.email.casefold()
    hashed = password_hasher.hash(body.password.get_secret_value())
    with get_engine().begin() as conn:
        account_id = conn.execute(
            insert(accounts).values(id=uuid4(), email=email, password_hash=hashed)
            .on_conflict_do_nothing(index_elements=[accounts.c.email]).returning(accounts.c.id)
        ).scalar_one_or_none()
        if account_id is None:
            raise HTTPException(409, "An account already exists for this email")
        session = create_session(conn, account_id, token)
    set_session_cookie(response, session)
    return Account(id=account_id, email=email)


@router.post("/login")
def login(body: LoginCredentials, response: Response, token: SessionToken = None) -> Account:
    with get_engine().connect() as conn:
        account = conn.execute(
            select(accounts).where(accounts.c.email == body.email.casefold())
        ).mappings().first()
    valid = password_hasher.verify(body.password.get_secret_value(), account["password_hash"] if account else dummy_hash)
    if not valid or account is None:
        raise HTTPException(401, "Incorrect email or password")
    with get_engine().begin() as conn:
        session = create_session(conn, account["id"], token)
    set_session_cookie(response, session)
    return Account(id=account["id"], email=account["email"])


@router.post("/logout", status_code=204)
def logout(response: Response, token: SessionToken = None) -> None:
    if token:
        with get_engine().begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.token_hash == token_hash(token)))
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=SECURE_COOKIE, samesite="lax")


@router.get("/me")
def me(account: CurrentAccount) -> Account:
    return account
