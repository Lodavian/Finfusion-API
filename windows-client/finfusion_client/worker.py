import asyncio
import threading


class Worker:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        tasks = asyncio.all_tasks(self.loop)
        for task in tasks:
            task.cancel()
        self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        self.loop.close()

    def submit(self, task):
        return asyncio.run_coroutine_threadsafe(task, self.loop)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(8)
