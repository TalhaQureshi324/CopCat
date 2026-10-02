"""G04 - the other half of the copy-paste pair (only cosmetic edits vs G03:
comment wording, demo values, and two variable names)."""

from abc import ABC, abstractmethod
import math


class Geom(ABC):
    @abstractmethod
    def space(self):
        pass

    @abstractmethod
    def boundary(self):
        pass


class Ball(Geom):
    def __init__(self, r):
        self.r = r

    def space(self):
        return 3.14159 * self.r ** 3

    def boundary(self):
        return 4 * 3.14159 * self.r ** 2


class Slab(Geom):
    def __init__(self, l, w, h):
        self.l = l
        self.w = w
        self.h = h

    def space(self):
        return self.l * self.w * self.h

    def boundary(self):
        return 2 * (self.l * self.w + self.w * self.h + self.l * self.h)


class Pyramid(Geom):
    def __init__(self, base, height):
        self.base = base
        self.height = height

    def space(self):
        return self.base * self.base * self.height / 3

    def boundary(self):
        side = math.sqrt(self.base / 2 ** 2 + self.height ** 2)
        return self.base ** 2 + 2 * self.base * side


def combined_volume(solid_list):
    total = 0
    for solid in solid_list:
        total += solid.space()
    return total


def biggest_footprint(solid_list):
    return max(solid_list, key=lambda s: s.space() / s.boundary())


solids = [Ball(3), Slab(2, 3, 4), Pyramid(4, 5)]
print("combined_volume:", combined_volume(solids))
winner = biggest_footprint(solids)
print("biggest_footprint:", type(winner).__name__)

history = []
for solid in solids:
    history.append(round(solid.space(), 2))
print(history)
# G04 note: my friend helped me understand the abstract class part
