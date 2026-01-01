"""
ArcadiaForge Web Interface
==========================

Real-time progress dashboard for monitoring autonomous coding sessions.
"""

from .dashboard import DashboardServer, broadcast_update, start_dashboard

__all__ = ["DashboardServer", "broadcast_update", "start_dashboard"]
