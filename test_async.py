#!/bin/python

import os, subprocess
from contextlib import contextmanager
import trio


async def silent_call(arguments, swallow_stdout=True):
    """Calls an external program.  stdout and stderr are swallowed by default.  The
    environment variable ``OMP_THREAD_LIMIT`` is set to one, because we do
    parallelism by ourselves.  In particular, Tesseract scales *very* badly (at
    least, version 4.0) with more threads.

    :param list[object] arguments: the arguments for the call.  They are
      converted to ``str`` implicitly.
    :param bool swallow_stdout: if ``False``, stdout is caught and can be
      inspected by the caller (as a str rather than a byte string)

    :returns:
       the completed process

    :rtype: subprocess.CompletedProcess
    """
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "1"
    arguments = list(map(str, arguments))
    return await trio.run_process(arguments,
                                  stdout=None,#subprocess.DEVNULL if swallow_stdout else subprocess.PIPE,
                                  stderr=None, env=environment)

class MyRange:
    a = 0
    def __aiter__(self):
        return self
    async def __anext__(self):
        self.a += 1
        if self.a >= 10:
            raise StopAsyncIteration
        return self.a

class MyContext:
    def __enter__(self):
        print("Enter")
        return None

    def __exit__(self, *args, **kwargs):
        print("Exit")
        return None

async def my_range():
    await silent_call(["sh", "-c", f"sleep 3; echo MÖÖÖP"], False)
    for i in range(10):
        yield i

async def main():
    async for i in my_range():
        waiting_time = (10 - i) / 10
        await silent_call(["sh", "-c", f"sleep {waiting_time}; echo {i}"], False)
    # async with trio.open_nursery() as nursery:
    #     with MyContext() as toll:
    #         pass


data = trio.run(main)
