from studio.events.bus import EventBus
from studio.events.handlers import RuntimeHandler

global_event_bus = EventBus()
global_event_bus.subscribe(RuntimeHandler())
