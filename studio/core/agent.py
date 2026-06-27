class BaseAgent:
    name = "base"

    def before(self, *args, **kwargs):
        return None

    def after(self, result, *args, **kwargs):
        return result

    def process(self, *args, **kwargs):
        raise NotImplementedError("Agent must implement process()")

    def run(self, *args, **kwargs):
        self.before(*args, **kwargs)
        result = self.process(*args, **kwargs)
        return self.after(result, *args, **kwargs)
