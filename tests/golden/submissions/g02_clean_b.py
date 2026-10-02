"""G02 - a second clean, independent submission.

Different from G01 in structure and naming; must stay CLEAN against all
other golden files.
"""

library_log = []


def register(title, writer, copies):
    entry = {"title": title, "writer": writer, "total": copies,
             "left": copies}
    library_log.append(entry)
    return entry


def search(title):
    for entry in library_log:
        if entry["title"].casefold() == title.casefold():
            return entry
    return None


def checkout(entry):
    if entry["left"] == 0:
        print("shelf empty for", entry["title"])
        return
    entry["left"] -= 1
    print("ok, left:", entry["left"])


def hand_back(entry):
    if entry["left"] < entry["total"]:
        entry["left"] += 1


register("Algorithms", "Sedgewick", 2)
checkout(search("Algorithms"))
checkout(search("Algorithms"))
hand_back(search("Algorithms"))
print(sum(e["left"] for e in library_log))


class PayrollPerson:
    kind = "base"

    def __init__(self, label, number, monthly):
        self.label = label
        self.number = number
        self.monthly = monthly

    def wages(self):
        return self.monthly


class PayrollBoss(PayrollPerson):
    def __init__(self, label, number, monthly, cut):
        PayrollPerson.__init__(self, label, number, monthly)
        self.cut = cut

    def wages(self):
        return self.monthly + self.cut


class PayrollDev(PayrollPerson):
    def __init__(self, label, number, monthly, over, unit):
        PayrollPerson.__init__(self, label, number, monthly)
        self.over = over
        self.unit = unit

    def wages(self):
        return self.monthly + self.over * self.unit


class PayrollIntern(PayrollPerson):
    def __init__(self, label, stipend):
        PayrollPerson.__init__(self, label, 0, 0)
        self.stipend = stipend

    def wages(self):
        return self.stipend


people = [PayrollBoss("Zain", 11, 80000, 12000),
          PayrollDev("Maha", 12, 65000, 6, 400),
          PayrollIntern("Feroz", 9000)]
total = 0
for person in people:
    total += person.wages()
print("payroll:", total)


wallet_balance = 4000


def wallet_deposit(cash):
    global wallet_balance
    if cash > 0:
        wallet_balance += cash


def wallet_withdraw(cash):
    global wallet_balance
    if cash <= 0:
        raise RuntimeError("positive amounts only")
    if cash > wallet_balance:
        raise RuntimeError("balance too low")
    wallet_balance -= cash


wallet_deposit(1000)
wallet_withdraw(2500)
print(wallet_balance)
try:
    wallet_withdraw(999999)
except RuntimeError as problem:
    print("refused:", problem)
