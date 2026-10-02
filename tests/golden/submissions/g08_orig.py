"""G08 - original of the renamed-variables pair (G07 is the same logic with
every variable renamed). Class names are identical; the AST channel must
still match the pair (renaming-invariance), while the source channel drops."""


class Thermometer:
    def __init__(self, celsius):
        self.celsius = celsius

    def to_fahrenheit(self):
        return self.celsius * 9 / 5 + 32

    def scale(self):
        if self.celsius < 10:
            return "cold"
        if self.celsius < 25:
            return "mild"
        return "hot"


class Wallet:
    def __init__(self, balance):
        self.balance = balance

    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("amount must be positive")
        self.balance += amount

    def withdraw(self, amount):
        if amount > self.balance:
            raise ValueError("insufficient funds")
        self.balance -= amount
        return self.balance


class Employee:
    def __init__(self, name, employee_id, base_salary):
        self.name = name
        self.employee_id = employee_id
        self.base_salary = base_salary

    def calculate_pay(self):
        return self.base_salary


class Manager(Employee):
    def __init__(self, name, employee_id, base_salary, bonus):
        super().__init__(name, employee_id, base_salary)
        self.bonus = bonus

    def calculate_pay(self):
        return super().calculate_pay() + self.bonus


class Developer(Employee):
    def __init__(self, name, employee_id, base_salary, extra_hours, hourly_rate):
        super().__init__(name, employee_id, base_salary)
        self.extra_hours = extra_hours
        self.hourly_rate = hourly_rate

    def calculate_pay(self):
        return super().calculate_pay() + self.extra_hours * self.hourly_rate


class Intern(Employee):
    def __init__(self, name, employee_id, base_salary, stipend):
        super().__init__(name, employee_id, base_salary)
        self.stipend = stipend

    def calculate_pay(self):
        return self.stipend


thermometer = Thermometer(30)
print(thermometer.to_fahrenheit(), thermometer.scale())

wallet = Wallet(1000)
wallet.deposit(500)
print(wallet.withdraw(200))

staff = [Manager("Omar", 21, 70000, 20000),
         Developer("Sana", 22, 60000, 12, 30),
         Intern("Bilal", 23, 0, 18000)]
for emp in staff:
    print(emp.name, emp.calculate_pay())
