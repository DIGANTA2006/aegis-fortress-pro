class OrderStateManager:

    def __init__(self):

        self.orders = {}

    def register_order(self, order_id, status):

        self.orders[order_id] = {
            "status": status
        }

    def update_order(self, order_id, status):

        if order_id in self.orders:
            self.orders[order_id]["status"] = status

    def get_order(self, order_id):

        return self.orders.get(order_id)
