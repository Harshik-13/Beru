from backend.app.core.config import settings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.app_env.value == "development",
        future=True,
    )


engine: AsyncEngine = create_engine()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
