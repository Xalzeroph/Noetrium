from __future__ import annotations

import argparse
import contextlib
import fcntl
import faulthandler
import hashlib
import io
import json
import importlib.util
import runpy
import os
from pathlib import Path
import select
import signal
import socket
import sys
import time
import traceback
import urllib.parse

_DEFAULT_SOCKET = Path('/tmp/noetrium-control.sock')
_RESEARCH_CLI_SNIPPET = (
    'from noetrium_platform.composition.operator.wiring.research import main; '
    'import sys; raise SystemExit(main(sys.argv[1:]))'
)
_UNAVAILABLE_EXIT = 74
_STALE_SOURCE_EXIT = 75
_REQUEST_ENV_KEYS = (
    'NOETRIUM_BOOTSTRAP_OWNER_PID',
    'NOETRIUM_BOOTSTRAP_OWNER_BOOT',
    'NOETRIUM_BOOTSTRAP_OWNER_START',
    'NOETRIUM_CONTROL_REQUEST_LEASE',
    'NOETRIUM_CONTROL_PROFILE',
)
_MAX_FRAME_BYTES = 1024 * 1024
_RECONCILE_INTERVAL_SECONDS = 30.0
_RECONCILE_LOCK_NAME = 'runtime-fabric-reconcile.lock'


def _loaded_source_fingerprint() -> dict[str, tuple[int, int]]:
    root = Path(__file__).resolve().parents[1]
    rows: dict[str, tuple[int, int]] = {}
    for module in tuple(sys.modules.values()):
        raw = getattr(module, '__file__', None)
        if not isinstance(raw, str):
            continue
        try:
            resolved = Path(raw).resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if resolved.suffix not in {'.py', '.pyi'}:
            continue
        try:
            stat = resolved.stat()
        except OSError:
            rows[str(resolved)] = (-1, -1)
        else:
            rows[str(resolved)] = (stat.st_mtime_ns, stat.st_size)
    return rows


def _source_drift(
    baseline: dict[str, tuple[int, int]],
) -> tuple[str, tuple[int, int], tuple[int, int]] | None:
    for raw, expected in baseline.items():
        try:
            stat = Path(raw).stat()
            current = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            current = (-1, -1)
        if current != expected:
            return (raw, expected, current)
    return None


def _source_is_fresh(baseline: dict[str, tuple[int, int]]) -> bool:
    return _source_drift(baseline) is None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_lines(lines: list[str]) -> str:
    return hashlib.sha256(
        ''.join(line + '\n' for line in lines).encode('utf-8')
    ).hexdigest()


def _docker_get_json(path: str) -> dict[str, object] | None:
    host = os.environ.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
    if not host.startswith('unix://'):
        return None
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(1.0)
        client.connect(host[len('unix://'):])
        client.sendall(
            (f'GET {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n').encode('ascii')
        )
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError:
        return None
    finally:
        client.close()
    raw = b''.join(chunks)
    head, separator, body = raw.partition(b'\r\n\r\n')
    if not separator or b' 200 ' not in head.split(b'\r\n', 1)[0]:
        return None
    if b'\r\nTransfer-Encoding: chunked' in b'\r\n' + head:
        decoded = bytearray()
        cursor = 0
        while True:
            line_end = body.find(b'\r\n', cursor)
            if line_end < 0:
                return None
            size_token = body[cursor:line_end].split(b';', 1)[0]
            try:
                size = int(size_token, 16)
            except ValueError:
                return None
            cursor = line_end + 2
            if size == 0:
                body = bytes(decoded)
                break
            end = cursor + size
            if end + 2 > len(body) or body[end:end + 2] != b'\r\n':
                return None
            decoded.extend(body[cursor:end])
            cursor = end + 2
    try:
        value = json.loads(body.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return value if type(value) is dict else None


def _docker_daemon_identity() -> str | None:
    info = _docker_get_json('/info')
    if info is None:
        return None
    compact = lambda value: json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False
    )
    return '|'.join((
        str(info.get('ID', '')),
        str(info.get('ServerVersion', '')),
        str(info.get('Driver', '')),
        str(info.get('DefaultRuntime', '')),
        compact(info.get('Runtimes', {})),
        compact(info.get('CDISpecDirs', [])),
    ))


