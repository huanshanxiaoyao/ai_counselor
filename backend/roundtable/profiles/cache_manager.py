"""
话题相关设定缓存管理器
优先使用 Redis，当 Redis 不可用时降级到内存缓存（FIFO 策略）
"""
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

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


class BaseCache:
    """缓存基类"""

    def get(self, character_name: str, topic: str) -> Optional[TopicProfileCacheEntry]:
        raise NotImplementedError()

    def set(
        self,
        character_name: str,
        topic: str,
        viewpoints: Dict[str, str] = None,
        representative_articles: List[Dict] = None,
        language_style: Dict[str, Any] = None,
        temporal_constraints: Dict[str, Any] = None
    ) -> TopicProfileCacheEntry:
        raise NotImplementedError()

    def delete(self, character_name: str, topic: str) -> bool:
        raise NotImplementedError()

    def clear(self):
        raise NotImplementedError()

    def get_all(self) -> List[TopicProfileCacheEntry]:
        raise NotImplementedError()

    def get_stats(self) -> Dict[str, Any]:
        raise NotImplementedError()


class InMemoryCache(BaseCache):
    """纯内存缓存实现（FIFO 淘汰策略）"""

    def __init__(self, max_size: int = 100):
        self._max_size = max_size
        self._cache: Dict[str, TopicProfileCacheEntry] = {}
        self._order: List[str] = []  # 用于 FIFO 淘汰
        self._lock = threading.Lock()

    @staticmethod
    def make_key(character_name: str, topic: str) -> str:
        return f"{character_name}:{topic}"

    def get(self, character_name: str, topic: str) -> Optional[TopicProfileCacheEntry]:
        key = self.make_key(character_name, topic)
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                logger.debug(f"[InMemory] Cache hit: {key}")
            else:
                logger.debug(f"[InMemory] Cache miss: {key}")
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
        key = self.make_key(character_name, topic)
        with self._lock:
            if key in self._cache:
                # 更新现有条目
                entry = self._cache[key]
                entry.viewpoints = viewpoints or {}
                entry.representative_articles = representative_articles or []
                entry.language_style = language_style or {}
                entry.temporal_constraints = temporal_constraints or {}
                entry.created_at = datetime.now()
                logger.debug(f"[InMemory] Cache updated: {key}")
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
                self._cache[key] = entry
                self._order.append(key)
                logger.debug(f"[InMemory] Cache set: {key}")

                # FIFO 淘汰
                if len(self._cache) > self._max_size:
                    oldest_key = self._order.pop(0)
                    del self._cache[oldest_key]
                    logger.info(f"[InMemory] Cache evicted (FIFO): {oldest_key}")

            return entry

    def delete(self, character_name: str, topic: str) -> bool:
        key = self.make_key(character_name, topic)
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                if key in self._order:
                    self._order.remove(key)
                logger.info(f"[InMemory] Cache deleted: {key}")
                return True
            return False

    def clear(self):
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._order.clear()
            logger.info(f"[InMemory] Cache cleared: {count} entries removed")

    def get_all(self) -> List[TopicProfileCacheEntry]:
        with self._lock:
            return list(self._cache.values())

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "utilization": f"{len(self._cache) / self._max_size * 100:.1f}%",
                "backend": "memory"
            }


