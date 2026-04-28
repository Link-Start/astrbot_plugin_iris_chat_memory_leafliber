"""
API 路由模块

提供六类API：
- Memory API: 记忆管理（L1/L2/L3）
- Profile API: 画像管理
- Stats API: 统计数据
- Data API: 导入导出
- Manage API: 管理操作
- Hidden Config API: 隐藏参数管理
"""
from .memory import memory_bp
from .profile import profile_bp
from .stats import stats_bp
from .data_routes import data_bp
from .manage_routes import manage_bp
from .hidden_config_routes import hidden_config_bp

__all__ = ['memory_bp', 'profile_bp', 'stats_bp', 'data_bp', 'manage_bp', 'hidden_config_bp']
