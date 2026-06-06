def my_decorator(f):
    return f


@my_decorator
def decorated_func():
    pass


class DecoratedClass:
    @staticmethod
    def static_method():
        pass

    @classmethod
    def class_method(cls):
        pass
