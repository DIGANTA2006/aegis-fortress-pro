import csv
import os
from datetime import datetime


class TradeLogger:

    def __init__(
        self,
        file_path='logs/trades.csv'
    ):

        self.file_path = file_path

        os.makedirs(
            os.path.dirname(file_path),
            exist_ok=True
        )

        if not os.path.exists(file_path):

            with open(
                file_path,
                'w',
                newline=''
            ) as f:

                writer = csv.writer(f)

                writer.writerow([
                    'timestamp',
                    'symbol',
                    'side',
                    'quantity',
                    'price',
                    'pnl'
                ])

    def log_trade(
        self,
        symbol,
        side,
        quantity,
        price,
        pnl
    ):

        with open(
            self.file_path,
            'a',
            newline=''
        ) as f:

            writer = csv.writer(f)

            writer.writerow([
                datetime.utcnow(),
                symbol,
                side,
                quantity,
                price,
                pnl
            ])
