import asyncio
from pathlib import Path

from dotenv import load_dotenv

from src.tiny_agent.config import get_tiny_agent_config
from src.tiny_agent.tiny_agent import TinyAgent

load_dotenv()


async def main():
    config_path = Path.cwd() / "llm_configs/" / "config_openai.json"

    tiny_agent_config = get_tiny_agent_config(config_path=str(config_path))
    tiny_agent = TinyAgent(tiny_agent_config)
    await tiny_agent.arun(
        query="Write a notes with the Carbonara recipe "
              " and then write the route how to get to the origin of Spaghetti Carbonara."
    )


if __name__ == "__main__":
    asyncio.run(main())
