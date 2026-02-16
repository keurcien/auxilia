from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_db
from app.users.models import (
    UserCreate,
    UserDB,
    UserRead,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserRead, status_code=201)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)) -> UserRead:
    """Create a new user."""
    # Check if email already exists
    if user.email:
        result = await db.execute(select(UserDB).where(UserDB.email == user.email))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")

    db_user = UserDB.model_validate(user)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


@router.get("/", response_model=list[UserRead])
async def get_users(
    is_admin: bool | None = None, db: AsyncSession = Depends(get_db)
) -> list[UserRead]:
    """List all users, optionally filtered by is_admin."""
    query = select(UserDB)
    if is_admin is not None:
        query = query.where(UserDB.is_admin == is_admin)
    result = await db.execute(query)
    users = result.scalars().all()
    return list(users)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: UUID, db: AsyncSession = Depends(get_db)) -> UserRead:
    """Get a user by ID."""
    result = await db.execute(select(UserDB).where(UserDB.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/email/{email}", response_model=UserRead)
async def get_user_by_email_route(email: str, db: AsyncSession = Depends(get_db)) -> UserRead:
    """Get a user by email."""
    from app.users.service import get_user_by_email
    user = await get_user_by_email(email, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID, user_update: UserUpdate, db: AsyncSession = Depends(get_db)
) -> UserRead:
    """Update a user."""
    result = await db.execute(select(UserDB).where(UserDB.id == user_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if email is being changed and if it already exists
    update_data = user_update.model_dump(exclude_unset=True)
    if "email" in update_data and update_data["email"] != db_user.email:
        result = await db.execute(
            select(UserDB).where(UserDB.email == update_data["email"])
        )
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")

    for key, value in update_data.items():
        setattr(db_user, key, value)

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a user."""
    result = await db.execute(select(UserDB).where(UserDB.id == user_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(db_user)
    await db.commit()
