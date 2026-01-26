"""Telemetry module for tracking MP3 playback events."""
import aiosqlite
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Database path (in repo root)
DB_PATH = Path(__file__).resolve().parents[2] / "telemetry.db"


class PlaybackEvent(BaseModel):
    """Model for a playback event."""
    id: int
    track_name: str
    device_name: Optional[str] = None
    device_ip: Optional[str] = None
    timestamp_utc: str
    status: str
    error_message: Optional[str] = None


class DailyStats(BaseModel):
    """Model for daily statistics."""
    date: str
    track_name: str
    play_count: int


class WeeklyStats(BaseModel):
    """Model for weekly statistics."""
    year: int
    week: int
    track_name: str
    play_count: int


class MonthlyStats(BaseModel):
    """Model for monthly statistics."""
    year: int
    month: int
    track_name: str
    play_count: int


class TopTrack(BaseModel):
    """Model for top tracks."""
    track_name: str
    play_count: int
    last_played: str


class HealthStatus(BaseModel):
    """Model for health status."""
    status: str
    database_connected: bool
    total_events: int
    message: str


class TelemetryService:
    """Service for managing telemetry data."""

    def __init__(self, db_path: Path = DB_PATH):
        """Initialize the telemetry service.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._initialized = False

    async def initialize(self):
        """Initialize the database and create schema if needed."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Create playback_events table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS playback_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        track_name TEXT NOT NULL,
                        device_name TEXT,
                        device_ip TEXT,
                        timestamp_utc TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error_message TEXT
                    )
                """)

                # Create indexes for performance
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_timestamp
                    ON playback_events(timestamp_utc)
                """)

                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_track_name
                    ON playback_events(track_name)
                """)

                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_device_name
                    ON playback_events(device_name)
                """)

                await db.commit()
                self._initialized = True
                logger.info(f"Telemetry database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize telemetry database: {e}")
            raise

    async def record_playback(
        self,
        track_name: str,
        device_name: Optional[str] = None,
        device_ip: Optional[str] = None,
        status: str = "success",
        error_message: Optional[str] = None
    ):
        """Record a playback event.

        Args:
            track_name: Name of the track
            device_name: Name of the device
            device_ip: IP address of the device
            status: Status of the playback (success, failed, attempted)
            error_message: Error message if status is failed
        """
        try:
            timestamp_utc = datetime.utcnow().isoformat()

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO playback_events
                    (track_name, device_name, device_ip, timestamp_utc, status, error_message)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (track_name, device_name, device_ip, timestamp_utc, status, error_message))

                await db.commit()
                logger.debug(f"Recorded playback event: {track_name} on {device_name} - {status}")
        except Exception as e:
            logger.error(f"Failed to record playback event: {e}")
            # Don't raise - telemetry failures shouldn't affect playback

    async def get_recent_events(self, limit: int = 100) -> List[PlaybackEvent]:
        """Get recent playback events.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of playback events
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT * FROM playback_events
                    ORDER BY timestamp_utc DESC
                    LIMIT ?
                """, (limit,)) as cursor:
                    rows = await cursor.fetchall()
                    return [PlaybackEvent(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get recent events: {e}")
            return []

    async def get_daily_stats(self, limit: int = 30) -> List[DailyStats]:
        """Get daily playback statistics.

        Args:
            limit: Number of days to include

        Returns:
            List of daily statistics
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT
                        DATE(timestamp_utc) as date,
                        track_name,
                        COUNT(*) as play_count
                    FROM playback_events
                    WHERE status = 'success'
                    AND DATE(timestamp_utc) >= DATE('now', '-' || ? || ' days')
                    GROUP BY DATE(timestamp_utc), track_name
                    ORDER BY date DESC, play_count DESC
                """, (limit,)) as cursor:
                    rows = await cursor.fetchall()
                    return [DailyStats(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get daily stats: {e}")
            return []

    async def get_weekly_stats(self, limit: int = 12) -> List[WeeklyStats]:
        """Get weekly playback statistics.

        Args:
            limit: Number of weeks to include

        Returns:
            List of weekly statistics
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT
                        CAST(STRFTIME('%Y', timestamp_utc) AS INTEGER) as year,
                        CAST(STRFTIME('%W', timestamp_utc) AS INTEGER) as week,
                        track_name,
                        COUNT(*) as play_count
                    FROM playback_events
                    WHERE status = 'success'
                    AND DATE(timestamp_utc) >= DATE('now', '-' || ? * 7 || ' days')
                    GROUP BY year, week, track_name
                    ORDER BY year DESC, week DESC, play_count DESC
                """, (limit,)) as cursor:
                    rows = await cursor.fetchall()
                    return [WeeklyStats(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get weekly stats: {e}")
            return []

    async def get_monthly_stats(self, limit: int = 12) -> List[MonthlyStats]:
        """Get monthly playback statistics.

        Args:
            limit: Number of months to include

        Returns:
            List of monthly statistics
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT
                        CAST(STRFTIME('%Y', timestamp_utc) AS INTEGER) as year,
                        CAST(STRFTIME('%m', timestamp_utc) AS INTEGER) as month,
                        track_name,
                        COUNT(*) as play_count
                    FROM playback_events
                    WHERE status = 'success'
                    AND DATE(timestamp_utc) >= DATE('now', '-' || ? || ' months')
                    GROUP BY year, month, track_name
                    ORDER BY year DESC, month DESC, play_count DESC
                """, (limit,)) as cursor:
                    rows = await cursor.fetchall()
                    return [MonthlyStats(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get monthly stats: {e}")
            return []

    async def get_top_tracks(self, limit: int = 10, days: Optional[int] = None) -> List[TopTrack]:
        """Get top played tracks.

        Args:
            limit: Maximum number of tracks to return
            days: Optional number of days to look back (None = all time)

        Returns:
            List of top tracks
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row

                if days:
                    query = """
                        SELECT
                            track_name,
                            COUNT(*) as play_count,
                            MAX(timestamp_utc) as last_played
                        FROM playback_events
                        WHERE status = 'success'
                        AND DATE(timestamp_utc) >= DATE('now', '-' || ? || ' days')
                        GROUP BY track_name
                        ORDER BY play_count DESC
                        LIMIT ?
                    """
                    params = (days, limit)
                else:
                    query = """
                        SELECT
                            track_name,
                            COUNT(*) as play_count,
                            MAX(timestamp_utc) as last_played
                        FROM playback_events
                        WHERE status = 'success'
                        GROUP BY track_name
                        ORDER BY play_count DESC
                        LIMIT ?
                    """
                    params = (limit,)

                async with db.execute(query, params) as cursor:
                    rows = await cursor.fetchall()
                    return [TopTrack(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get top tracks: {e}")
            return []

    async def get_health_status(self) -> HealthStatus:
        """Get health status of the telemetry system.

        Returns:
            Health status information
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT COUNT(*) as count FROM playback_events") as cursor:
                    row = await cursor.fetchone()
                    total_events = row[0] if row else 0

                return HealthStatus(
                    status="healthy",
                    database_connected=True,
                    total_events=total_events,
                    message=f"Telemetry system operational with {total_events} events recorded"
                )
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return HealthStatus(
                status="unhealthy",
                database_connected=False,
                total_events=0,
                message=f"Database connection failed: {str(e)}"
            )


def get_telemetry_router(telemetry: TelemetryService) -> APIRouter:
    """Create and configure the telemetry API router.

    Args:
        telemetry: TelemetryService instance

    Returns:
        Configured APIRouter
    """
    router = APIRouter()

    @router.get("/health", response_model=HealthStatus)
    async def health():
        """Get telemetry system health status."""
        return await telemetry.get_health_status()

    @router.get("/events/recent", response_model=List[PlaybackEvent])
    async def recent_events(limit: int = Query(default=100, ge=1, le=1000)):
        """Get recent playback events.

        Args:
            limit: Maximum number of events to return (1-1000)
        """
        return await telemetry.get_recent_events(limit)

    @router.get("/stats/daily", response_model=List[DailyStats])
    async def daily_stats(limit: int = Query(default=30, ge=1, le=365)):
        """Get daily playback statistics.

        Args:
            limit: Number of days to include (1-365)
        """
        return await telemetry.get_daily_stats(limit)

    @router.get("/stats/weekly", response_model=List[WeeklyStats])
    async def weekly_stats(limit: int = Query(default=12, ge=1, le=52)):
        """Get weekly playback statistics.

        Args:
            limit: Number of weeks to include (1-52)
        """
        return await telemetry.get_weekly_stats(limit)

    @router.get("/stats/monthly", response_model=List[MonthlyStats])
    async def monthly_stats(limit: int = Query(default=12, ge=1, le=36)):
        """Get monthly playback statistics.

        Args:
            limit: Number of months to include (1-36)
        """
        return await telemetry.get_monthly_stats(limit)

    @router.get("/stats/top-tracks", response_model=List[TopTrack])
    async def top_tracks(
        limit: int = Query(default=10, ge=1, le=100),
        days: Optional[int] = Query(default=None, ge=1, le=365)
    ):
        """Get most popular tracks.

        Args:
            limit: Maximum number of tracks to return (1-100)
            days: Optional number of days to look back (None = all time)
        """
        return await telemetry.get_top_tracks(limit, days)

    @router.get("/dashboard", response_class=HTMLResponse)
    async def dashboard():
        """Serve the telemetry dashboard HTML page."""
        template_path = Path(__file__).parent / "templates" / "telemetry_dashboard.html"
        try:
            with open(template_path, "r") as f:
                html_content = f.read()
            return HTMLResponse(content=html_content)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Dashboard template not found")
        except Exception as e:
            logger.error(f"Failed to load dashboard: {e}")
            raise HTTPException(status_code=500, detail="Failed to load dashboard")

    return router
