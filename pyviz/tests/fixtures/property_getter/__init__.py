class Config:
    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v

    @staticmethod
    def default():
        return 42
