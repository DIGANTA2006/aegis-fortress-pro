import time
import functools

def retry(max_attempts=3, delay=2):

    def decorator(func):

        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            last_exception = None

            for attempt in range(max_attempts):

                try:
                    return func(*args, **kwargs)

                except Exception as e:

                    last_exception = e
                    time.sleep(delay)

            raise last_exception

        return wrapper

    return decorator
