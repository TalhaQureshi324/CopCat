"""G01 - a clean, independent submission with its own style.

Deliberately divergent from the other golden files: different variable
names, different control flow, different demo data, dict-based inventory.
Must stay CLEAN against every other file.
"""


class BookShopItem:
    def __init__(self, ttl, writer, code, stock):
        self.ttl = ttl
        self.writer = writer
        self.code = code
        self.stock = stock

    def lend(self):
        if self.stock > 0:
            self.stock -= 1
            return True
        return False

    def give_back(self):
        self.stock += 1


class Shelf:
    def __init__(self):
        self.hold = {}

    def place(self, item):
        self.hold[item.code] = item

    def locate(self, code):
        return self.hold.get(code)

    def count(self):
        return sum(i.stock for i in self.hold.values())


shelf = Shelf()
b1 = BookShopItem("Design Patterns", "GoF", "DP01", 3)
shelf.place(b1)
b1.lend()
print(shelf.count())


class Wage:
    RATE = 1.0

    def __init__(self, who, tab, pay):
        self.who = who
        self.tab = tab
        self.pay = pay

    def net(self):
        return self.pay


class Lead(Wage):
    def __init__(self, who, tab, pay, extra):
        super().__init__(who, tab, pay)
        self.extra = extra

    def net(self):
        return self.pay + self.extra


class Coder(Wage):
    def __init__(self, who, tab, pay, hrs, perhr):
        super().__init__(who, tab, pay)
        self.hrs = hrs
        self.perhr = perhr

    def net(self):
        return self.pay + self.hrs * self.perhr


class Trainee(Wage):
    def __init__(self, who, tab, allowance):
        super().__init__(who, tab, 0)
        self.allowance = allowance

    def net(self):
        return self.allowance


crew = [Lead("Hina", 7, 70000, 9000), Coder("Omar", 8, 60000, 8, 300),
        Trainee("Rida", 9, 12000)]
for member in crew:
    print(member.who, member.net())


class Purse:
    def __init__(self, opening):
        self._amount = opening

    @property
    def amount(self):
        return self._amount

    def add(self, cash):
        if cash > 0:
            self._amount += cash

    def take(self, cash):
        if 0 < cash <= self._amount:
            self._amount -= cash
            return True
        return False


purse = Purse(2000)
purse.add(500)
purse.take(300)
print(purse.amount)


import math


class Plane:
    def span(self):
        raise NotImplementedError


class Dot(Plane):
    def __init__(self, r):
        self.r = r

    def span(self):
        return math.pi * self.r ** 2

    def edge(self):
        return 2 * math.pi * self.r


class Board(Plane):
    def __init__(self, w, h):
        self.w = w
        self.h = h

    def span(self):
        return self.w * self.h

    def edge(self):
        return 2 * (self.w + self.h)


print(Board(2, 5).span())


class Crate:
    def __init__(self, label, pieces, threshold):
        self.label = label
        self.pieces = pieces
        self.threshold = threshold

    def peel(self, n):
        if n < 1 or n > self.pieces:
            raise ValueError("bad peel amount")
        self.pieces -= n
        if self.pieces < self.threshold:
            print("restock", self.label)


crate = Crate("Nails", 50, 10)
crate.peel(30)
print(crate.pieces)
