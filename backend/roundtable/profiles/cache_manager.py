"""
话题相关设定缓存管理器
使用 Redis Hash 存储，实现 FIFO (先进先出) 策略
"""
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis

logger = logging.getLogger(__name__)


@dataclass
class TopicProfileCacheEntry:
    """话题设定缓存条目"""
    key: str                          # "角色名:话题"
    character_name: str               # 角色名
    topic: str                        # 话题
    viewpoints: Dict[str, str] = field(default_factory=dict)      # 核心观点
    representative_articles: List[Dict] = field(default_factory=list)  # 代表文章
    language_style: Dict[str, Any] = field(default_factory=dict)   # 语言风格
    temporal_constraints: Dict[str, Any] = field(default_factory=dict)  # 时代边界
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """转换为字典用于序列化"""
        return {
            'key': self.key,
            'character_name': self.character_name,
            'topic': self.topic,
            'viewpoints': self.viewpoints,
            'representative_articles': self.representative_articles,
            'language_style': self.language_style,
            'temporal_constraints': self.temporal_constraints,
            'created_at': self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TopicProfileCacheEntry':
        """从字典反序列化"""
        entry = cls(
            key=data['key'],
            character_name=data['character_name'],
            topic=data['topic'],
            viewpoints=data.get('viewpoints', {}),
            representative_articles=data.get('representative_articles', []),
            language_style=data.get('language_style', {}),
            temporal_constraints=data.get('temporal_constraints', {}),
            created_at=datetime.fromisoformat(data['created_at']) if 'created_at' in data else datetime.now(),
        )
        return entry


class TopicProfileCache:
    """
    话题设定缓存管理器

    使用 Redis Hash 存储：
    - key: "roundtable:topic_profile_cache"
    - field: "角色名:话题"
    - value: JSON序列化的 TopicProfileCacheEntry

    特性：
    - FIFO 策略：使用有序集合按时间戳淘汰最老条目
    - 持久化：存储在 Redis 中，容器重启后数据保留
    - 线程安全
    """

    _instance: Optional['TopicProfileCache'] = None
    _lock = threading.Lock()

    # Redis keys
    CACHE_KEY = "roundtable:topic_profile_cache"
    TIMESTAMP_KEY = "roundtable:topic_profile_cache:ts"

    def __new__(cls, max_size: int = 100):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_size: int = 100):
        if self._initialized:
            return
        self._initialized = True
        self._max_size = max_size

        # Redis connection - use REDIS_HOST env var (default to localhost for local dev)
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', '6379'))
        self._redis = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=0,
            decode_responses=True
        )

        # 预热缓存：将 Redis 中的数据加载到内存索引（提高查询速度）
        self._cache_index: Dict[str, TopicProfileCacheEntry] = {}
        self._load_from_redis()

        logger.info(f"TopicProfileCache initialized with max_size={max_size}, redis={redis_host}:{redis_port}")

    def _load_from_redis(self):
        """从 Redis 加载缓存到内存索引"""
        try:
            all_data = self._redis.hgetall(self.CACHE_KEY)
            for key, data in all_data.items():
                try:
                    entry_data = json.loads(data)
                    entry = TopicProfileCacheEntry.from_dict(entry_data)
                    self._cache_index[key] = entry
                except Exception as e:
                    logger.error(f"Failed to parse cache entry {key}: {e}")
            logger.info(f"Loaded {len(self._cache_index)} entries from Redis")
        except Exception as e:
            logger.error(f"Failed to load cache from Redis: {e}")

    @staticmethod
    def make_key(character_name: str, topic: str) -> str:
        """生成缓存Key"""
        return f"{character_name}:{topic}"

    def get(self, character_name: str, topic: str) -> Optional[TopicProfileCacheEntry]:
        """
        获取缓存条目

        Args:
            character_name: 角色名
            topic: 话题

        Returns:
            缓存条目，如果未命中返回 None
        """
        key = self.make_key(character_name, topic)

        with self._lock:
            if key not in self._cache_index:
                logger.debug(f"Cache miss: {key}")
                return None

            # 移到末尾（最近使用）- 更新 Redis 中的时间戳
            timestamp = datetime.now().timestamp()
            self._redis.zadd(self.TIMESTAMP_KEY, {key: timestamp})

            entry = self._cache_index[key]
            logger.debug(f"Cache hit: {key}")
            return entry

    def set(
        self,
        character_name: str,
        topic: str,
        viewpoints: Dict[str, str] = None,
        representative_articles: List[Dict] = None,
        language_style: Dict[str, Any] = None,
        temporal_constraints: Dict[str, Any] = None
    ) -> TopicProfileCacheEntry:
        """
        设置缓存条目

        Args:
            character_name: 角色名
            topic: 话题
            viewpoints: 核心观点
            representative_articles: 代表文章
            language_style: 语言风格
            temporal_constraints: 时代边界

        Returns:
            创建的缓存条目
        """
        key = self.make_key(character_name, topic)

        with self._lock:
            # 如果已存在，更新
            if key in self._cache_index:
                entry = self._cache_index[key]
                entry.viewpoints = viewpoints or {}
                entry.representative_articles = representative_articles or []
                entry.language_style = language_style or {}
                entry.temporal_constraints = temporal_constraints or {}
                entry.created_at = datetime.now()
                logger.debug(f"Cache updated: {key}")
            else:
                # 新建条目
                entry = TopicProfileCacheEntry(
                    key=key,
                    character_name=character_name,
                    topic=topic,
                    viewpoints=viewpoints or {},
                    representative_articles=representative_articles or [],
                    language_style=language_style or {},
                    temporal_constraints=temporal_constraints or {},
                )
                self._cache_index[key] = entry
                logger.debug(f"Cache set: {key}")

            # 保存到 Redis
            self._redis.hset(self.CACHE_KEY, key, json.dumps(entry.to_dict(), ensure_ascii=False))

            # 更新时间戳用于 FIFO 淘汰
            timestamp = datetime.now().timestamp()
            self._redis.zadd(self.TIMESTAMP_KEY, {key: timestamp})

            # 如果超出容量，淘汰最老的（FIFO）
            if len(self._cache_index) > self._max_size:
                # 获取最老的条目（分数最低）
                oldest = self._redis.zrange(self.TIMESTAMP_KEY, 0, 0)
                if oldest:
                    oldest_key = oldest[0]
                    self._evict_key(oldest_key)
                    logger.info(f"Cache evicted (FIFO): {oldest_key}")

            return entry

    def _evict_key(self, key: str):
        """淘汰指定的缓存键"""
        if key in self._cache_index:
            del self._cache_index[key]
        self._redis.hdel(self.CACHE_KEY, key)
        self._redis.zrem(self.TIMESTAMP_KEY, key)

    def delete(self, character_name: str, topic: str) -> bool:
        """
        删除指定缓存条目

        Returns:
            是否成功删除
        """
        key = self.make_key(character_name, topic)

        with self._lock:
            if key in self._cache_index:
                self._evict_key(key)
                logger.info(f"Cache deleted: {key}")
                return True
            return False

    def clear(self):
        """清空所有缓存"""
        with self._lock:
            count = len(self._cache_index)
            self._cache_index.clear()
            self._redis.delete(self.CACHE_KEY)
            self._redis.delete(self.TIMESTAMP_KEY)
            logger.info(f"Cache cleared: {count} entries removed")

    def get_all(self) -> List[TopicProfileCacheEntry]:
        """获取所有缓存条目"""
        with self._lock:
            return list(self._cache_index.values())

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            return {
                "size": len(self._cache_index),
                "max_size": self._max_size,
                "utilization": f"{len(self._cache_index) / self._max_size * 100:.1f}%",
                "redis_keys": self._redis.hlen(self.CACHE_KEY),
            }

    def get_by_prefix(self, character_name: str) -> List[TopicProfileCacheEntry]:
        """获取指定角色的所有缓存条目"""
        with self._lock:
            return [
                entry for entry in self._cache_index.values()
                if entry.character_name == character_name
            ]

    def reload(self):
        """重新从 Redis 加载缓存"""
        self._cache_index.clear()
        self._load_from_redis()


# 全局缓存实例
_global_cache: Optional[TopicProfileCache] = None


def get_topic_cache() -> TopicProfileCache:
    """获取全局话题缓存实例"""
    global _global_cache
    if _global_cache is None:
        _global_cache = TopicProfileCache(max_size=100)
    return _global_cache