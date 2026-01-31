"""
统一 API 配置：所有脚本从此模块读取 API Key 与模型配置。

加载顺序：
  1. 若存在 config_local.py，则从中读取 API_KEY、BASE_URL、MODEL_NAME
  2. 否则从环境变量读取：OPENAI_API_KEY、OPENAI_BASE_URL、OPENAI_MODEL_NAME
  3. 未设置时使用占位符/默认值（LLM 相关功能会提示配置）

使用方式：
  - 推荐：复制 config_local.py.example 为 config_local.py，填入你的 Key（勿提交 config_local.py）
  - 或：设置环境变量 OPENAI_API_KEY 等
"""

import os

# 尝试从本地配置文件加载（不提交到版本库）
try:
    from config_local import API_KEY as _API_KEY, BASE_URL as _BASE_URL, MODEL_NAME as _MODEL_NAME
    API_KEY = _API_KEY
    BASE_URL = _BASE_URL
    MODEL_NAME = _MODEL_NAME
except ImportError:
    API_KEY = os.environ.get("OPENAI_API_KEY", "")
    BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")
    MODEL_NAME = os.environ.get("OPENAI_MODEL_NAME", "deepseek-chat")

# 占位符，用于判断是否已配置真实 Key
_PLACEHOLDER = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"


def is_api_configured():
    """是否已配置可用的 API Key（非空且非占位符）。"""
    return bool(API_KEY and API_KEY.strip() != _PLACEHOLDER)
