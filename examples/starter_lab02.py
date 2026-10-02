"""Starter/base code for --starter demo (Lab 02 mandated skeleton).

Anything in this file is indexed by `copcat audit --starter` and subtracted
from every submission before similarity is computed, so the lab manual's own
sample code can never inflate student-to-student similarity.
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
        else:
            print("No copies available")

    def return_book(self):
        if self.available_copies < self.total_copies:
            self.available_copies += 1


class Library:
    def __init__(self):
        self.books = []

    def add_book(self, book):
        self.books.append(book)

    def find_by_title(self, title):
        for book in self.books:
            if book.title == title:
                return book
        return None

    def total_books_available(self):
        total = 0
        for book in self.books:
            total += book.available_copies
        return total


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


class Developer(Employee):
    def __init__(self, name, employee_id, base_salary, extra_hours, hourly_rate):
        super().__init__(name, employee_id, base_salary)
        self.extra_hours = extra_hours
        self.hourly_rate = hourly_rate


class Intern(Employee):
    def __init__(self, name, employee_id, base_salary, stipend):
        super().__init__(name, employee_id, base_salary)
        self.stipend = stipend


class BankAccount:
    def __init__(self, balance):
        self.__balance = balance

    @property
    def balance(self):
        return self.__balance

    def deposit(self, amount):
        if amount > 0:
            self.__balance += amount

    def withdraw(self, amount):
        if 0 < amount <= self.__balance:
            self.__balance -= amount


class Shape:
    def area(self):
        pass

    def perimeter(self):
        pass


class Circle(Shape):
    def __init__(self, radius):
        self.radius = radius

    def area(self):
        return 3.14 * self.radius ** 2

    def perimeter(self):
        return 2 * 3.14 * self.radius


class Rectangle(Shape):
    def __init__(self, length, width):
        self.length = length
        self.width = width

    def area(self):
        return self.length * self.width

    def perimeter(self):
        return 2 * (self.length + self.width)


class Triangle(Shape):
    def __init__(self, a, b, c):
        self.a = a
        self.b = b
        self.c = c

    def perimeter(self):
        return self.a + self.b + self.c


class InventoryItem:
    def __init__(self, name, quantity, reorder_level):
        self.name = name
        self.quantity = quantity
        self.reorder_level = reorder_level

    def remove_stock(self, qty):
        if qty <= 0:
            print("Invalid quantity")
        elif qty > self.quantity:
            print("Insufficient stock")
        else:
            self.quantity -= qty
