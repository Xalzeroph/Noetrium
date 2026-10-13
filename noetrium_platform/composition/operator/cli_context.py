"""Workspace selectors and immutable run provenance, not scientific authority."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import time
from uuid import uuid4
from noetrium_platform.foundation.kernel.kernel.durability import (
    atomic_replace_bytes,
    durable_sqlite_reader,
    InterprocessFileLock,
)

WORKSPACE_NAME = "noetrium.workspace.json"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def validate_name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError(
            "name must contain letters, numbers, dot, underscore or hyphen, starting with a letter or number"
        )
    return value


def real_directory(path):
    p = Path(path).expanduser().absolute()
    if p.is_symlink() or not p.is_dir():
        raise ValueError("expected a real directory: " + str(p))
    return p.resolve()


def locate_workspace(explicit=None, *, cwd=None):
    hint = explicit or os.environ.get("NOETRIUM_WORKSPACE_FILE")
    if hint:
        return Path(hint).expanduser().absolute()
    start = Path(cwd or Path.cwd()).resolve()
    for parent in (start, *start.parents):
        candidate = parent / WORKSPACE_NAME
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Workspace:
    path: Path
    data: dict

    @classmethod
    def load(cls, path):
        p = Path(path).expanduser().absolute()
        if p.is_symlink():
            raise ValueError("workspace file must not be a symlink")
        d = json.loads(p.read_text())
        if not isinstance(d, dict):
            raise ValueError("workspace must be a JSON object")
        if d.get("schema") != "noetrium.workspace.v1":
            raise ValueError("unsupported workspace schema")
        if not isinstance(d.get("projects"), dict) or not isinstance(
            d.get("default_projects"), list
        ):
            raise ValueError("workspace requires projects and default_projects")
        if not isinstance(d.get("active_runs", {}), dict):
            raise ValueError("active_runs must be an object")
        for field in ("platform_root", "data_root"):
            if not isinstance(d.get(field), str) or not d[field]:
                raise ValueError("workspace requires " + field)
        for name, value in d["projects"].items():
            validate_name(name)
            cls(p, d).resolve(value)
        if any(name not in d["projects"] for name in d["default_projects"]):
            raise ValueError("default project is not registered")
        return cls(p, d)

    def resolve(self, value):
        p = Path(value).expanduser()
        return (p if p.is_absolute() else self.path.parent / p).absolute()

    def roots(self, selected=None):
        names = list(selected or self.data["default_projects"])
        if not names:
            raise ValueError(
                "no default projects; use noetrium project add NAME PATH, then noetrium project use NAME [NAME...]"
            )
        roots = tuple(
            real_directory(self.resolve(self.data["projects"].get(name, name)))
            for name in names
        )
        if len(set(roots)) != len(roots):
            raise ValueError("project set contains duplicate directories")
        return tuple(names), roots

    @staticmethod
    def roots_key(roots):
        return hashlib.sha256(
            json.dumps(sorted(str(p) for p in roots), separators=(",", ":")).encode()
        ).hexdigest()

    def group_key(self, names):
        _, roots = self.roots(names)
        return self.roots_key(roots)

    def launch_guard(self, names):
        return InterprocessFileLock(
            self.path.parent / (".noetrium-launch-" + self.group_key(names) + ".lock"),
            blocking=False,
        )

    def record_path(self, name):
        return (
            self.resolve(self.data["data_root"])
            / "_cli"
            / "records"
            / (validate_name(name) + ".json")
        )

    def active_record(self, names, run_name=None):
        name = run_name or self.data.get("active_runs", {}).get(self.group_key(names))
        if not name:
            return None
        p = self.record_path(name)
        if p.is_symlink():
            raise ValueError("run record must not be a symlink")
        row = json.loads(p.read_text())
        if (
            not isinstance(row, dict)
            or row.get("schema") != "noetrium.cli.run.v1"
            or row.get("name") != name
        ):
            raise ValueError("invalid run binding")
        for field in ("platform_root", "data_root"):
            if (
                not isinstance(row.get(field), str)
                or not Path(row[field]).is_absolute()
            ):
                raise ValueError("invalid run binding: " + field)
        for field in ("project_roots", "selected_roots"):
            values = row.get(field)
            if (
                not isinstance(values, list)
                or not values
                or any(
                    not isinstance(v, str) or not Path(v).is_absolute() for v in values
                )
                or len(set(values)) != len(values)
            ):
                raise ValueError("invalid run binding: " + field)
        if len(row["project_roots"]) != len(row["selected_roots"]):
            raise ValueError("run binding paper count drifted")
        return row

    def records(self):
        directory = self.record_path("placeholder").parent
        rows = [self.active_record((), p.stem) for p in directory.glob("*.json")]
        return tuple(
            sorted(
                rows,
                key=lambda row: (row.get("created_at", 0), row["name"]),
                reverse=True,
            )
        )

    def execution_guard(self, name):
        return InterprocessFileLock(
            self.record_path(name).with_suffix(".execution.lock"), blocking=False
        )

    def update_record(self, name, fields):
        allowed = {
            "owner",
            "last_action",
            "last_exit",
            "last_action_at",
            "launch_phase",
        }
        if set(fields) - allowed:
            raise ValueError("immutable run provenance cannot be edited")
        path = self.record_path(name)
        with InterprocessFileLock(path.with_suffix(".lock"), blocking=True):
            row = self.active_record((), name)
            row.update(fields)
            atomic_replace_bytes(path, (json.dumps(row, indent=2) + "\n").encode())
        return row

    def update(self, operation):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with InterprocessFileLock(self.path.with_suffix(".lock"), blocking=True):
            current = Workspace.load(self.path)
            data = json.loads(json.dumps(current.data))
            operation(data)
            atomic_replace_bytes(
                self.path,
                (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(),
            )
        return Workspace.load(self.path)


def require_workspace(explicit=None):
    path = locate_workspace(explicit)
    if path is None:
        raise ValueError(
            "No workspace found. First run: noetrium workspace init --project /path/to/paper"
        )
    return Workspace.load(path)


def initialize_workspace(
    explicit=None, *, platform_root, data_root, projects, env_file=None
):
    path = Path(explicit or Path.cwd() / WORKSPACE_NAME).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("workspace file must not be a symlink")
    if path.exists():
        raise FileExistsError("workspace already exists: " + str(path))
    platform = real_directory(platform_root)
    if not (platform / "deploy/noetrium").is_file():
        raise ValueError("platform root requires deploy/noetrium")
    registered = {}
    for spec in projects:
        name, separator, value = spec.partition("=")
        root = real_directory(value if separator else spec)
        name = validate_name(
            name
            if separator
            else re.sub(r"[^A-Za-z0-9_.-]+", "-", root.name).strip("._-") or "paper"
        )
        if name in registered:
            raise ValueError("duplicate project name; use --project NAME=PATH")
        if not (root / "project.manifest.json").is_file():
            raise ValueError("project requires project.manifest.json: " + str(root))
        registered[name] = str(root)
    data = {
        "schema": "noetrium.workspace.v1",
        "platform_root": str(platform),
        "data_root": str(data_root),
        "projects": registered,
        "default_projects": list(registered),
        "active_runs": {},
    }
    if env_file:
        source = Path(env_file).expanduser().absolute()
        if source.is_symlink() or not source.is_file():
            raise ValueError("environment file must be a regular file")
        data["env_file"] = str(source)
    candidate = Workspace(path, data)
    if registered:
        candidate.roots()
    with InterprocessFileLock(path.with_suffix(".lock"), blocking=True):
        if path.exists():
            raise FileExistsError("workspace already exists: " + str(path))
        atomic_replace_bytes(
            path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
        )
    return Workspace.load(path)


def owner_identity(pid=None):
    pid = os.getpid() if pid is None else pid
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        return {
            "pid": pid,
            "start": stat[19],
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        }
    except (OSError, IndexError):
        return None


def owner_alive(row):
    identity = row.get("owner")
    return identity is not None and owner_identity(identity.get("pid")) == identity


def graph_summary(row):
    root = Path(row["data_root"]) / "projects" / "root-sets"
    states = {}
    for path in root.glob("*/research/graph.v5.sqlite3"):
        with durable_sqlite_reader(path, timeout_seconds=1) as conn:
            for state, count in conn.execute(
                "SELECT n.state,count(*) FROM research_graph_nodes n JOIN research_graph_active_cuts c ON c.cut_id=n.execution_id GROUP BY n.state"
            ):
                states[state] = states.get(state, 0) + count
    return states


def existing_record(ws, names, run_name=None):
    row = ws.active_record(names, run_name)
    if row is not None:
        if names and row.get("selected_roots") is not None:
            _, selected = ws.roots(names)
            if sorted(str(p) for p in selected) != sorted(row["selected_roots"]):
                raise ValueError("recorded run belongs to a different paper set")
        for root in row["project_roots"]:
            real_directory(root)
        backend = real_directory(row["platform_root"]) / "deploy" / "noetrium"
        if not backend.is_file():
            raise ValueError("recorded run backend is unavailable: " + str(backend))
        env = row.get("env_file")
        if env and not Path(env).is_file():
            raise ValueError("recorded run environment file is unavailable")
    return row


def publish(ws, names, row, *, activate=True):
    path = ws.record_path(row["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with InterprocessFileLock(path.with_suffix(".lock"), blocking=True):
        if path.exists():
            raise FileExistsError("run name is already recorded: " + row["name"])
        atomic_replace_bytes(path, (json.dumps(row, indent=2) + "\n").encode())
    if activate:
        ws.update(
            lambda data: data.setdefault("active_runs", {}).__setitem__(
                ws.roots_key(row["selected_roots"]), row["name"]
            )
        )


def attach(ws, name, platform_root, data_root, project_roots, env_file=None):
    names, _roots = ws.roots()
    roots = tuple(real_directory(p) for p in project_roots)
    if len(roots) != len(names):
        raise ValueError(
            "existing execution must match the number of selected workspace projects"
        )

    def project_identity(root):
        doc = json.loads((root / "project.manifest.json").read_text())
        if doc.get("schema") == "noetrium.unit.document.v2":
            return doc["units"][doc["root"]]["unit_id"]
        return doc.get("program_id") or doc.get("project_id") or doc.get("name")

    if sorted(project_identity(p) for p in roots) != sorted(
        project_identity(p) for p in _roots
    ):
        raise ValueError("attached roots do not match the selected paper identities")
    data = real_directory(data_root)
    platform = real_directory(platform_root)
    if not (platform / "deploy/noetrium").is_file():
        raise ValueError("platform root does not contain deploy/noetrium")
    if env_file and not Path(env_file).is_file():
        raise ValueError("environment file does not exist")
    pid_file = data / "launcher.pid"
    owner = (
        owner_identity(int(pid_file.read_text().strip()))
        if pid_file.is_file()
        else None
    )
    row = {
        "schema": "noetrium.cli.run.v1",
        "name": validate_name(name),
        "platform_root": str(platform),
        "data_root": str(data),
        "project_roots": [str(p) for p in roots],
        "env_file": str(Path(env_file).absolute()) if env_file else None,
        "owner": owner,
        "selected_roots": [str(p) for p in _roots],
        "adopted": True,
        "created_at": time.time(),
    }
    # Binding alone never constructs providers or starts/resumes an execution.
    publish(ws, names, row)
    return row


def freeze_new_run(
    ws,
    names,
    roots,
    runner,
    name=None,
    env_file=None,
    *,
    committed=False,
    revisions=(),
    source_record=None,
    activate=True,
):
    name = validate_name(name or time.strftime("run-%Y%m%d-%H%M%S-") + uuid4().hex[:8])
    platform = real_directory(
        os.environ.get("NOETRIUM_PLATFORM_ROOT") or ws.resolve(ws.data["platform_root"])
    )
    selected_roots = tuple(roots)
    choices = {}
    for spec in revisions:
        key, separator, revision = spec.partition("=")
        if not separator or not revision or key not in ("platform", *names):
            raise ValueError("--revision expects platform=REF or REGISTERED_PAPER=REF")
        if key in choices:
            raise ValueError("duplicate revision target: " + key)
        choices[key] = revision
    if source_record is not None:
        if choices:
            raise ValueError(
                "rerun uses the original version pair; use run --revision for changed sources"
            )
        platform = real_directory(source_record["platform_root"])
        roots = tuple(real_directory(p) for p in source_record["project_roots"])
        selected_roots = tuple(source_record["selected_roots"])
        configured_source_env = source_record.get("env_file")
        if configured_source_env:
            env_file = configured_source_env
        committed = True
    sources = tuple(dict.fromkeys((platform, *roots)))
    commits = {}

    def git(repo, *args):
        result = runner.run(("git", "-C", str(repo), *args))
        if result.returncode:
            raise RuntimeError("Git source snapshot failed: " + result.stderr.strip())
        return result.stdout.strip()

    # A paper may be a standalone repository or a subdirectory of a shared
    # repository. Freeze each repository once, preserving every relative root.
    repository_for = {
        source: real_directory(git(source, "rev-parse", "--show-toplevel"))
        for source in sources
    }
    repositories = tuple(dict.fromkeys(repository_for.values()))
    relative_roots = {
        source: source.relative_to(repository_for[source]) for source in sources
    }
    selected_commits = {}
    source_names = {platform: "platform", **dict(zip(roots, names))}
    for source in sources:
        ref = choices.get(source_names.get(source))
        if source_record is not None:
            ref = expected_source_revision(source_record, source)
            if ref is None:
                raise ValueError(
                    "historical source lacks pinned revision evidence: " + str(source)
                )
        if ref is not None:
            repo = repository_for[source]
            resolved = git(
                repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"
            )
            if repo in selected_commits and selected_commits[repo] != resolved:
                raise ValueError(
                    "papers in the same repository cannot select conflicting revisions"
                )
            selected_commits[repo] = resolved
    for repo in repositories:
        explicit = committed or repo in selected_commits
        if not explicit and git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError(
                "commit tracked source changes before starting a new formal run: "
                + str(repo)
            )
        data_location = ws.resolve(ws.data["data_root"]).resolve()
        if source_record is None and (
            data_location == repo or repo.is_relative_to(data_location)
        ):
            raise ValueError("workspace data_root must not contain a source repository")
        ignored = {
            ws.path.resolve(),
            ws.path.with_suffix(".lock").resolve(),
            ws.path.with_suffix(".run-allocation.lock").resolve(),
        }
        configured = (
            env_file
            or ws.data.get("env_file")
            or os.environ.get("NOETRIUM_CONTROL_ENV_FILE")
        )
        if configured:
            ignored.add(ws.resolve(configured).resolve())
        for relative in (
            []
            if explicit
            else git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
        ):
            candidate = (repo / relative).resolve()
            cli_lock = (
                candidate.parent == ws.path.parent.resolve()
                and candidate.name.startswith(".noetrium-launch-")
                and candidate.suffix == ".lock"
            )
            if (
                candidate in ignored
                or candidate.is_relative_to(data_location)
                or cli_lock
            ):
                continue
            raise ValueError(
                "untracked source would be absent from the frozen run; commit it or ignore generated files: "
                + str(candidate)
            )
        commits[str(repo)] = selected_commits.get(repo) or git(
            repo, "rev-parse", "--verify", "HEAD^{commit}"
        )
    folder = ws.resolve(ws.data["data_root"]) / "runs" / name
    if any(folder == repo or folder.is_relative_to(repo) for repo in repositories):
        raise ValueError("new run state must be outside every source repository")
    with InterprocessFileLock(
        ws.path.with_suffix(".run-allocation.lock"), blocking=True
    ):
        if folder.exists() or ws.record_path(name).exists():
            raise FileExistsError("run name already exists: " + name)
        folder.mkdir(parents=True, mode=0o700)
    frozen = {}
    created = []
    try:
        for index, repo in enumerate(repositories):
            destination = (
                folder
                / "frozen"
                / (
                    "platform"
                    if repo == repository_for[platform]
                    else f"repository-{index}"
                )
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            git(
                repo,
                "worktree",
                "add",
                "--detach",
                str(destination),
                commits[str(repo)],
            )
            created.append((repo, destination))
            frozen[repo] = destination
        configured_env = (
            env_file
            or ws.data.get("env_file")
            or os.environ.get("NOETRIUM_CONTROL_ENV_FILE")
        )
        if not configured_env and (platform / "deploy/.env").is_file():
            configured_env = str(platform / "deploy/.env")
        copied_env = None
        if configured_env:
            source = ws.resolve(configured_env)
            if source.is_symlink() or not source.is_file():
                raise ValueError("environment configuration must be a regular file")
            copied_env = folder / "control.env"
            atomic_replace_bytes(copied_env, source.read_bytes())
            copied_env.chmod(0o600)
        row = {
            "schema": "noetrium.cli.run.v1",
            "name": name,
            "platform_root": str(
                frozen[repository_for[platform]] / relative_roots[platform]
            ),
            "project_roots": [
                str(frozen[repository_for[p]] / relative_roots[p]) for p in roots
            ],
            "data_root": str(folder / "state"),
            "env_file": str(copied_env) if copied_env else None,
            "selected_roots": [str(p) for p in selected_roots],
            "source_commits": commits,
            "frozen_source_revisions": {
                str(frozen[repository_for[p]] / relative_roots[p]): commits[
                    str(repository_for[p])
                ]
                for p in sources
            },
            "env_sha256": hashlib.sha256(copied_env.read_bytes()).hexdigest()
            if copied_env
            else None,
            "parent_run": source_record["name"] if source_record else None,
            "launch_phase": "prepared",
            "owner": None,
            "created_at": time.time(),
            "adopted": False,
            "launch_log": str(folder / "launch.log"),
        }
        for path in (
            Path(row["platform_root"]),
            *(Path(p) for p in row["project_roots"]),
        ):
            real_directory(path)
        for path in row["project_roots"]:
            if not Path(path, "project.manifest.json").is_file():
                raise ValueError(
                    "selected revision does not contain the paper manifest: " + path
                )
        atomic_replace_bytes(
            folder / "FROZEN_COMMITS.json",
            (json.dumps(commits, indent=2) + "\n").encode(),
        )
        publish(ws, names, row, activate=activate)
        return row
    except BaseException:
        # Source preparation failures never start Research. Retain the folder as
        # failure evidence, but remove only the worktrees created by this call.
        for repo, destination in (
            () if ws.record_path(name).exists() else reversed(created)
        ):
            runner.run(
                (
                    "git",
                    "-C",
                    str(repo),
                    "worktree",
                    "remove",
                    "--force",
                    str(destination),
                )
            )
        raise


def execution_environment(row):
    environment = os.environ.copy()
    environment["NOETRIUM_INTERNAL_DISPATCH"] = "1"
    environment["NOETRIUM_DATA_ROOT"] = row["data_root"]
    if row.get("env_file"):
        environment["NOETRIUM_CONTROL_ENV_FILE"] = row["env_file"]
    else:
        environment["NOETRIUM_CONTROL_ENV_FILE"] = ""
    return environment


def read_log_tail(path, lines):
    """Read only the required suffix of a growing launcher log."""
    chunks = []
    newlines = 0
    with Path(path).open("rb") as stream:
        stream.seek(0, 2)
        position = stream.tell()
        while position > 0 and newlines <= lines:
            size = min(position, 65536)
            position -= size
            stream.seek(position)
            chunk = stream.read(size)
            chunks.append(chunk)
            newlines += chunk.count(b"\n")
    return (
        b"".join(reversed(chunks))
        .decode("utf-8", errors="replace")
        .splitlines(keepends=True)[-lines:]
    )


def expected_source_revision(row, root):
    pinned = row.get("frozen_source_revisions", {}).get(str(root))
    if pinned:
        return pinned
    provenance = Path(row["data_root"]) / "FROZEN_COMMITS.txt"
    if provenance.is_file() and not provenance.is_symlink():
        fields = dict(
            line.split("=", 1)
            for line in provenance.read_text().splitlines()
            if "=" in line
        )
        value = fields.get(Path(root).name)
        if value and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
            return value
    return None


def observed_source_revision(root):
    path = Path(root)
    for candidate in (path, *path.parents):
        marker = candidate / ".git"
        if marker.is_symlink():
            return None
        if marker.is_dir():
            git_dir = marker
        elif marker.is_file():
            text = marker.read_text().strip()
            if not text.startswith("gitdir: "):
                return None
            git_dir = (candidate / text[8:]).resolve()
        else:
            continue
        try:
            head = (git_dir / "HEAD").read_text().strip()
        except OSError:
            return None
        return head if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head) else None
    return None


def version_summary(row):
    roots = [row["platform_root"], *row["project_roots"]]
    return {
        "run": row["name"],
        "sources": [
            {
                "root": root,
                "revision": expected_source_revision(row, root),
                "observed_detached_head": observed_source_revision(root)
                if Path(root).is_dir()
                else None,
            }
            for root in roots
        ],
        "environment_sha256": row.get("env_sha256"),
        "parent_run": row.get("parent_run"),
    }


def recovery_runtime_binding(row):
    """Read an explicit recovery runtime without changing scientific provenance."""
    path = Path(row["data_root"]) / "RUNTIME_RECOVERY.json"
    if path.is_symlink():
        raise ValueError("recovery runtime binding must not be a symlink")
    if not path.exists():
        return None
    note = json.loads(path.read_text())
    if not isinstance(note, dict):
        raise ValueError("recovery runtime binding must be an object")
    expected = {
        "data_root": row["data_root"],
        "original_platform_root": row["platform_root"],
        "original_project_roots": row["project_roots"],
    }
    if any(note.get(key) != value for key, value in expected.items()):
        raise ValueError("recovery runtime binding belongs to another execution")
    root = note.get("runtime_root")
    revision = note.get("runtime_revision")
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError("recovery runtime root must be absolute")
    if not isinstance(revision, str) or not re.fullmatch(
        r"[0-9a-f]{40}|[0-9a-f]{64}", revision
    ):
        raise ValueError("recovery runtime requires a pinned Git commit")
    return {"platform_root": root, "revision": revision}


def execution_record(row):
    """Resolve the recorded execution runtime and enforce its immutable commit."""
    binding = recovery_runtime_binding(row)
    if binding is None:
        return row
    root = real_directory(binding["platform_root"])
    if observed_source_revision(root) != binding["revision"]:
        raise ValueError(
            "recovery runtime is missing or no longer at its pinned detached commit"
        )
    return {**row, "platform_root": str(root)}
