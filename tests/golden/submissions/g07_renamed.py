"""G07 - renamed-variables twin of G08: identical logic, every local and
attribute renamed. The source-line channel must drop; the AST-canonical
channel must stay high (renaming-invariance evidence)."""


class Thermometer:
    def __init__(self, temp_c):
        self.temp_c = temp_c

    def to_f(self):
        return self.temp_c * 9 / 5 + 32

    def category(self):
        if self.temp_c < 10:
            return "cold"
        if self.temp_c < 25:
            return "mild"
        return "hot"


class Purse:
    def __init__(self, avail):
        self.avail = avail

    def put(self, cash):
        if cash <= 0:
            raise ValueError("amount must be positive")
        self.avail += cash

    def draw(self, cash):
        if cash > self.avail:
            raise ValueError("insufficient funds")
        self.avail -= cash
        return self.avail


class Worker:
    def __init__(self, who, code, wage):
        self.who = who
        self.code = code
        self.wage = wage

    def wages(self):
        return self.wage


class WorkerBoss(Worker):
    def __init__(self, who, code, wage, extra_pay):
        super().__init__(who, code, wage)
        self.extra_pay = extra_pay

    def wages(self):
        return super().wages() + self.extra_pay


class WorkerDev(Worker):
    def __init__(self, who, code, wage, ot, rate):
        super().__init__(who, code, wage)
        self.ot = ot
        self.rate = rate

    def wages(self):
        return super().wages() + self.ot * self.rate


class WorkerTrainee(Worker):
    def __init__(self, who, code, wage, stipend):
        super().__init__(who, code, wage)
        self.stipend = stipend

    def wages(self):
        return self.stipend


sensor = Thermometer(30)
print(sensor.to_f(), sensor.category())

purse = Purse(1000)
purse.put(500)
print(purse.draw(200))

team = [WorkerBoss("Omar", 21, 70000, 20000),
        WorkerDev("Sana", 22, 60000, 12, 30),
        WorkerTrainee("Bilal", 23, 0, 18000)]
for member in team:
    print(member.who, member.wages())
