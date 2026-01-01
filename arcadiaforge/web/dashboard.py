"""
Real-Time Progress Dashboard
============================

FastAPI-based web dashboard with WebSocket for real-time updates.
Displays feature progress, session status, and activity logs.

Usage:
    # Start the dashboard server
    python -m arcadiaforge dashboard

    # Or programmatically
    from arcadiaforge.web import start_dashboard
    start_dashboard(port=8080, project_dir="/path/to/project")
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware


# =============================================================================
# Dashboard Server
# =============================================================================

class DashboardServer:
    """
    Real-time dashboard server with WebSocket support.

    Maintains connections and broadcasts updates to all clients.
    """

    def __init__(self, project_dir: Path):
        """
        Initialize the dashboard server.

        Args:
            project_dir: Project root directory for database access
        """
        self.project_dir = Path(project_dir)
        self.app = FastAPI(title="ArcadiaForge Dashboard")
        self.connections: List[WebSocket] = []
        self.activity_log: List[Dict[str, Any]] = []
        self._setup_routes()
        self._setup_cors()

    def _setup_cors(self):
        """Configure CORS for local development."""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self):
        """Set up API routes."""

        @self.app.get("/", response_class=HTMLResponse)
        async def dashboard():
            """Serve the dashboard HTML."""
            return get_dashboard_html()

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket endpoint for real-time updates."""
            await websocket.accept()
            self.connections.append(websocket)
            try:
                # Send initial state
                status = await self.get_current_status()
                await websocket.send_json(status)

                # Keep connection alive
                while True:
                    try:
                        # Ping-pong to keep connection alive
                        data = await asyncio.wait_for(
                            websocket.receive_text(),
                            timeout=30.0
                        )
                        if data == "ping":
                            await websocket.send_text("pong")
                    except asyncio.TimeoutError:
                        # Send heartbeat
                        await websocket.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                if websocket in self.connections:
                    self.connections.remove(websocket)

        @self.app.get("/api/status")
        async def get_status():
            """Get current project status."""
            return await self.get_current_status()

        @self.app.get("/api/features")
        async def get_features():
            """Get all features with status."""
            return await self.get_features_list()

        @self.app.get("/api/activity")
        async def get_activity():
            """Get recent activity log."""
            return {"activities": self.activity_log[-50:]}  # Last 50 activities

        @self.app.get("/api/sessions")
        async def get_sessions():
            """Get session history."""
            return await self.get_session_history()

    async def get_current_status(self) -> Dict[str, Any]:
        """Get current project status from database."""
        try:
            from arcadiaforge.db.connection import get_session_maker
            from arcadiaforge.db.models import Feature, Session, WarmMemory
            from sqlalchemy import select, func

            session_maker = get_session_maker()
            async with session_maker() as session:
                # Get feature stats
                result = await session.execute(select(Feature))
                features = result.scalars().all()

                total = len(features)
                passing = sum(1 for f in features if f.passes)
                blocked = sum(1 for f in features if (f.feature_metadata or {}).get("blocked_by_capability"))

                # Get current session info
                result = await session.execute(
                    select(Session).order_by(Session.id.desc()).limit(1)
                )
                current_session = result.scalar_one_or_none()

                # Get recent warm memory
                result = await session.execute(
                    select(WarmMemory).order_by(WarmMemory.session_id.desc()).limit(5)
                )
                recent_sessions = result.scalars().all()

                return {
                    "type": "status",
                    "features": {
                        "total": total,
                        "passing": passing,
                        "failing": total - passing - blocked,
                        "blocked": blocked,
                    },
                    "completion": (passing / total * 100) if total > 0 else 0,
                    "session": {
                        "id": current_session.id if current_session else 0,
                        "status": current_session.status if current_session else "unknown",
                        "started": current_session.start_time.isoformat() if current_session else None,
                    },
                    "history": [
                        {
                            "session_id": s.session_id,
                            "completed": s.features_completed,
                            "duration": s.duration_seconds,
                        }
                        for s in recent_sessions
                    ],
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as e:
            return {
                "type": "status",
                "error": str(e),
                "features": {"total": 0, "passing": 0, "failing": 0, "blocked": 0},
                "completion": 0,
                "timestamp": datetime.now().isoformat(),
            }

    async def get_features_list(self) -> Dict[str, Any]:
        """Get all features with details."""
        try:
            from arcadiaforge.db.connection import get_session_maker
            from arcadiaforge.db.models import Feature
            from sqlalchemy import select

            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(select(Feature).order_by(Feature.index))
                features = result.scalars().all()

                return {
                    "features": [
                        {
                            "index": f.index,
                            "description": f.description,
                            "category": f.category,
                            "passes": f.passes,
                            "blocked": bool((f.feature_metadata or {}).get("blocked_by_capability")),
                            "verified_at": f.verified_at.isoformat() if f.verified_at else None,
                        }
                        for f in features
                    ]
                }
        except Exception as e:
            return {"features": [], "error": str(e)}

    async def get_session_history(self) -> Dict[str, Any]:
        """Get session history from database."""
        try:
            from arcadiaforge.db.connection import get_session_maker
            from arcadiaforge.db.models import WarmMemory
            from sqlalchemy import select

            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(WarmMemory).order_by(WarmMemory.session_id.desc()).limit(20)
                )
                sessions = result.scalars().all()

                return {
                    "sessions": [
                        {
                            "id": s.session_id,
                            "started": s.started_at.isoformat(),
                            "ended": s.ended_at.isoformat(),
                            "duration": s.duration_seconds,
                            "features_completed": s.features_completed,
                            "features_regressed": s.features_regressed,
                            "ending_state": s.ending_state,
                        }
                        for s in sessions
                    ]
                }
        except Exception as e:
            return {"sessions": [], "error": str(e)}

    async def broadcast(self, data: Dict[str, Any]):
        """Broadcast update to all connected clients."""
        if not self.connections:
            return

        message = json.dumps(data)
        disconnected = []

        for websocket in self.connections:
            try:
                await websocket.send_text(message)
            except Exception:
                disconnected.append(websocket)

        # Clean up disconnected clients
        for ws in disconnected:
            if ws in self.connections:
                self.connections.remove(ws)

    def add_activity(self, activity_type: str, message: str, data: dict = None):
        """Add an activity to the log and broadcast it."""
        activity = {
            "type": activity_type,
            "message": message,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        }
        self.activity_log.append(activity)

        # Keep only last 100 activities
        if len(self.activity_log) > 100:
            self.activity_log = self.activity_log[-100:]

        # Broadcast activity
        asyncio.create_task(self.broadcast({
            "type": "activity",
            "activity": activity,
        }))


