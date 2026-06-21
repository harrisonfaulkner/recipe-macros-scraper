from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    usda_api_key: str = ""
    database_path: str = "data/nutrition.db"
    runtime_db_path: str = "data/runtime/runtime.db"
    admin_api_key: str = ""
    request_timeout: int = 10
    log_level: str = "INFO"
    allowed_origins: list[str] = ["*"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
