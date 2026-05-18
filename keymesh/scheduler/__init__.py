"""keymesh.scheduler package."""
from keymesh.scheduler.base import BaseScheduler, SchedulerStrategy
from keymesh.scheduler.round_robin import RoundRobinScheduler
from keymesh.scheduler.least_busy import LeastBusyScheduler
from keymesh.scheduler.weighted import WeightedScheduler

__all__ = [
    "BaseScheduler",
    "SchedulerStrategy",
    "RoundRobinScheduler",
    "LeastBusyScheduler",
    "WeightedScheduler",
]


def build_scheduler(strategy: SchedulerStrategy) -> BaseScheduler:
    """Factory: return a scheduler instance for the given strategy."""
    match strategy:
        case SchedulerStrategy.ROUND_ROBIN:
            return RoundRobinScheduler()
        case SchedulerStrategy.LEAST_BUSY:
            return LeastBusyScheduler()
        case SchedulerStrategy.WEIGHTED:
            return WeightedScheduler()
        case _:
            raise ValueError(f"Unknown scheduler strategy: {strategy!r}")