class RedisCache(BaseCache):
    """Redis 缓存实现"""

    # Redis keys
    CACHE_KEY = "roundtable:topic_profile_cache"
    TIMESTAMP_KEY = "roundtable:topic_profile_cache:ts"

    def __init__(self, max_size: int = 100):
        self._max_size = max_size
        self._cache_index: Dict[str, TopicProfileCacheEntry] = {}
        self._lock = threading.Lock()
        self._redis_available = False

        # Redis connection
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', '6379'))

        try:
            import redis
            self._redis = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=0,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=5
            )

            # 测试连接
            self._redis.ping()
            self._redis_available = True

            # 预热缓存
            self._load_from_redis()
            logger.info(f"[Redis] Cache initialized with max_size={max_size}, redis={redis_host}:{redis_port}")
        except Exception as e:
            logger.warning(f"[Redis] Redis connection failed, will use memory-only mode: {e}")
            self._redis_available = False

    def _load_from_redis(self):
        """从 Redis 加载缓存到内存索引"""
        if not self._redis_available:
            return
        try:
            all_data = self._redis.hgetall(self.CACHE_KEY)
            for key, data in all_data.items():
                try:
                    entry_data = json.loads(data)
                    entry = TopicProfileCacheEntry.from_dict(entry_data)
                    self._cache_index[key] = entry
                except Exception as e:
                    logger.error(f"[Redis] Failed to parse cache entry {key}: {e}")
            logger.info(f"[Redis] Loaded {len(self._cache_index)} entries from Redis")
        except Exception as e:
            logger.error(f"[Redis] Failed to load cache from Redis: {e}")
            self._redis_available = False

    @staticmethod
    def make_key(character_name: str, topic: str) -> str:
        return f"{character_name}:{topic}"

    def get(self, character_name: str, topic: str) -> Optional[TopicProfileCacheEntry]:
        key = self.make_key(character_name, topic)
        with self._lock:
            if key not in self._cache_index:
                logger.debug(f"[Redis] Cache miss: {key}")
                return None

            entry = self._cache_index[key]
            logger.debug(f"[Redis] Cache hit: {key}")

            # 更新 Redis 时间戳（可选操作，失败不影响）
            if self._redis_available:
                try:
                    timestamp = datetime.now().timestamp()
                    self._redis.zadd(self.TIMESTAMP_KEY, {key: timestamp})
                except Exception:
                    pass  # 忽略 Redis 操作失败

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
        key = self.make_key(character_name, topic)
        with self._lock:
            if key in self._cache_index:
                entry = self._cache_index[key]
                entry.viewpoints = viewpoints or {}
                entry.representative_articles = representative_articles or []
                entry.language_style = language_style or {}
                entry.temporal_constraints = temporal_constraints or {}
                entry.created_at = datetime.now()
                logger.debug(f"[Redis] Cache updated: {key}")
            else:
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
                logger.debug(f"[Redis] Cache set: {key}")

            # 保存到 Redis（失败则降级为纯内存）
            if self._redis_available:
                try:
                    self._redis.hset(self.CACHE_KEY, key, json.dumps(entry.to_dict(), ensure_ascii=False))
                    timestamp = datetime.now().timestamp()
                    self._redis.zadd(self.TIMESTAMP_KEY, {key: timestamp})
                except Exception as e:
                    logger.warning(f"[Redis] Failed to write to Redis, switching to memory-only mode: {e}")
                    self._redis_available = False

            # 内存 FIFO 淘汰（不依赖 Redis）
            if len(self._cache_index) > self._max_size:
                oldest_key = next(iter(self._cache_index))
                self._evict_key(oldest_key)
                logger.info(f"[Redis] Cache evicted (FIFO): {oldest_key}")

            return entry

    def _evict_key(self, key: str):
        """淘汰指定的缓存键"""
        if key in self._cache_index:
            del self._cache_index[key]
        # 如果 Redis 可用，尝试从 Redis 删除
        if self._redis_available:
            try:
                self._redis.hdel(self.CACHE_KEY, key)
                self._redis.zrem(self.TIMESTAMP_KEY, key)
            except Exception:
                pass  # 忽略 Redis 操作失败

    def delete(self, character_name: str, topic: str) -> bool:
        key = self.make_key(character_name, topic)
        with self._lock:
            if key in self._cache_index:
                self._evict_key(key)
                logger.info(f"[Redis] Cache deleted: {key}")
                return True
            return False

    def clear(self):
        with self._lock:
            count = len(self._cache_index)
            self._cache_index.clear()
            if self._redis_available:
                try:
                    self._redis.delete(self.CACHE_KEY)
                    self._redis.delete(self.TIMESTAMP_KEY)
                except Exception:
                    self._redis_available = False
            logger.info(f"[Redis] Cache cleared: {count} entries removed")

    def get_all(self) -> List[TopicProfileCacheEntry]:
        with self._lock:
            return list(self._cache_index.values())

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "size": len(self._cache_index),
                "max_size": self._max_size,
                "utilization": f"{len(self._cache_index) / self._max_size * 100:.1f}%",
                "backend": "redis" if self._redis_available else "redis-memory-fallback"
            }


class TopicProfileCache:
    """
    话题设定缓存管理器 - 带有 Redis 降级功能

    优先使用 Redis，当 Redis 不可用时自动降级到内存缓存
    """

    _instance: Optional['TopicProfileCache'] = None
    _lock = threading.Lock()

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

        # 尝试使用 Redis，失败则降级到内存缓存
        self._backend: BaseCache
        try:
            self._backend = RedisCache(max_size=max_size)
            logger.info("TopicProfileCache using Redis backend")
        except Exception as e:
            logger.warning(f"Redis not available, falling back to in-memory cache: {e}")
            self._backend = InMemoryCache(max_size=max_size)
            logger.info("TopicProfileCache using in-memory backend")

    def get(self, character_name: str, topic: str) -> Optional[TopicProfileCacheEntry]:
        return self._backend.get(character_name, topic)

    def set(
        self,
        character_name: str,
        topic: str,
        viewpoints: Dict[str, str] = None,
        representative_articles: List[Dict] = None,
        language_style: Dict[str, Any] = None,
        temporal_constraints: Dict[str, Any] = None
    ) -> TopicProfileCacheEntry:
        return self._backend.set(
            character_name, topic, viewpoints,
            representative_articles, language_style, temporal_constraints
        )

    def delete(self, character_name: str, topic: str) -> bool:
        return self._backend.delete(character_name, topic)

    def clear(self):
        self._backend.clear()

    def get_all(self) -> List[TopicProfileCacheEntry]:
        return self._backend.get_all()

    def get_stats(self) -> Dict[str, Any]:
        return self._backend.get_stats()

    def get_by_prefix(self, character_name: str) -> List[TopicProfileCacheEntry]:
        """获取指定角色的所有缓存条目"""
        return [
            entry for entry in self._backend.get_all()
            if entry.character_name == character_name
        ]


# 全局缓存实例
_global_cache: Optional[TopicProfileCache] = None


def get_topic_cache() -> TopicProfileCache:
    """获取全局话题缓存实例"""
    global _global_cache
    if _global_cache is None:
        _global_cache = TopicProfileCache(max_size=100)
    return _global_cache
