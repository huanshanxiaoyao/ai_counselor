"""
Offline Character Profile System
人物设定模块 - 支持离线预置基础设定和话题相关设定缓存
"""
from .cache_manager import TopicProfileCache, get_topic_cache
from .profile_loader import BaseProfileLoader, get_base_profile_loader
from .candidate_queue import CandidateQueue, get_candidate_queue
from .profile_generator import generate_offline_profile, save_generated_profile

__all__ = [
    'TopicProfileCache', 'get_topic_cache',
    'BaseProfileLoader', 'get_base_profile_loader',
    'CandidateQueue', 'get_candidate_queue',
    'generate_offline_profile', 'save_generated_profile',
]