# =============================================================================
# Global Dashboard Instance
# =============================================================================

_dashboard: Optional[DashboardServer] = None


def get_dashboard() -> Optional[DashboardServer]:
    """Get the global dashboard instance."""
    return _dashboard


def set_dashboard(dashboard: DashboardServer):
    """Set the global dashboard instance."""
    global _dashboard
    _dashboard = dashboard


async def broadcast_update(data: Dict[str, Any]):
    """Broadcast update to dashboard if running."""
    if _dashboard:
        await _dashboard.broadcast(data)


def log_activity(activity_type: str, message: str, data: dict = None):
    """Log activity to dashboard if running."""
    if _dashboard:
        _dashboard.add_activity(activity_type, message, data)


# =============================================================================
# Dashboard HTML Template
# =============================================================================

def get_dashboard_html() -> str:
    """Return the dashboard HTML."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ArcadiaForge Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .status-passing { color: #4ade80; }
        .status-failing { color: #f87171; }
        .status-blocked { color: #fbbf24; }
        .activity-item { animation: fadeIn 0.3s ease-in; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
        .pulse { animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    </style>
</head>
<body class="bg-gray-900 text-white min-h-screen">
    <div class="container mx-auto px-4 py-8 max-w-7xl">
        <!-- Header -->
        <div class="flex justify-between items-center mb-8">
            <h1 class="text-3xl font-bold text-blue-400">ArcadiaForge</h1>
            <div class="flex items-center gap-2">
                <span id="connection-status" class="w-3 h-3 rounded-full bg-red-500"></span>
                <span id="connection-text" class="text-gray-400">Disconnected</span>
            </div>
        </div>

        <!-- Stats Cards -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div class="bg-gray-800 rounded-xl p-6 shadow-lg">
                <h2 class="text-sm text-gray-400 uppercase tracking-wider">Completion</h2>
                <p class="text-4xl font-bold text-green-400 mt-2" id="completion">0%</p>
                <div class="mt-3 h-2 bg-gray-700 rounded-full overflow-hidden">
                    <div id="completion-bar" class="h-full bg-green-500 transition-all duration-500" style="width: 0%"></div>
                </div>
            </div>
            <div class="bg-gray-800 rounded-xl p-6 shadow-lg">
                <h2 class="text-sm text-gray-400 uppercase tracking-wider">Features</h2>
                <p class="text-4xl font-bold text-blue-400 mt-2">
                    <span id="features-passing">0</span>/<span id="features-total">0</span>
                </p>
                <p class="text-sm text-gray-500 mt-1">
                    <span id="features-blocked" class="text-yellow-400">0</span> blocked
                </p>
            </div>
            <div class="bg-gray-800 rounded-xl p-6 shadow-lg">
                <h2 class="text-sm text-gray-400 uppercase tracking-wider">Session</h2>
                <p class="text-4xl font-bold text-purple-400 mt-2" id="session-id">#0</p>
                <p class="text-sm text-gray-500 mt-1" id="session-status">Unknown</p>
            </div>
            <div class="bg-gray-800 rounded-xl p-6 shadow-lg">
                <h2 class="text-sm text-gray-400 uppercase tracking-wider">Last Update</h2>
                <p class="text-2xl font-bold text-gray-300 mt-2" id="last-update">--:--:--</p>
                <p class="text-sm text-gray-500 mt-1" id="update-ago">Never</p>
            </div>
        </div>

        <!-- Main Content Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Feature List -->
            <div class="lg:col-span-2 bg-gray-800 rounded-xl p-6 shadow-lg">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-xl font-semibold">Features</h2>
                    <div class="flex gap-2">
                        <button onclick="filterFeatures('all')" class="px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-sm">All</button>
                        <button onclick="filterFeatures('passing')" class="px-3 py-1 rounded bg-gray-700 hover:bg-green-600 text-sm">Passing</button>
                        <button onclick="filterFeatures('failing')" class="px-3 py-1 rounded bg-gray-700 hover:bg-red-600 text-sm">Failing</button>
                        <button onclick="filterFeatures('blocked')" class="px-3 py-1 rounded bg-gray-700 hover:bg-yellow-600 text-sm">Blocked</button>
                    </div>
                </div>
                <div id="feature-list" class="space-y-2 max-h-96 overflow-y-auto">
                    <p class="text-gray-500">Loading features...</p>
                </div>
            </div>

            <!-- Activity Log -->
            <div class="bg-gray-800 rounded-xl p-6 shadow-lg">
                <h2 class="text-xl font-semibold mb-4">Activity</h2>
                <div id="activity-log" class="space-y-2 max-h-96 overflow-y-auto font-mono text-sm">
                    <p class="text-gray-500">Waiting for activity...</p>
                </div>
            </div>
        </div>

        <!-- Session History -->
        <div class="mt-6 bg-gray-800 rounded-xl p-6 shadow-lg">
            <h2 class="text-xl font-semibold mb-4">Session History</h2>
            <div class="overflow-x-auto">
                <table class="w-full text-sm">
                    <thead class="text-gray-400 border-b border-gray-700">
                        <tr>
                            <th class="text-left py-2">Session</th>
                            <th class="text-left py-2">Duration</th>
                            <th class="text-left py-2">Completed</th>
                            <th class="text-left py-2">Regressed</th>
                            <th class="text-left py-2">Status</th>
                        </tr>
                    </thead>
                    <tbody id="session-history" class="text-gray-300">
                        <tr><td colspan="5" class="py-4 text-gray-500">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let features = [];
        let currentFilter = 'all';
        let lastUpdateTime = null;

        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

            ws.onopen = () => {
                document.getElementById('connection-status').className = 'w-3 h-3 rounded-full bg-green-500';
                document.getElementById('connection-text').textContent = 'Connected';
            };

            ws.onclose = () => {
                document.getElementById('connection-status').className = 'w-3 h-3 rounded-full bg-red-500';
                document.getElementById('connection-text').textContent = 'Disconnected';
                setTimeout(connect, 3000);
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleUpdate(data);
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        }

        function handleUpdate(data) {
            lastUpdateTime = new Date();
            updateTimestamp();

            if (data.type === 'status') {
                updateStatus(data);
            } else if (data.type === 'activity') {
                addActivity(data.activity);
            } else if (data.type === 'feature_update') {
                loadFeatures();
            }
        }

        function updateStatus(data) {
            if (data.features) {
                document.getElementById('features-passing').textContent = data.features.passing;
                document.getElementById('features-total').textContent = data.features.total;
                document.getElementById('features-blocked').textContent = data.features.blocked;
            }

            if (data.completion !== undefined) {
                const pct = data.completion.toFixed(1);
                document.getElementById('completion').textContent = pct + '%';
                document.getElementById('completion-bar').style.width = pct + '%';
            }

            if (data.session) {
                document.getElementById('session-id').textContent = '#' + data.session.id;
                document.getElementById('session-status').textContent = data.session.status;
            }

            if (data.history) {
                updateSessionHistory(data.history);
            }
        }

        function addActivity(activity) {
            const log = document.getElementById('activity-log');
            if (log.querySelector('.text-gray-500')) {
                log.innerHTML = '';
            }

            const time = new Date(activity.timestamp).toLocaleTimeString();
            const icon = getActivityIcon(activity.type);

            const entry = document.createElement('div');
            entry.className = 'activity-item p-2 bg-gray-700 rounded text-gray-300';
            entry.innerHTML = `<span class="text-gray-500">${time}</span> ${icon} ${activity.message}`;

            log.prepend(entry);

            // Keep only last 50 entries
            while (log.children.length > 50) {
                log.removeChild(log.lastChild);
            }
        }

        function getActivityIcon(type) {
            const icons = {
                'feature_complete': '✅',
                'feature_fail': '❌',
                'session_start': '🚀',
                'session_end': '🏁',
                'error': '⚠️',
                'tool': '🔧',
                'checkpoint': '💾',
            };
            return icons[type] || '📝';
        }

        async function loadFeatures() {
            try {
                const response = await fetch('/api/features');
                const data = await response.json();
                features = data.features || [];
                renderFeatures();
            } catch (error) {
                console.error('Failed to load features:', error);
            }
        }

        function renderFeatures() {
            const list = document.getElementById('feature-list');
            const filtered = features.filter(f => {
                if (currentFilter === 'all') return true;
                if (currentFilter === 'passing') return f.passes;
                if (currentFilter === 'failing') return !f.passes && !f.blocked;
                if (currentFilter === 'blocked') return f.blocked;
                return true;
            });

            if (filtered.length === 0) {
                list.innerHTML = '<p class="text-gray-500">No features match filter</p>';
                return;
            }

            list.innerHTML = filtered.map(f => {
                let statusClass = 'status-failing';
                let statusText = 'Failing';
                if (f.passes) {
                    statusClass = 'status-passing';
                    statusText = 'Passing';
                } else if (f.blocked) {
                    statusClass = 'status-blocked';
                    statusText = 'Blocked';
                }

                return `
                    <div class="p-3 bg-gray-700 rounded flex justify-between items-center">
                        <div>
                            <span class="text-gray-400">#${f.index}</span>
                            <span class="ml-2">${f.description.substring(0, 60)}${f.description.length > 60 ? '...' : ''}</span>
                        </div>
                        <span class="${statusClass} font-medium">${statusText}</span>
                    </div>
                `;
            }).join('');
        }

        function filterFeatures(filter) {
            currentFilter = filter;
            renderFeatures();
        }

        function updateSessionHistory(history) {
            const tbody = document.getElementById('session-history');
            if (!history || history.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="py-4 text-gray-500">No session history</td></tr>';
                return;
            }

            tbody.innerHTML = history.map(s => {
                const duration = s.duration ? Math.round(s.duration / 60) + ' min' : '-';
                return `
                    <tr class="border-b border-gray-700">
                        <td class="py-2">#${s.session_id}</td>
                        <td class="py-2">${duration}</td>
                        <td class="py-2 text-green-400">+${s.completed || 0}</td>
                        <td class="py-2 text-red-400">${s.regressed ? '-' + s.regressed : '-'}</td>
                        <td class="py-2">${s.ending_state || '-'}</td>
                    </tr>
                `;
            }).join('');
        }

        function updateTimestamp() {
            if (!lastUpdateTime) return;

            document.getElementById('last-update').textContent = lastUpdateTime.toLocaleTimeString();

            const updateAgo = () => {
                if (!lastUpdateTime) return;
                const seconds = Math.floor((new Date() - lastUpdateTime) / 1000);
                let text = 'Just now';
                if (seconds >= 60) {
                    const minutes = Math.floor(seconds / 60);
                    text = `${minutes}m ago`;
                } else if (seconds >= 10) {
                    text = `${seconds}s ago`;
                }
                document.getElementById('update-ago').textContent = text;
            };

            updateAgo();
            setInterval(updateAgo, 5000);
        }

        // Initialize
        connect();
        loadFeatures();

        // Periodic refresh
        setInterval(loadFeatures, 30000);
    </script>
</body>
</html>'''


# =============================================================================
# Server Startup
# =============================================================================

def start_dashboard(port: int = 8080, project_dir: Path = None, open_browser: bool = True):
    """
    Start the dashboard server.

    Args:
        port: Port to run on (default: 8080)
        project_dir: Project directory (default: current directory)
        open_browser: Whether to open browser automatically
    """
    import uvicorn
    import webbrowser
    import threading

    if project_dir is None:
        project_dir = Path.cwd()

    # Create and register dashboard
    dashboard = DashboardServer(project_dir)
    set_dashboard(dashboard)

    # Open browser after slight delay
    if open_browser:
        def open_browser_delayed():
            import time
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}")

        threading.Thread(target=open_browser_delayed, daemon=True).start()

    print(f"Starting ArcadiaForge Dashboard at http://localhost:{port}")

    # Run server
    uvicorn.run(dashboard.app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    start_dashboard()
