"""Lab 03 starter — data structure and agent patterns from the lab manual's
"SYNTAX HELPING" section. CopCat subtracts fingerprints from this file
before scoring."""

from collections import deque


class SimpleStack:
    def __init__(self):
        self._items = deque()

    def push(self, item):
        self._items.append(item)

    def pop(self):
        if not self._items:
            raise IndexError("pop from empty stack")
        return self._items.pop()

    def peek(self):
        return self._items[-1] if self._items else None


class SimpleQueue:
    def __init__(self):
        self._items = deque()

    def enqueue(self, item):
        self._items.append(item)

    def dequeue(self):
        if not self._items:
            raise IndexError("dequeue from empty queue")
        return self._items.popleft()

    def peek(self):
        return self._items[0] if self._items else None


class SimpleReflexAgent:
    def act(self, percept):
        location, status = percept
        if status == "Dirty":
            return "Suck"
        elif location == "A":
            return "Right"
        elif location == "B":
            return "Left"
        return "NoOp"


class ModelBasedReflexAgent:
    def __init__(self, rooms):
        self.model = {r: "Unknown" for r in rooms}
        self.last_action = None

    def update_state(self, percept, action):
        loc, status = percept
        self.model[loc] = status
        if action == "Suck":
            self.model[loc] = "Clean"

    def act(self, percept):
        self.update_state(percept, self.last_action)
        if all(self.model[r] == "Clean" for r in self.model):
            return "NoOp"
        return "Suck" if percept[1] == "Dirty" else ("Right" if percept[0] == "A" else "Left")