def _docker_image_id(name: str) -> str | None:
    if not name:
        return None
    row = _docker_get_json('/images/' + urllib.parse.quote(name, safe='') + '/json')
    if row is None:
        return None
    value = row.get('Id')
    return value if isinstance(value, str) and value else None


def _gpu_fingerprint() -> str:
    root = Path('/proc/driver/nvidia')
    rows: list[str] = []
    version = root / 'version'
    if version.is_file():
        try:
            rows.append('version=' + _sha256_file(version))
        except OSError:
            rows.append('version=unreadable')
    gpu_root = root / 'gpus'
    if gpu_root.is_dir():
        for path in sorted(gpu_root.glob('*/information')):
            try:
                rows.append(str(path) + '=' + _sha256_file(path))
            except OSError:
                rows.append(str(path) + '=unreadable')
    for path in sorted(Path('/dev').glob('nvidia*')):
        try:
            stat = path.stat()
            rows.append(f'dev={path.name}:{stat.st_rdev}:{stat.st_mode}')
        except OSError:
            rows.append(f'dev={path.name}:missing')
    return hashlib.sha256('\n'.join(rows).encode('utf-8')).hexdigest()


def _project_roots(_argv: tuple[str, ...]) -> tuple[Path, ...] | None:
    # A resident control worker is already generation-bound to exactly one
    # canonical root set. Lifecycle requests (inspect/reconcile/retry/...) do
    # not carry --project-roots-file in argv, so argv is not an authority for
    # worker identity. Always read the startup-bound canonical roots file.
    raw = os.environ.get('NOETRIUM_CONTROL_PROJECT_ROOTS_FILE', '').strip()
    if not raw:
        return None
    roots_file = Path(raw)
    try:
        rows = tuple(
            Path(line.strip())
            for line in roots_file.read_text('utf-8').splitlines()
            if line.strip()
        )
    except (OSError, UnicodeError):
        return None
    return rows or None


