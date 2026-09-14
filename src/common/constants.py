"""
全局常量定义。
"""
from pathlib import Path

# 项目根目录：src/common/constants.py -> 项目根（parents[2]）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 默认配置文件路径
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_LOGGING_CONFIG_PATH = PROJECT_ROOT / "config" / "logging.yaml"

# 应用标识
APP_NAME = "agent_framework"
APP_VERSION = "0.1.0"

# 环境变量前缀：用于密钥注入（${AGENT_XX}）与配置路径覆盖（AGENT_A__B=val）
ENV_PREFIX = "AGENT_"

# 默认文本编码
DEFAULT_ENCODING = "utf-8"
