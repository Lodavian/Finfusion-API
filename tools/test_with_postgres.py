"""Run tests against a disposable local PostgreSQL cluster; never install a service.

Usage: python tools/test_with_postgres.py --bin-dir build/tool-cache/pgsql/bin
The cluster and logs remain under runtime for inspection; PostgreSQL is stopped.
"""
import argparse
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    binary = args.bin_dir.resolve()
    runtime = root / "runtime" / ("postgres-test-" + uuid.uuid4().hex)
    runtime.mkdir(parents=True)
    password = secrets.token_hex(24)
    password_file = runtime / "init-password"
    password_file.write_text(password, encoding="ascii")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = dict(os.environ, PGPASSWORD=password)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def run(name, *arguments):
        executable = binary / (name + (".exe" if os.name == "nt" else ""))
        # PostgreSQL child processes can inherit a Windows pipe and keep it
        # open after pg_ctl exits. A log file avoids waiting for pipe EOF.
        output = runtime / (name + ".log")
        with output.open("wb") as log:
            result = subprocess.run([str(executable), *map(str, arguments)], env=environment,
                                    stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        print(output.read_bytes().decode(errors="replace"), flush=True)
        result.check_returncode()
        return result

    started = False
    try:
        run("initdb", "-D", runtime / "data", "-U", "postgres", "-A", "scram-sha-256",
            "--pwfile", password_file, "--encoding=UTF8", "--locale=C")
        password_file.unlink()
        run("pg_ctl", "-D", runtime / "data", "-l", runtime / "postgres.log",
            "-o", f"-h 127.0.0.1 -p {port}", "-w", "start")
        started = True
        database = "finfusion_test_" + uuid.uuid4().hex
        run("createdb", "-h", "127.0.0.1", "-p", port, "-U", "postgres", database)
        environment["FINFUSION_TEST_DSN"] = f"postgresql://postgres:{password}@127.0.0.1:{port}/{database}"
        environment.pop("PYTHONPATH", None)
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--basetemp",
                               str(runtime / "pytest"), "--junitxml", str(runtime / "tests.xml")],
                                cwd=root, env=environment, creationflags=flags,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout.decode(errors="replace"), flush=True)
        return result.returncode
    finally:
        if started:
            run("pg_ctl", "-D", runtime / "data", "-m", "fast", "-w", "stop")
        password_file.unlink(missing_ok=True)
        print(f"Test artifacts: {runtime}")


if __name__ == "__main__":
    raise SystemExit(main())
