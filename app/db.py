from sqlalchemy import Boolean, ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Flag(Base):
    __tablename__ = "flags"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    default_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)


class UserOverride(Base):
    __tablename__ = "user_overrides"

    flag_name: Mapped[str] = mapped_column(
        ForeignKey("flags.name", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)


def make_engine(database_url: str):
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL must use postgresql+psycopg://")
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=5,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
    )
