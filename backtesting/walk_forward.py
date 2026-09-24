class WalkForwardTester:

    def split_data(
        self,
        data,
        train_ratio=0.7
    ):

        split_index = int(
            len(data) * train_ratio
        )

        train = data[:split_index]

        test = data[split_index:]

        return train, test
