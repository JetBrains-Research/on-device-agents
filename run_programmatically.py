import asyncio
from pathlib import Path

from dotenv import load_dotenv

from src.tiny_agent.config import get_tiny_agent_config
from src.tiny_agent.tiny_agent import TinyAgent

load_dotenv()


async def main():
    config_path = Path.cwd() / "config.json"

    tiny_agent_config = get_tiny_agent_config(config_path=str(config_path))
    tiny_agent = TinyAgent(tiny_agent_config)
    await tiny_agent.arun(
        query="How to get to the KIT Uni from my place? " " Write the result into the notes with detailed route."
    )


if __name__ == "__main__":
    asyncio.run(main())
