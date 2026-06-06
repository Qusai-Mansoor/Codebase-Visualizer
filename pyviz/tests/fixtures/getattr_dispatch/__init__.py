def dispatcher(obj, method_name):
    return getattr(obj, method_name)()


def normal_call():
    return len([1, 2, 3])
