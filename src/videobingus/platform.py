import shutil
import subprocess
import tempfile
from contextlib import contextmanager


def executable(name: str, explicit: str | None = None) -> str:
    found = shutil.which(explicit or name)
    if not found:
        raise ValueError(f"{explicit or name} was not found. Install FFmpeg or set {name} in configuration.")
    return found


def run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        raise ValueError(f"{args[0]} failed: {result.stderr[-3000:]}")
    return result.stdout


@contextmanager
def process(args: list[str], check=True, **kwargs):
    with tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(args, stderr=errors, **kwargs)
        failure = None
        try:
            yield child
        except BaseException as error:
            failure = error
            if child.poll() is None:
                child.terminate()
        finally:
            for pipe in (child.stdin, child.stdout):
                if pipe:
                    try:
                        pipe.close()
                    except BrokenPipeError:
                        pass
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if failure and not isinstance(failure, BrokenPipeError):
            raise failure
        if (child.returncode and check) or failure:
            errors.seek(0)
            raise ValueError(errors.read().decode("utf-8", errors="replace")[-3000:])
