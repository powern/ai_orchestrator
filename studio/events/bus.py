class EventBus:
    def __init__(self):
        self.handlers = []

    def subscribe(self, handler):
        self.handlers.append(handler)
        return handler

    def publish(self, event):
        results = []

        for handler in list(self.handlers):
            results.append(handler(event))

        return results
