"""
候选队列管理器
用于跟踪被推荐但没有离线基础设定的角色
当推荐次数达到阈值时，自动触发生成离线基础设定
"""
import json
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import redis

logger = logging.getLogger(__name__)


@dataclass
class CandidateEntry:
    """候选角色条目"""
    name: str           # 角色名
    era: str            # 时代
    recommend_count: int = 0  # 被推荐次数
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    status: str = 'pending'  # pending, generating, completed, failed
    generated_profile_path: Optional[str] = None  # 生成后的配置文件路径

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'era': self.era,
            'recommend_count': self.recommend_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'status': self.status,
            'generated_profile_path': self.generated_profile_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CandidateEntry':
        entry = cls(
            name=data['name'],
            era=data.get('era', ''),
            recommend_count=data.get('recommend_count', 0),
            created_at=datetime.fromisoformat(data['created_at']) if 'created_at' in data else datetime.now(),
            updated_at=datetime.fromisoformat(data['updated_at']) if 'updated_at' in data else datetime.now(),
            status=data.get('status', 'pending'),
            generated_profile_path=data.get('generated_profile_path'),
        )
        return entry


class CandidateQueue:
    """
    候选队列管理器

    使用 Redis Hash 存储：
    - key: "roundtable:candidate_queue"
    - field: 角色名
    - value: JSON序列化的 CandidateEntry

    特性：
    - 自动触发：当 recommend_count >= trigger_threshold 时触发生成任务
    - 线程安全
    - 后台线程执行生成任务
    """

    _instance: Optional['CandidateQueue'] = None
    _lock = threading.Lock()

    # Redis key
    QUEUE_KEY = "roundtable:candidate_queue"

    def __new__(cls, trigger_threshold: int = 2):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, trigger_threshold: int = 2):
        if self._initialized:
            return
        self._initialized = True
        self._trigger_threshold = trigger_threshold

        # Redis connection - use REDIS_HOST env var (default to localhost for local dev)
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', '6379'))
        self._redis = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=0,
            decode_responses=True
        )

        # Thread pool for background generation
        self._executor = None

        logger.info(f"CandidateQueue initialized with trigger_threshold={trigger_threshold}")

    def _get_executor(self):
        """获取线程池Executor（延迟初始化）"""
        if self._executor is None:
            from concurrent.futures import ThreadPoolExecutor
            self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='profile_generator_')
        return self._executor

    def add_candidate(self, name: str, era: str = '') -> CandidateEntry:
        """
        添加候选角色

        Args:
            name: 角色名
            era: 时代（可选）

        Returns:
            更新后的 CandidateEntry
        """
        key = f"{name}"

        with self._lock:
            existing = self._redis.hget(self.QUEUE_KEY, key)

            if existing:
                entry_data = json.loads(existing)
                entry = CandidateEntry.from_dict(entry_data)
                entry.recommend_count += 1
                entry.updated_at = datetime.now()
            else:
                entry = CandidateEntry(
                    name=name,
                    era=era,
                    recommend_count=1,
                )

            # 保存回 Redis
            self._redis.hset(self.QUEUE_KEY, key, json.dumps(entry.to_dict(), ensure_ascii=False))
            logger.info(f"Added candidate: {name}, count: {entry.recommend_count}")

            # 检查是否达到触发阈值
            if entry.recommend_count >= self._trigger_threshold and entry.status == 'pending':
                self._trigger_generation(entry)

            return entry

    def get_candidate(self, name: str) -> Optional[CandidateEntry]:
        """获取指定候选角色"""
        data = self._redis.hget(self.QUEUE_KEY, name)
        if data:
            return CandidateEntry.from_dict(json.loads(data))
        return None

    def get_all_candidates(self) -> List[CandidateEntry]:
        """获取所有候选角色"""
        all_data = self._redis.hgetall(self.QUEUE_KEY)
        candidates = []
        for name, data in all_data.items():
            try:
                candidates.append(CandidateEntry.from_dict(json.loads(data)))
            except Exception as e:
                logger.error(f"Failed to parse candidate {name}: {e}")
        return candidates

    def get_pending_candidates(self) -> List[CandidateEntry]:
        """获取待处理的候选角色"""
        return [c for c in self.get_all_candidates() if c.status == 'pending']

    def get_stats(self) -> Dict:
        """获取统计信息"""
        candidates = self.get_all_candidates()
        return {
            'total': len(candidates),
            'pending': len([c for c in candidates if c.status == 'pending']),
            'generating': len([c for c in candidates if c.status == 'generating']),
            'completed': len([c for c in candidates if c.status == 'completed']),
            'failed': len([c for c in candidates if c.status == 'failed']),
        }

    def remove_candidate(self, name: str) -> bool:
        """移除候选角色"""
        result = self._redis.hdel(self.QUEUE_KEY, name)
        return result > 0

    def reset_count(self, name: str) -> Optional[CandidateEntry]:
        """重置推荐计数"""
        entry = self.get_candidate(name)
        if entry:
            entry.recommend_count = 0
            entry.status = 'pending'
            entry.updated_at = datetime.now()
            self._redis.hset(self.QUEUE_KEY, name, json.dumps(entry.to_dict(), ensure_ascii=False))
        return entry

    def clear(self):
        """清空所有候选"""
        self._redis.delete(self.QUEUE_KEY)

    def update_status(self, name: str, status: str, profile_path: str = None):
        """更新候选状态"""
        entry = self.get_candidate(name)
        if entry:
            entry.status = status
            entry.updated_at = datetime.now()
            if profile_path:
                entry.generated_profile_path = profile_path
            self._redis.hset(self.QUEUE_KEY, name, json.dumps(entry.to_dict(), ensure_ascii=False))

    def _trigger_generation(self, entry: CandidateEntry):
        """触发生成任务"""
        logger.info(f"Triggering profile generation for: {entry.name}")

        def generate_profile():
            try:
                self.update_status(entry.name, 'generating')

                # 调用生成器生成离线基础设定
                from .profile_generator import generate_offline_profile
                profile_path = generate_offline_profile(entry.name, entry.era)

                if profile_path:
                    self.update_status(entry.name, 'completed', profile_path)
                    logger.info(f"Profile generation completed: {entry.name} -> {profile_path}")

                    # 重新加载基础设定
                    from .profile_loader import get_base_profile_loader
                    loader = get_base_profile_loader()
                    loader.reload()
                else:
                    self.update_status(entry.name, 'failed')
                    logger.error(f"Profile generation failed: {entry.name}")

            except Exception as e:
                logger.exception(f"Profile generation error for {entry.name}: {e}")
                self.update_status(entry.name, 'failed')

        # 提交到线程池执行
        future = self._get_executor().submit(generate_profile)
        logger.info(f"Profile generation task submitted: {entry.name}")

    def trigger_generation(self, name: str) -> bool:
        """
        手动触发生成

        Returns:
            是否成功触发（候选角色存在且状态为pending/generating时）
        """
        entry = self.get_candidate(name)
        if entry and entry.status in ('pending', 'failed'):
            self._trigger_generation(entry)
            return True
        return False


def get_candidate_queue() -> CandidateQueue:
    """获取候选队列单例"""
    return CandidateQueue()
