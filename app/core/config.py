from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# 1. 动态获取当前文件 (config.py) 的绝对路径
# 当前文件: ScholarVision/app/core/config.py
current_file = Path(__file__).resolve()

# 2. 往上翻三级：core -> app -> ScholarVision(根目录)
BASE_DIR = current_file.parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

class Settings(BaseSettings):
    # 3. 强制指定读取绝对路径的 .env 文件
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore" 
    )

    PROJECT_NAME: str = "Scholar Vision"
    INTERN_API_KEY: str

settings = Settings()