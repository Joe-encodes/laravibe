import asyncio
from sqlalchemy.ext.asyncio import create_async_engine

DB_URL = "postgresql+asyncpg://koyeb-adm:npg_CJ3HdwSQGc5Y@ep-frosty-bird-al9czkz6.c-3.eu-central-1.pg.koyeb.app/koyebdb"
engine = create_async_engine(DB_URL)

async def test():
    try:
        async with engine.begin() as conn:
            from sqlalchemy import text
            res = await conn.execute(text("SELECT count(*) FROM submissions;"))
            print(f"Submissions in PG: {res.scalar()}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test())
