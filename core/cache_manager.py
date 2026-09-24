import json
import redis


class CacheManager:

    def __init__(
        self,
        host='localhost',
        port=6379,
        db=0
    ):

        self.client = redis.Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=True
        )

    def set(self, key, value):

        self.client.set(
            key,
            json.dumps(value)
        )

    def get(self, key):

        value = self.client.get(key)

        if value is None:
            return None

        return json.loads(value)

    def delete(self, key):

        self.client.delete(key)
