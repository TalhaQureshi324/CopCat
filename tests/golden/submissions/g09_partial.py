"""G09 - partial submission: only Task 1 exists. Grading golden: must score
low (<= 2.0 of 10.0)."""


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
            return True
        return False

    def return_book(self):
        self.available_copies += 1


b = Book("Kleo", "Zain", "x1", 1)
print(b.borrow_book())
print(b.borrow_book())
print(b.available_copies)
