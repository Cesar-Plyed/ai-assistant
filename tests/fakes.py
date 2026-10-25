"""Small shared fakes for unit tests (not collected by pytest)."""


class FakeLogger:
    def __init__(self):
        self.events = []

    def log(self, event_type, payload=None):
        self.events.append((event_type, payload))
