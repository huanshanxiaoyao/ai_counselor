"""
基础设定加载器
负责从文件系统加载离线预置的人物基础设定
"""
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 获取 base_profiles 目录路径
BASE_PROFILES_DIR = Path(__file__).parent / "base_profiles"


class BaseProfileLoader:
    """基础设定加载器"""

    _instance: Optional['BaseProfileLoader'] = None
    _profiles: Dict[str, dict] = {}
    _loaded: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not BaseProfileLoader._loaded:
            self._load_all_profiles()

    def _load_all_profiles(self):
        """加载所有基础设定文件"""
        BaseProfileLoader._profiles = {}

        if not BASE_PROFILES_DIR.exists():
            logger.warning(f"Base profiles directory not found: {BASE_PROFILES_DIR}")
            return

        for file_path in BASE_PROFILES_DIR.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    profile = json.load(f)
                    name = profile.get('name', '')
                    if name:
                        BaseProfileLoader._profiles[name] = profile
                        logger.info(f"Loaded base profile: {name}")
            except Exception as e:
                logger.error(f"Failed to load profile from {file_path}: {e}")

        BaseProfileLoader._loaded = True
        logger.info(f"Loaded {len(BaseProfileLoader._profiles)} base profiles")

    def get_profile(self, name: str) -> Optional[dict]:
        """
        获取指定人物的基础设定

        Args:
            name: 角色名

        Returns:
            基础设定字典，如果不存在返回 None
        """
        return BaseProfileLoader._profiles.get(name)

    def has_profile(self, name: str) -> bool:
        """检查是否有指定人物的基础设定"""
        return name in BaseProfileLoader._profiles

    def get_all_profiles(self) -> Dict[str, dict]:
        """获取所有已加载的基础设定"""
        return BaseProfileLoader._profiles.copy()

    def get_profile_names(self) -> List[str]:
        """获取所有已配置基础设定的人物名列表"""
        return list(BaseProfileLoader._profiles.keys())

    def reload(self):
        """重新加载所有基础设定"""
        BaseProfileLoader._loaded = False
        BaseProfileLoader._profiles = {}
        self._load_all_profiles()


def get_base_profile_loader() -> BaseProfileLoader:
    """获取基础设定加载器单例"""
    return BaseProfileLoader()
