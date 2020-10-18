class RingBuffer(list):
    max_size = 0
    __start_index = 0

    def __init__(self, max_size):
        self.max_size = max_size

    def append(self, item):
        if len(self) < self.max_size:
            super().append(item)
        else:
            super().__setitem__(self.__start_index, item)
            self.__start_index = (self.__start_index + 1) % self.max_size

    def __getitem__(self, index: int):
        return super().__getitem__((self.__start_index + index) % self.max_size)

    def __setitem__(self, index: int, value):
        super().__setitem__((self.__start_index + index) % self.max_size)
