"""G06 - complete, correct solution with standard interface naming.

This is the grading golden file: the rubric should score it at or near
full marks. G05 (commented-out evasion twin) is generated from this file
at test time.
"""


class Book:
    def __init__(self, title, author, isbn, total_copies):
        self.title = title
        self.author = author
        self.isbn = isbn
        self.total_copies = total_copies
        self.available_copies = total_copies

    def borrow_book(self):
        if self.available_copies > 0:
            self.available_copies -= 1
            print(f"'{self.title}' borrowed")
        else:
            print(f"Cannot borrow '{self.title}'")

    def return_book(self):
        if self.available_copies < self.total_copies:
            self.available_copies += 1

    def __str__(self):
        return f"{self.title} by {self.author} ({self.available_copies}/{self.total_copies})"


class Library:
    def __init__(self):
        self.books = []

    def add_book(self, book):
        self.books.append(book)

    def find_by_title(self, title):
        for b in self.books:
            if b.title.lower() == title.lower():
                return b
        return None

    def total_books_available(self):
        return sum(b.available_copies for b in self.books)


lib = Library()
book1 = Book("Clean Code", "Robert Martin", "9780132350884", 2)
lib.add_book(book1)
book1.borrow_book()
print(lib.total_books_available())


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


staff = [Manager("Sara", 1, 90000, 15000),
         Developer("Ali", 2, 80000, 10, 25),
         Intern("Zara", 3, 0, 20000)]
for emp in staff:
    print(emp.name, emp.calculate_pay())


class BankAccountError(Exception):
    pass


class BankAccount:
    def __init__(self, balance):
        self.__balance = balance

    @property
    def balance(self):
        return self.__balance

    def deposit(self, amount):
        if amount <= 0:
            raise BankAccountError("Deposit must be positive")
        self.__balance += amount

    def withdraw(self, amount):
        if amount <= 0:
            raise BankAccountError("Withdrawal must be positive")
        if amount > self.__balance:
            raise BankAccountError("Insufficient funds")
        self.__balance -= amount


acc = BankAccount(5000)
acc.deposit(2000)
acc.withdraw(1500)
# acc.__balance = 999999 would fail: name mangling stores it as
# _BankAccount__balance, so direct assignment only adds a new attribute
print(acc.balance)


class Complex:
    def __init__(self, real, imag):
        self.real = real
        self.imag = imag

    def __add__(self, other):
        return Complex(self.real + other.real, self.imag + other.imag)

    def __sub__(self, other):
        return Complex(self.real - other.real, self.imag - other.imag)

    def __mul__(self, other):
        return Complex(self.real * other.real - self.imag * other.imag,
                       self.real * other.imag + self.imag * other.real)

    def __eq__(self, other):
        return self.real == other.real and self.imag == other.imag

    def __abs__(self):
        return (self.real ** 2 + self.imag ** 2) ** 0.5

    def __str__(self):
        if self.imag >= 0:
            return "{} + {}i".format(self.real, self.imag)
        return "{} - {}i".format(self.real, abs(self.imag))


c1 = Complex(3, 4)
c2 = Complex(1, -4)
print(c1 + c2)
print(c1 * c2)
print(abs(c1))


from abc import ABC, abstractmethod


class Shape(ABC):
    @abstractmethod
    def area(self):
        pass

    @abstractmethod
    def perimeter(self):
        pass
    # note: instantiating Shape() directly raises TypeError because the
    # class is abstract


class Circle(Shape):
    def __init__(self, radius):
        self.radius = radius

    def area(self):
        return 3.14159 * self.radius ** 2

    def perimeter(self):
        return 2 * 3.14159 * self.radius


class Rectangle(Shape):
    def __init__(self, width, height):
        self.width = width
        self.height = height

    def area(self):
        return self.width * self.height

    def perimeter(self):
        return 2 * (self.width + self.height)


class Triangle(Shape):
    def __init__(self, a, b, c):
        self.a = a
        self.b = b
        self.c = c

    def perimeter(self):
        return self.a + self.b + self.c

    def area(self):
        s = self.perimeter() / 2
        return (s * (s - self.a) * (s - self.b) * (s - self.c)) ** 0.5


def total_area(shapes):
    total = 0
    for shape in shapes:
        total += shape.area()
    return total


def most_efficient_shape(shapes):
    best = None
    ratio = -1
    for shape in shapes:
        r = shape.area() / shape.perimeter()
        if r > ratio:
            ratio = r
            best = shape
    return best


shapes = [Circle(4), Rectangle(3, 6), Triangle(5, 5, 6)]
print(total_area(shapes))


class InventoryError(Exception):
    pass


class InsufficientStockError(InventoryError):
    pass


class InvalidQuantityError(InventoryError):
    pass


class InventoryItem:
    def __init__(self, name, quantity, reorder_level):
        self.name = name
        self.quantity = quantity
        self.reorder_level = reorder_level

    def remove_stock(self, qty):
        if qty <= 0:
            raise InvalidQuantityError("Quantity must be positive")
        if qty > self.quantity:
            raise InsufficientStockError("Insufficient stock")
        self.quantity -= qty
        if self.quantity <= self.reorder_level:
            print("Warning: reorder", self.name)


item = InventoryItem("USB Cable", 10, 5)
try:
    item.remove_stock(4)
except InventoryError as e:
    print(e)
try:
    item.remove_stock(-2)
except InventoryError as e:
    print(e)
try:
    item.remove_stock(100)
except InventoryError as e:
    print(e)
