"""
Telemetry and metrics collection
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import time


@dataclass
class Metric:
    """Single metric value"""
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class Event:
    """Event record"""
    name: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Telemetry:
    """Telemetry collector"""
    
    def __init__(self):
        self._metrics: list[Metric] = []
        self._events: list[Event] = []
    
    def record_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a metric"""
        self._metrics.append(Metric(name=name, value=value, tags=tags or {}))
    
    def record_event(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Record an event"""
        self._events.append(Event(name=name, metadata=metadata or {}))
    
    def get_metrics(self) -> list[Metric]:
        """Get all recorded metrics"""
        return self._metrics.copy()
    
    def get_events(self) -> list[Event]:
        """Get all recorded events"""
        return self._events.copy()
    
    def clear(self) -> None:
        """Clear all metrics and events"""
        self._metrics.clear()
        self._events.clear()


# Global telemetry instance
_telemetry = Telemetry()


def get_telemetry() -> Telemetry:
    """Get global telemetry instance"""
    return _telemetry

