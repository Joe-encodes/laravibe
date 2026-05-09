import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

POSTGRES_URL = "postgresql+asyncpg://koyeb-adm:npg_CJ3HdwSQGc5Y@ep-frosty-bird-al9czkz6.c-3.eu-central-1.pg.koyeb.app/koyebdb"

async def test():
    engine = create_async_engine(POSTGRES_URL)
    async with engine.connect() as conn:
        try:
            await conn.execute(text("SELECT user_id, user_prompt FROM submissions LIMIT 1;"))
            print("Submissions columns exist!")
        except Exception as e:
            print("Error in submissions:", str(e))

        try:
            await conn.execute(text("SELECT ai_prompt, planner_model, pm_category FROM iterations LIMIT 1;"))
            print("Iterations columns exist!")
        except Exception as e:
            print("Error in iterations:", str(e))

if __name__ == "__main__":
    asyncio.run(test())
