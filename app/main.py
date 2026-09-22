import logging
import secrets
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError, ProgrammingError, TimeoutError
from sqlalchemy.orm import Session

from app.cache import EvaluationCache
from app.config import Settings
from app.db import Flag, UserOverride, make_engine
from app.schemas import (
    NAME_PATTERN,
    USER_PATTERN,
    CreateFlag,
    Evaluation,
    FlagResponse,
    OverrideResponse,
    SetDefault,
    SetOverride,
)

logger = logging.getLogger(__name__)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    cache: EvaluationCache[Evaluation] = EvaluationCache(
        settings.cache_max_entries, settings.cache_ttl_seconds
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(title="Feature Flag API", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.cache = cache
    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def authenticate(key: Optional[str] = Security(api_key_header)):
        if settings.api_key is not None and (
            key is None
            or not secrets.compare_digest(
                key.encode("utf-8"), settings.api_key.get_secret_value().encode("utf-8")
            )
        ):
            raise HTTPException(
                401, "Missing or invalid API key", headers={"WWW-Authenticate": "ApiKey"}
            )

    flags = APIRouter(dependencies=[Depends(authenticate)])

    @app.exception_handler(OperationalError)
    @app.exception_handler(TimeoutError)
    async def database_unavailable(request, exc):
        # Do not include SQL parameters, user identifiers, or credentials in logs.
        logger.error("Database unavailable (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={"detail": "Database temporarily unavailable"},
            headers={"Retry-After": "1"},
        )

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready():
        try:
            with engine.connect() as connection:
                # Check application tables, not merely the database connection.
                connection.execute(select(Flag.name).limit(1))
                connection.execute(select(UserOverride.user_id).limit(1))
        except ProgrammingError:
            raise HTTPException(503, "Database schema not ready") from None
        return {"status": "ready"}

    @flags.post("/flags", status_code=201, response_model=FlagResponse, tags=["flags"])
    def create_flag(body: CreateFlag, response: Response):
        with Session(engine) as session, session.begin():
            row = session.execute(
                insert(Flag)
                .values(**body.model_dump())
                .on_conflict_do_nothing(index_elements=[Flag.name])
                .returning(Flag)
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(409, "Flag already exists")
            result = FlagResponse.model_validate(row)
        cache.invalidate()
        response.headers["Location"] = f"/flags/{result.name}"
        return result

    @flags.get("/flags/{flag_name}", response_model=FlagResponse, tags=["flags"])
    def get_flag(
        flag_name: str = Path(min_length=1, max_length=100, pattern=NAME_PATTERN),
    ):
        with Session(engine) as session:
            flag = session.get(Flag, flag_name)
            if flag is None:
                raise HTTPException(404, "Flag not found")
            return FlagResponse.model_validate(flag)

    @flags.put("/flags/{flag_name}/default", response_model=FlagResponse, tags=["flags"])
    def set_default(
        body: SetDefault,
        flag_name: str = Path(min_length=1, max_length=100, pattern=NAME_PATTERN),
    ):
        with Session(engine) as session, session.begin():
            row = session.execute(
                update(Flag)
                .where(Flag.name == flag_name)
                .values(default_enabled=body.default_enabled)
                .returning(Flag)
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(404, "Flag not found")
            result = FlagResponse.model_validate(row)
        cache.invalidate()
        return result

    @flags.put(
        "/flags/{flag_name}/users/{user_id}",
        response_model=OverrideResponse,
        tags=["flags"],
    )
    def set_override(
        body: SetOverride,
        flag_name: str = Path(min_length=1, max_length=100, pattern=NAME_PATTERN),
        user_id: str = Path(min_length=1, max_length=128, pattern=USER_PATTERN),
    ):
        with Session(engine) as session, session.begin():
            if session.get(Flag, flag_name) is None:
                raise HTTPException(404, "Flag not found")
            session.execute(
                insert(UserOverride)
                .values(flag_name=flag_name, user_id=user_id, enabled=body.enabled)
                .on_conflict_do_update(
                    index_elements=[UserOverride.flag_name, UserOverride.user_id],
                    set_={"enabled": body.enabled},
                )
            )
        cache.invalidate()
        return OverrideResponse(flag_name=flag_name, user_id=user_id, enabled=body.enabled)

    @flags.get("/flags/{flag_name}/evaluate", response_model=Evaluation, tags=["evaluation"])
    def evaluate(
        response: Response,
        flag_name: str = Path(min_length=1, max_length=100, pattern=NAME_PATTERN),
        user_id: str = Query(min_length=1, max_length=128, pattern=USER_PATTERN),
    ):
        response.headers["Cache-Control"] = "no-store"
        key = (flag_name, user_id)
        cached, generation = cache.get(key)
        if cached is not None:
            return cached
        with Session(engine) as session:
            # One statement gives a consistent snapshot of default and override.
            row = session.execute(
                select(Flag.default_enabled, UserOverride.enabled)
                .outerjoin(
                    UserOverride,
                    and_(
                        UserOverride.flag_name == Flag.name,
                        UserOverride.user_id == user_id,
                    ),
                )
                .where(Flag.name == flag_name)
            ).one_or_none()
            if row is None:
                raise HTTPException(404, "Flag not found")
            default, override = row
        result = Evaluation(
            flag_name=flag_name,
            user_id=user_id,
            enabled=default if override is None else override,
            source="default" if override is None else "override",
        )
        cache.put(key, result, generation)
        return result

    app.include_router(flags)
    return app
