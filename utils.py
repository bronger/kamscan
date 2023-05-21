import subprocess, os


debug = False


def silent_call(arguments, asynchronous=False, swallow_stdout=True):
    """Calls an external program.  stdout and stderr are swallowed by default.  The
    environment variable ``OMP_THREAD_LIMIT`` is set to one, because we do
    parallelism by ourselves.  In particular, Tesseract scales *very* badly (at
    least, version 4.0) with more threads.

    :param list[object] arguments: the arguments for the call.  They are
      converted to ``str`` implicitly.
    :param bool asynchronous: whether the program should be launched
      asynchronously
    :param bool swallow_stdout: if ``False``, stdout is caught and can be
      inspected by the caller (as a str rather than a byte string)

    :returns: if asynchronous, it returns a ``Popen`` object, otherwise, it
      returns a ``CompletedProcess`` object.
    :rtype: subprocess.Popen or subprocess.CompletedProcess

    :raises subprocess.CalledProcessError: if a synchronously called process
      returns a non-zero return code
    """
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "1"
    kwargs = {"stdout": subprocess.DEVNULL if swallow_stdout else subprocess.PIPE,
              "stderr": None if debug else subprocess.DEVNULL, "text": True, "env": environment}
    arguments = list(map(str, arguments))
    if asynchronous:
        return subprocess.Popen(arguments, **kwargs)
    else:
        kwargs["check"] = True
        return subprocess.run(arguments, **kwargs)
