"""Lab 02 starter — OOP syntax patterns from the lab manual's
"SYNTAX HELPING" section. These are reference examples the instructor
provided — every student's submission will contain similar patterns.
CopCat subtracts fingerprints from this file before scoring."""

# --- Defining a Class ---
class Car:
    def __init__(self, brand, model):
        self.brand = brand
        self.model = model

    def display(self):
        print(f"car is : {self.brand} {self.model}")


# --- Creating an Object (Instantiation) ---
my_car = Car("Toyota", "Corolla")
my_car.display()


# --- Inheritance ---
class ElectricCar(Car):
    def __init__(self, brand, model, battery):
        super().__init__(brand, model)
        self.battery = battery

    def display(self):
        print(f"elect Car: {self.brand} {self.model} with {self.battery}")
