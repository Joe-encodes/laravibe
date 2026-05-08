import asyncio
import os
import pathlib
import sys

# Add project root to path
sys.path.append(str(pathlib.Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import selectinload

from api.models import Base, Submission, Iteration, RepairSummary

SQLITE_URL = "sqlite+aiosqlite:///./data/repair.db"
POSTGRES_URL = "postgresql+asyncpg://koyeb-adm:npg_CJ3HdwSQGc5Y@ep-frosty-bird-al9czkz6.c-3.eu-central-1.pg.koyeb.app/koyebdb"

async def migrate():
    print("Starting migration from SQLite to Postgres...")
    
    sqlite_engine = create_async_engine(SQLITE_URL)
    SqliteSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)
    
    pg_engine = create_async_engine(POSTGRES_URL)
    PgSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

    # 1. Create tables in Postgres if they don't exist
    print("Ensuring tables exist in Postgres...")
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Fetch data from SQLite
    print("Fetching data from SQLite...")
    async with SqliteSessionLocal() as sqlite_session:
        result_sub = await sqlite_session.execute(select(Submission).options(selectinload(Submission.iterations)))
        submissions = result_sub.scalars().all()

        result_rs = await sqlite_session.execute(select(RepairSummary))
        repair_summaries = result_rs.scalars().all()

    print(f"Found {len(submissions)} Submissions and {len(repair_summaries)} Repair Summaries in SQLite.")

    # 3. Insert into Postgres
    print("Inserting into Postgres...")
    async with PgSessionLocal() as pg_session:
        # To avoid conflicts, we merge them based on ID
        for sub in submissions:
            # SQLAlchemy async merge
            await pg_session.merge(sub)
            
        for rs in repair_summaries:
            await pg_session.merge(rs)

        print("Committing to Postgres...")
        await pg_session.commit()

    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
