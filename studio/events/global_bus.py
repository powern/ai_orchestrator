from studio.events.bus import EventBus
from studio.events.handlers import EventLogHandler, RuntimeHandler


global_event_bus = EventBus()
global_event_bus.subscribe(EventLogHandler())
global_event_bus.subscribe(RuntimeHandler())