def _desired_control_input_root() -> str:
    namespace = os.environ.get('NOETRIUM_CONTROL_FABRIC_NAMESPACE_ROOT', '').strip()
    if not namespace:
        return ''
    registry = Path(namespace) / 'content' / 'state' / 'model' / 'assets'
    if not registry.is_dir():
        return ''
    retiring = registry / '_retiring'
    refs: list[str] = []
    for path in sorted(registry.glob('*.json')):
        if (retiring / path.name).exists():
            continue
        try:
            row = json.loads(path.read_text('utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(row, dict) or row.get('mode') != 'reference':
            continue
        raw = row.get('path')
        if isinstance(raw, str) and os.path.isabs(raw):
            refs.append(raw)
    if not refs:
        return ''
    common = os.path.commonpath(refs)
    return '' if common == os.path.sep else common


def _runtime_is_fresh(argv: tuple[str, ...], gpu_fingerprint: str) -> bool:
    expected_daemon = os.environ.get('NOETRIUM_DOCKER_DAEMON_CAPABILITY_IDENTITY', '')
    if not expected_daemon or _docker_daemon_identity() != expected_daemon:
        return False
    if _gpu_fingerprint() != gpu_fingerprint:
        return False

    docker_cli_image = os.environ.get('NOETRIUM_DOCKER_CLI_IMAGE', '')
    docker_cli_id = os.environ.get('NOETRIUM_DOCKER_CLI_IMAGE_ID', '')
    python_image = os.environ.get('NOETRIUM_PYTHON_RUNTIME_IMAGE', '')
    python_image_id = os.environ.get('NOETRIUM_PYTHON_RUNTIME_IMAGE_ID', '')
    if (
        not docker_cli_id
        or not python_image_id
        or _docker_image_id(docker_cli_image) != docker_cli_id
        or _docker_image_id(python_image) != python_image_id
    ):
        return False

    root = Path(__file__).resolve().parents[1]
    expected_bootstrap = os.environ.get('NOETRIUM_BOOTSTRAP_INPUT_DIGEST', '')
    try:
        bootstrap_lines = [
            f"{_sha256_file(root / 'deploy/bootstrap/Dockerfile')}  deploy/bootstrap/Dockerfile",
            f"{_sha256_file(root / 'pyproject.toml')}  pyproject.toml",
            docker_cli_id,
            python_image_id,
        ]
    except OSError:
        return False
    if not expected_bootstrap or _sha256_lines(bootstrap_lines) != expected_bootstrap:
        return False

    roots = _project_roots(argv)
    if roots is None:
        return False
    roots_file = os.environ.get('NOETRIUM_CONTROL_PROJECT_ROOTS_FILE', '')
    expected_root_set = os.environ.get('NOETRIUM_CONTROL_ROOT_SET_DIGEST', '')
    if not roots_file or not expected_root_set:
        return False
    try:
        if hashlib.sha256(Path(roots_file).read_bytes()).hexdigest() != expected_root_set:
            return False
    except OSError:
        return False

    expected_runtime = os.environ.get('NOETRIUM_PROJECT_RUNTIME_INPUT_DIGEST', '')
    bootstrap_image_id = os.environ.get('NOETRIUM_BOOTSTRAP_IMAGE_ID', '')
    runtime_fabric_root = os.environ.get('NOETRIUM_RUNTIME_FABRIC_ROOT', '')
    host_identity_source = os.environ.get('NOETRIUM_HOST_IDENTITY_SOURCE', '')
    host_uid = os.environ.get('NOETRIUM_HOST_UID', '')
    if not all((expected_runtime, bootstrap_image_id, runtime_fabric_root, host_identity_source, host_uid)):
        return False
    try:
        runtime_lines = [_sha256_file(row / 'pyproject.toml') for row in roots]
        runtime_lines.extend(
            _sha256_file(root / relative)
            for relative in (
                'pyproject.toml',
                'deploy/bootstrap/ProjectRuntime.Dockerfile',
                'scripts/materialize_project_runtime.py',
                'noetrium_platform/composition/runtime_coordination.py',
                'noetrium_platform/foundation/kernel/kernel/lease_clock.py',
            )
        )
        runtime_lines.append(_sha256_file(Path(host_identity_source)))
    except OSError:
        return False
    runtime_lines.extend((
        expected_root_set,
        bootstrap_image_id,
        runtime_fabric_root,
        'uid=' + host_uid,
    ))
    if _sha256_lines(runtime_lines) != expected_runtime:
        return False

    if _desired_control_input_root() != os.environ.get('NOETRIUM_CONTROL_INPUT_ROOT', '').strip():
        return False

    env_digest = os.environ.get('NOETRIUM_CONTROL_ENV_DIGEST', 'none')
    env_file = os.environ.get('NOETRIUM_CONTROL_ENV_FILE', '').strip()
    if env_digest != 'none':
        if not env_file:
            return False
        try:
            if _sha256_file(Path(env_file)) != env_digest:
                return False
        except OSError:
            return False
    return True


@contextlib.contextmanager
def _request_environment(values: dict[str, str]):
    previous: dict[str, str | None] = {}
    for key, value in values.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _read_message(conn: socket.socket) -> dict[str, object]:
    data = bytearray()
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            raise ConnectionError('control worker client disconnected before request frame')
        data.extend(chunk)
        if len(data) > _MAX_FRAME_BYTES:
            raise ValueError('control worker request exceeds maximum frame size')
        newline = data.find(b'\n')
        if newline >= 0:
            if any(byte not in b' \t\r\n' for byte in data[newline + 1:]):
                raise ValueError('control worker request contains trailing data')
            raw = bytes(data[:newline])
            break
    payload = json.loads(raw.decode('utf-8'))
    if type(payload) is not dict:
        raise TypeError('control worker request must be a JSON object')
    return payload


def _send_message(conn: socket.socket, payload: dict[str, object]) -> None:
    conn.sendall(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def _terminal_result_path() -> Path:
    raw = os.environ.get('NOETRIUM_CONTROL_STATE_ROOT', '').strip()
    root = (
        Path(raw).resolve() / 'control-worker-terminal'
        if raw
        else Path('/tmp') / f'noetrium-control-terminal-{os.getuid()}'
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / f'{os.getpid()}.{time.monotonic_ns()}.json'


def _write_terminal_result(path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(',', ':')
    ).encode('utf-8')
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    try:
        with os.fdopen(fd, 'wb', closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _read_terminal_result(path: Path) -> dict[str, object] | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError('control worker child terminal result is malformed') from exc
    if type(payload) is not dict:
        raise RuntimeError('control worker child terminal result is not an object')
    return payload


def _terminal_from_wait_status(status: int) -> dict[str, object]:
    if os.WIFSIGNALED(status):
        signum = os.WTERMSIG(status)
        try:
            signal_name = signal.Signals(signum).name
        except ValueError:
            signal_name = f'SIGNAL_{signum}'
        detail = (
            'resident control worker request child terminated by '
            f'{signal_name} ({signum}) before terminal publication'
        )
    elif os.WIFEXITED(status):
        detail = (
            'resident control worker request child exited with status '
            f'{os.WEXITSTATUS(status)} before terminal publication'
        )
    else:
        detail = (
            'resident control worker request child ended without a terminal '
            'publication'
        )
    return {
        'code': 1,
        'stdout': '',
        'stderr': detail + '; reconcile from durable state\n',
    }


def _dispatch(argv: tuple[str, ...]) -> int:
    if not argv:
        raise ValueError('control worker request requires argv')
    command = argv[0]
    if command == '-c' and len(argv) >= 2 and argv[1] == _RESEARCH_CLI_SNIPPET:
        from noetrium_platform.composition.operator.wiring.research import main
        return int(main(list(argv[2:])))

    root = Path(__file__).resolve().parents[1]
    previous_argv = sys.argv
    try:
        if command == '-m':
            if len(argv) < 2 or not argv[1].strip():
                raise ValueError('resident control -m requires a module name')
            module_name = argv[1]
            spec = importlib.util.find_spec(module_name)
            origin = None if spec is None else spec.origin
            if origin in {None, 'built-in', 'frozen'}:
                raise ValueError(
                    f'resident control module has no repository source: {module_name!r}'
                )
            try:
                Path(origin).resolve().relative_to(root)
            except ValueError as exc:
                raise ValueError(
                    f'resident control module escaped repository root: {module_name!r}'
                ) from exc
            sys.argv = [module_name, *argv[2:]]
            runpy.run_module(module_name, run_name='__main__', alter_sys=True)
            return 0

        candidate = Path(command)
        script = (candidate if candidate.is_absolute() else root / candidate).resolve()
        try:
            script.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f'resident control script escaped repository root: {command!r}'
            ) from exc
        if script.suffix != '.py' or not script.is_file():
            raise ValueError(
                f'unsupported resident control command: {command!r}'
            )
        sys.argv = [str(script), *argv[1:]]
        runpy.run_path(str(script), run_name='__main__')
        return 0
    finally:
        sys.argv = previous_argv


def _child_dispatch(
    server: socket.socket,
    argv: tuple[str, ...],
    request_env: dict[str, str],
    terminal_path: Path,
) -> None:
    server.close()

    def _cancel(_signum, _frame):
        raise KeyboardInterrupt('control worker request cancelled')

    signal.signal(signal.SIGTERM, _cancel)
    trace_file = None
    state_root = os.environ.get("NOETRIUM_CONTROL_STATE_ROOT", "").strip()
    if state_root:
        trace_path = Path(state_root) / f"request-trace.{os.getpid()}.log"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_file = trace_path.open("a", encoding="utf-8")
        faulthandler.enable(file=trace_file, all_threads=True)
        faulthandler.register(
            signal.SIGUSR2,
            file=trace_file,
            all_threads=True,
            chain=False,
        )
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 1
    try:
        with _request_environment(request_env):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    code = _dispatch(argv)
                except SystemExit as exc:
                    code = int(exc.code or 0)
    except BaseException:
        stderr.write(traceback.format_exc())
        code = 1
    try:
        _write_terminal_result(
            terminal_path,
            {
                'code': code,
                'stdout': stdout.getvalue(),
                'stderr': stderr.getvalue(),
            },
        )
    finally:
        if trace_file is not None:
            try:
                faulthandler.unregister(signal.SIGUSR2)
                faulthandler.disable()
            finally:
                trace_file.close()
        os._exit(0)


def _request_owner_lease(request_env: dict[str, str]) -> Path | None:
    owner_keys = (
        'NOETRIUM_BOOTSTRAP_OWNER_PID',
        'NOETRIUM_BOOTSTRAP_OWNER_BOOT',
        'NOETRIUM_BOOTSTRAP_OWNER_START',
    )
    has_owner = any(request_env.get(key, '').strip() for key in owner_keys)
    raw = request_env.get('NOETRIUM_CONTROL_REQUEST_LEASE', '').strip()
    if not raw:
        if has_owner:
            raise ValueError(
                'owned control request requires NOETRIUM_CONTROL_REQUEST_LEASE'
            )
        return None
    lease = Path(raw)
    if not lease.is_absolute():
        raise ValueError('control request lease path must be absolute')
    state_root_raw = os.environ.get('NOETRIUM_CONTROL_STATE_ROOT', '').strip()
    if not state_root_raw:
        raise ValueError('control request lease requires control state root')
    allowed = Path(state_root_raw).resolve() / 'control-request-leases'
    try:
        resolved = lease.resolve(strict=True)
    except OSError as exc:
        raise ValueError('control request lease does not exist') from exc
    if resolved.parent != allowed:
        raise ValueError('control request lease escaped control state root')
    if lease.is_symlink() or not resolved.is_file():
        raise ValueError('control request lease must be a real regular file')
    return resolved


def _request_supervisor(
    conn: socket.socket,
    server: socket.socket,
    argv: tuple[str, ...],
    request_env: dict[str, str],
) -> None:
    """Own one durable request independently of its observing client."""
    # The resident parent may use SIGCHLD to reap request supervisors. This
    # supervisor must keep normal child-wait semantics for its request process.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    use_fd = None
    terminal_path: Path | None = None
    try:
        # Validate all execution authority before forking. An invalid owner or
        # generation lock must never leave a request child running orphaned.
        owner_lease = _request_owner_lease(request_env)
        use_lock_raw = os.environ.get(
            'NOETRIUM_CONTROL_WORKER_USE_LOCK', ''
        ).strip()
        if use_lock_raw:
            use_lock = Path(use_lock_raw)
            if not use_lock.is_absolute():
                raise ValueError(
                    'control worker generation use-lock path must be absolute'
                )
            use_fd = os.open(
                use_lock, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600
            )
            fcntl.flock(use_fd, fcntl.LOCK_SH)

        # The child never writes the observing-client socket. It publishes one
        # private atomic result and the supervisor is the sole terminal writer.
        terminal_path = _terminal_result_path()
        child_pid = os.fork()
        if child_pid == 0:
            try:
                conn.close()
            except OSError:
                pass
            _child_dispatch(server, argv, request_env, terminal_path)

        server.close()
        status = _wait_child_or_cancel(conn, child_pid, owner_lease)
        payload = _read_terminal_result(terminal_path)
        if payload is None:
            payload = _terminal_from_wait_status(status)
        try:
            _send_message(conn, payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
    except BaseException:
        try:
            _send_message(conn, {
                'code': 1,
                'stdout': '',
                'stderr': traceback.format_exc(),
            })
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
    finally:
        if terminal_path is not None:
            try:
                terminal_path.unlink()
            except FileNotFoundError:
                pass
        if use_fd is not None:
            try:
                fcntl.flock(use_fd, fcntl.LOCK_UN)
            finally:
                os.close(use_fd)
        try:
            server.close()
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass
        os._exit(0)


def _reap_request_supervisors(_signum, _frame) -> None:
    """Reap completed direct request supervisors without blocking accept()."""
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid <= 0:
            return


def _wait_child_or_cancel(
    conn: socket.socket,
    child_pid: int,
    owner_lease: Path | None = None,
) -> int:
    """Wait for one durable request; only an explicit marker cancels it.

    Client/socket/SSH lifetime is observational. A disconnected client detaches
    from the request; it never becomes execution authority. Explicit operator
    cancellation is represented by an adjacent durable cancel marker.
    """

    cancel_marker = (
        None if owner_lease is None else Path(str(owner_lease) + '.cancel')
    )
    client_attached = True
    poller = select.poll()
    disconnect_mask = select.POLLHUP | select.POLLERR | select.POLLNVAL
    if hasattr(select, 'POLLRDHUP'):
        disconnect_mask |= select.POLLRDHUP
    poller.register(conn.fileno(), disconnect_mask)
    try:
        while True:
            done, status = os.waitpid(child_pid, os.WNOHANG)
            if done == child_pid:
                return status
            if cancel_marker is not None and cancel_marker.exists():
                try:
                    os.kill(child_pid, signal.SIGTERM)
                except ProcessLookupError:
                    # The child crossed its terminal boundary between waitpid
                    # and kill. Reap it in the next loop iteration.
                    continue
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    done, status = os.waitpid(child_pid, os.WNOHANG)
                    if done == child_pid:
                        return status
                    time.sleep(0.02)
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    # Race with natural exit: the blocking wait below still
                    # returns the exact child status if it has not been reaped.
                    pass
                _done, status = os.waitpid(child_pid, 0)
                return status
            if client_attached:
                events = poller.poll(50)
                if any(mask & disconnect_mask for _fd, mask in events):
                    client_attached = False
                    try:
                        poller.unregister(conn.fileno())
                    except (KeyError, OSError):
                        pass
            else:
                time.sleep(0.05)
    finally:
        # The request supervisor executes explicit cancellation but does not
        # consume the durable marker.  The owning wrapper must observe that
        # marker after the request returns so cancellation cannot be mistaken
        # for worker unavailability/source drift and automatically re-submitted.
        pass



def _resource_authority_path() -> Path | None:
    raw = os.environ.get('NOETRIUM_CONTROL_FABRIC_NAMESPACE_ROOT', '').strip()
    if not raw:
        return None
    return (
        Path(raw)
        / 'runtime'
        / 'state'
        / 'platform-resources'
        / 'platform-resources.sqlite'
    )


def _reconciliation_needed() -> bool:
    path = _resource_authority_path()
    if path is None or not path.is_file():
        return False
    from noetrium_platform.infrastructure.resources.authority import (
        UniversalResourceAuthority,
    )
    authority = UniversalResourceAuthority(path, timeout_seconds=5.0)
    return bool(authority.orphaned_claim_groups())


def _reconciliation_lock_path() -> Path:
    raw = os.environ.get('NOETRIUM_CONTROL_STATE_ROOT', '').strip()
    if not raw:
        raw = os.environ.get('NOETRIUM_CONTROL_FABRIC_NAMESPACE_ROOT', '').strip()
    if not raw:
        raise RuntimeError(
            'runtime-fabric reconciliation requires control state root'
        )
    root = Path(raw).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / _RECONCILE_LOCK_NAME


def _run_runtime_fabric_reconciliation() -> None:
    lock_path = _reconciliation_lock_path()
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if not _reconciliation_needed():
            return
        roots = _project_roots(())
        if roots is None:
            raise RuntimeError(
                'runtime-fabric reconciliation requires project roots'
            )
        argv: list[str] = ['-c', _RESEARCH_CLI_SNIPPET, 'reconcile']
        for root in roots:
            argv.extend(('--project', str(root)))
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = _dispatch(tuple(argv))
        if code != 0:
            detail = stderr.getvalue().strip() or stdout.getvalue().strip()
            raise RuntimeError(
                'runtime-fabric reconciliation failed'
                + (': ' + detail if detail else '')
            )
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _spawn_runtime_fabric_reconciliation() -> None:
    pid = os.fork()
    if pid != 0:
        return
    try:
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        _run_runtime_fabric_reconciliation()
    except BaseException:
        traceback.print_exc(file=sys.stderr)
    finally:
        os._exit(0)


def _preload_runtime() -> tuple[tuple[tuple[str, tuple[int, int]], ...], str]:
    import scripts.run_research_roots  # noqa: F401
    import noetrium_platform.composition.operator.wiring.research  # noqa: F401

    return _loaded_source_fingerprint(), _gpu_fingerprint()


def serve(socket_path: Path) -> int:
    # Publish the listening socket before expensive imports. The kernel backlog
    # becomes the readiness queue: callers can connect immediately while the
    # resident process preloads once, without a polling timeout race.
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    # Let the kernel size the pending-request backlog.  A fixed backlog turns
    # concurrent multi-paper submission into an arbitrary control-plane cap.
    server.listen(socket.SOMAXCONN)
    previous_sigchld = None
    try:
        # Preload once, then fork one isolated request process. Fork preserves
        # the imported module graph via COW while each Research request gets
        # process-local mutable state and remains independently cancellable.
        source_fingerprint, gpu_fingerprint = _preload_runtime()
        previous_sigchld = signal.getsignal(signal.SIGCHLD)
        signal.signal(signal.SIGCHLD, _reap_request_supervisors)
        next_reconcile_at = time.monotonic() + _RECONCILE_INTERVAL_SECONDS
        while True:
            timeout = max(0.0, next_reconcile_at - time.monotonic())
            readable, _, _ = select.select((server,), (), (), timeout)
            if not readable:
                if _source_drift(source_fingerprint) is None:
                    _spawn_runtime_fabric_reconciliation()
                next_reconcile_at = (
                    time.monotonic() + _RECONCILE_INTERVAL_SECONDS
                )
                continue
            conn, _ = server.accept()
            try:
                request = _read_message(conn)
                if request.get('probe') is True:
                    _send_message(
                        conn,
                        {'code': 0, 'stdout': 'ready\n', 'stderr': ''},
                    )
                    conn.close()
                    continue
                argv_raw = request.get('argv')
                if type(argv_raw) is not list or any(
                    type(row) is not str for row in argv_raw
                ):
                    raise TypeError(
                        'control worker argv must be a JSON string array'
                    )
                argv = tuple(argv_raw)
                source_drift = _source_drift(source_fingerprint)
                runtime_fresh = _runtime_is_fresh(argv, gpu_fingerprint)
                if source_drift is not None or not runtime_fresh:
                    detail = (
                        'source=' + repr(source_drift)
                        if source_drift is not None
                        else 'runtime=drifted'
                    )
                    _send_message(conn, {
                        'code': _STALE_SOURCE_EXIT,
                        'stdout': '',
                        'stderr': (
                            'resident control worker attestation changed; '
                            'restart required; ' + detail + '\n'
                        ),
                    })
                    conn.close()
                    continue
                env_raw = request.get('env', {})
                if type(env_raw) is not dict or any(
                    key not in _REQUEST_ENV_KEYS or type(value) is not str
                    for key, value in env_raw.items()
                ):
                    raise TypeError('control worker request env is invalid')
                supervisor_pid = os.fork()
                if supervisor_pid == 0:
                    _request_supervisor(
                        conn,
                        server,
                        argv,
                        dict(env_raw),
                    )
                # Only the supervisor/request child retain this client socket.
                # The resident parent can immediately accept the next request.
                conn.close()
                continue
            except BaseException:
                try:
                    _send_message(conn, {
                        'code': 1,
                        'stdout': '',
                        'stderr': traceback.format_exc(),
                    })
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            finally:
                conn.close()
    finally:
        if previous_sigchld is not None:
            signal.signal(signal.SIGCHLD, previous_sigchld)
        server.close()
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


def probe(socket_path: Path) -> int:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(socket_path))
        client.sendall(b'{"probe":true}\n')
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as exc:
        sys.stderr.write(f'resident control worker probe failed: {exc}\n')
        return _UNAVAILABLE_EXIT
    finally:
        client.close()
    raw = b''.join(chunks)
    if not raw:
        sys.stderr.write('resident control worker probe returned no terminal frame\n')
        return _UNAVAILABLE_EXIT
    try:
        response = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f'resident control worker probe returned invalid terminal frame: {exc}\n')
        return _UNAVAILABLE_EXIT
    if type(response) is not dict:
        sys.stderr.write('resident control worker probe terminal frame is not an object\n')
        return _UNAVAILABLE_EXIT
    return int(response.get('code', 1))


def request(socket_path: Path, argv: tuple[str, ...]) -> int:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(socket_path))
    except OSError as exc:
        sys.stderr.write(f'resident control worker unavailable: {exc}\n')
        return _UNAVAILABLE_EXIT
    request_env = {
        key: os.environ[key]
        for key in _REQUEST_ENV_KEYS
        if key in os.environ
    }
    frame = json.dumps(
        {'argv': list(argv), 'env': request_env}, separators=(',', ':')
    ).encode('utf-8') + b'\n'
    client.sendall(frame)
    chunks: list[bytes] = []
    while True:
        chunk = client.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
    client.close()
    raw = b''.join(chunks)
    if not raw:
        sys.stderr.write(
            'resident control worker request ended without a terminal frame; '
            'retry from durable state required\n'
        )
        return _UNAVAILABLE_EXIT
    try:
        response = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        sys.stderr.write(
            f'resident control worker returned an invalid terminal frame: {exc}; '
            'retry from durable state required\n'
        )
        return _UNAVAILABLE_EXIT
    if type(response) is not dict:
        sys.stderr.write(
            'resident control worker terminal frame is not an object; '
            'retry from durable state required\n'
        )
        return _UNAVAILABLE_EXIT
    stdout = response.get('stdout', '')
    stderr = response.get('stderr', '')
    if stdout:
        sys.stdout.write(str(stdout))
    if stderr:
        sys.stderr.write(str(stderr))
    return int(response.get('code', 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('serve', 'probe', 'request'))
    parser.add_argument('--socket', type=Path, default=_DEFAULT_SOCKET)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.mode == 'serve':
        if args.command:
            parser.error('serve does not accept command arguments')
        return serve(args.socket)
    if args.mode == 'probe':
        if args.command:
            parser.error('probe does not accept command arguments')
        return probe(args.socket)
    command = tuple(args.command)
    if command and command[0] == '--':
        command = command[1:]
    return request(args.socket, command)


if __name__ == '__main__':
    raise SystemExit(main())
