import numpy as np


class CorrelationEngine:

    def correlation_matrix(
        self,
        returns_data
    ):

        return np.corrcoef(returns_data)
