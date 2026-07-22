from pydantic_settings import BaseSettings

# gpt-4o-mini token prices in USD per token.
# Source: https://openai.com/api/pricing/  Checked: 2026-07-22
# Verify before the demo -- OpenAI adjusts prices without notice.
PRICE_TABLE: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {
        "input": 0.150 / 1_000_000,   # $0.150 per 1M input tokens
        "output": 0.600 / 1_000_000,  # $0.600 per 1M output tokens
    }
}


class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "deskfleet"
    STORE_API_BASE: str = "https://fakestoreapi.com"
    STORE_API_OFFLINE: bool = False
    MAX_ITERS: int = 2
    MAX_TOOL_CALLS: int = 4
    DB_PATH: str = "/tmp/deskfleet.db"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
