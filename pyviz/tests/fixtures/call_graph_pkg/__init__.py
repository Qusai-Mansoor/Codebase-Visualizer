def helper():
    return 42


def caller():
    return helper()


def multi_caller():
    helper()
    caller()


def builtin_user():
    print(len([1, 2, 3]))


def no_calls():
    x = 1
    return x


class MyClass:
    def method_a(self):
        self.method_b()

    def method_b(self):
        pass

    def uses_helper(self):
        return helper()

    @classmethod
    def factory(cls):
        return cls()

    def nested_call(self):
        result = len(helper())
        return result
