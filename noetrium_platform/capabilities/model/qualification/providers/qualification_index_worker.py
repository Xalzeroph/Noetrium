import email.parser
import hashlib
import html.parser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

try:
    from packaging.markers import default_environment
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    from packaging.tags import sys_tags
    from packaging.utils import parse_wheel_filename
    from packaging.version import InvalidVersion, Version
except Exception as exc:
    print(json.dumps({"error": "target Python lacks packaging metadata parser: " + type(exc).__name__}))
    raise SystemExit(0)

_REPOSITORY_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "noetrium_platform" / "__init__.py").is_file()
)
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailurePolicy,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime


MAX_NODES = 512
MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_METADATA_WORKERS = 16
TARGET_ENVIRONMENT = default_environment()
TARGET_ENVIRONMENT["extra"] = ""
CACHE_ROOT = ""


class _KeyedLocks:
    def __init__(self):
        self._guard = threading.Lock()
        self._locks = {}

    def for_key(self, key):
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock


_PAGE_LOCKS = _KeyedLocks()
_METADATA_LOCKS = _KeyedLocks()


def _blocking_map(operation, fn, values):
    """Run bounded metadata I/O under the Platform structured-concurrency authority."""
    rows = tuple(values)
    if not rows:
        return ()
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=MAX_METADATA_WORKERS,
            max_blocking_io_in_flight=MAX_METADATA_WORKERS,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
            default_queue_capacity=max(MAX_METADATA_WORKERS, len(rows)),
        )
    )
    group = runtime.open_task_group(
        f"model-qualification-{operation}",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    try:
        handles = tuple(
            group.submit(
                ExecutionSpec(
                    task_id=f"model-qualification-{operation}-{index}",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                lambda _context, item, *, _fn=fn: _fn(item),
                value,
            )
            for index, value in enumerate(rows)
        )
        results = []
        first_error = None
        for handle in handles:
            try:
                results.append(handle.result())
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        group.wait()
        if first_error is not None:
            raise first_error
        return tuple(results)
    finally:
        runtime.close()


def _active_dependencies(raw_dependencies, extras):
    """Evaluate dependency markers for the extras requested by a consumer."""
    requested = tuple(sorted(set(str(value) for value in extras)))
    active = []
    for raw_requirement in raw_dependencies:
        try:
            requirement = Requirement(raw_requirement)
        except Exception:
            active.append(raw_requirement)
            continue
        marker = requirement.marker
        if marker is None:
            active.append(raw_requirement)
            continue
        environments = requested or ("",)
        if any(
            marker.evaluate({**TARGET_ENVIRONMENT, "extra": extra})
            for extra in environments
        ):
            active.append(raw_requirement)
    return tuple(active)


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        values = dict(attrs)
        if values.get("href"):
            self.links.append(values)


def _fetch_url(url, accept, limit):
    """Fetch bounded index metadata without changing the target ABI probe."""
    cache_path = None
    if CACHE_ROOT:
        cache_key = hashlib.sha256((accept + "\x00" + url).encode("utf-8")).hexdigest()
        cache_path = os.path.join(CACHE_ROOT, cache_key + ".bin")
        try:
            cached = open(cache_path, "rb").read()
            if len(cached) <= limit:
                return cached
        except OSError:
            pass

    def _store(body):
        if cache_path is None:
            return body
        try:
            atomic_replace_bytes(Path(cache_path), body)
        except OSError:
            pass
        return body

    errors = []
    curl = shutil.which("curl")
    if curl:
        try:
            result = subprocess.run(
                (
                    curl,
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--connect-timeout",
                    "5",
                    "--max-time",
                    "10",
                    "--max-filesize",
                    str(limit),
                    "--header",
                    "Accept: " + accept,
                    url,
                ),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=12,
            )
            if len(result.stdout) > limit:
                raise ValueError("metadata response exceeds observation limit")
            return _store(result.stdout)
        except Exception as exc:
            errors.append("curl:" + type(exc).__name__)
    try:
        request = Request(url, headers={"Accept": accept})
        with urlopen(request, timeout=10) as response:
            return _store(response.read(limit))
    except Exception as exc:
        errors.append("urllib:" + type(exc).__name__)
        raise RuntimeError("bounded metadata fetch failed: " + ",".join(errors))


def _versions(raw):
    result = []
    for value in raw:
        try:
            version = str(Version(value))
        except InvalidVersion:
            continue
        if version not in result:
            result.append(version)
    return result


def _package_path(package):
    return package.replace("_", "-").replace(".", "-")


def _sha256_fragment(href):
    for value in urlsplit(href).fragment.split("&"):
        if value.startswith("sha256="):
            return value.split("=", 1)[1]
    return None


def _compatible_python(requires_python):
    if not requires_python:
        return True
    try:
        return SpecifierSet(requires_python).contains(
            Version("%d.%d.%d" % sys.version_info[:3]), prereleases=True
        )
    except Exception:
        return False


def _simple(index_url, package, page_cache):
    key = (index_url, package.lower().replace("_", "-"))
    with _PAGE_LOCKS.for_key(key):
        if key in page_cache:
            return page_cache[key]
        url = urljoin(index_url.rstrip("/") + "/", _package_path(package) + "/")
        try:
            page = _fetch_url(url, "text/html", MAX_PAGE_BYTES + 1)
            if len(page) > MAX_PAGE_BYTES:
                raise ValueError("simple index page exceeds observation limit")
            parser = _Links()
            parser.feed(page.decode("utf-8", "replace"))
            page_cache[key] = (parser.links, None)
        except Exception as exc:
            page_cache[key] = ((), "simple index request failed: " + type(exc).__name__)
        return page_cache[key]


def _artifact(link, version_specifier, target_tags):
    href = link.get("href", "")
    raw_name = unquote(urlsplit(href).path.rsplit("/", 1)[-1])
    if not raw_name.endswith(".whl"):
        return None
    try:
        _name, version, _build, tags = parse_wheel_filename(raw_name)
    except Exception:
        return None
    normalized_version = str(version)
    if version_specifier and not version_specifier.contains(version, prereleases=True):
        return None
    requires_python = link.get("data-requires-python")
    wheel_tags = {str(tag) for tag in tags}
    if not (wheel_tags & target_tags) or not _compatible_python(requires_python):
        return None
    return {
        "filename": raw_name,
        "version": normalized_version,
        "kind": "wheel",
        "sha256": _sha256_fragment(href),
        "metadata_sha256": (
            str(link.get("data-dist-info-metadata") or link.get("data-core-metadata"))
            .removeprefix("sha256=")
            if link.get("data-dist-info-metadata") or link.get("data-core-metadata")
            else None
        ),
        "python_tags": sorted({str(tag).split("-")[0] for tag in wheel_tags}),
        "abi_tags": sorted({str(tag).split("-")[1] for tag in wheel_tags}),
        "platform_tags": sorted({str(tag).split("-")[2] for tag in wheel_tags}),
        "requires_python": requires_python,
        "dependency_requirements": [],
        "_href": href,
    }


def _select(index_url, package, specifier, version_hints, page_cache, target_tags):
    links, error = _simple(index_url, package, page_cache)
    if error:
        return None, (), error
    hints = set(_versions(version_hints))
    candidates = []
    for link in links:
        item = _artifact(link, specifier, target_tags)
        if item is not None and (not hints or item["version"] in hints):
            candidates.append(item)
    if not candidates and hints:
        # Index output can normalize local versions differently from the simple
        # filename. Re-run without the hint set but preserve the requirement.
        for link in links:
            item = _artifact(link, specifier, target_tags)
            if item is not None:
                candidates.append(item)
    if not candidates:
        return None, (), "no compatible binary wheel satisfies the requirement"
    selected = max((item["version"] for item in candidates), key=Version)
    selected_items = sorted(
        [item for item in candidates if item["version"] == selected],
        key=lambda item: item["filename"],
    )
    return selected, selected_items, None


def _read_metadata(artifact, metadata_cache):
    href = artifact["_href"].split("#", 1)[0] + ".metadata"
    with _METADATA_LOCKS.for_key(href):
        if href in metadata_cache:
            deps, error = metadata_cache[href]
        else:
            try:
                body = _fetch_url(href, "application/octet-stream", MAX_METADATA_BYTES + 1)
                if len(body) > MAX_METADATA_BYTES:
                    raise ValueError("package metadata exceeds observation limit")
                expected = artifact.get("metadata_sha256")
                if expected and hashlib.sha256(body).hexdigest() != expected:
                    raise ValueError("package metadata SHA-256 mismatch")
                message = email.parser.BytesParser().parsebytes(body)
                deps = tuple(message.get_all("Requires-Dist", ()))
                error = None
            except Exception as exc:
                deps = ()
                error = "package metadata request failed: " + type(exc).__name__
            metadata_cache[href] = (deps, error)
    artifact["dependency_requirements"] = list(deps)
    return deps, error


def _read_metadata_with_fallback(
    artifact,
    package,
    version,
    metadata_cache,
    page_cache,
    target_tags,
    fallback_index,
):
    """Use a verified public-index metadata twin when a mirror omits PEP 658."""
    # A mirror without a PEP 658 digest does not advertise a metadata
    # endpoint.  Do not first issue a guaranteed .metadata request that can
    # consume the full network timeout for every root/dependency candidate;
    # go directly to the verified same-version public-index twin below.
    if artifact.get("_index_url") != fallback_index and not artifact.get("metadata_sha256"):
        deps, error = (), "mirror does not expose PEP 658 metadata"
    else:
        deps, error = _read_metadata(artifact, metadata_cache)
    if error is None or artifact.get("_index_url") == fallback_index:
        return deps, error
    try:
        exact = SpecifierSet("==" + str(version))
        fallback_version, fallback_artifacts, fallback_error = _select(
            fallback_index,
            package,
            exact,
            (version,),
            page_cache,
            target_tags,
        )
    except Exception as exc:
        return deps, error + "; fallback metadata selection failed: " + type(exc).__name__
    if fallback_error or fallback_version != str(version) or not fallback_artifacts:
        return deps, error + "; fallback metadata artifact unavailable"
    fallback_deps, fallback_metadata_error = _read_metadata(
        fallback_artifacts[0], metadata_cache
    )
    if fallback_metadata_error is not None:
        return deps, error + "; fallback metadata request failed: " + fallback_metadata_error
    artifact["dependency_requirements"] = list(fallback_deps)
    return fallback_deps, None


def _public_artifact(item):
    return {key: value for key, value in item.items() if not key.startswith("_")}


def _screen_root_candidate(
    version,
    *,
    index_url,
    package,
    preferred_versions,
    page_cache,
    metadata_cache,
    target_tags,
    fallback_index,
):
    selected_version, artifacts, selection_error = _select(
        index_url,
        package,
        SpecifierSet("==" + str(version)),
        (version,),
        page_cache,
        target_tags,
    )
    if selection_error or selected_version is None or not artifacts:
        return {
            "version": str(version),
            "compatible": False,
            "error": selection_error or "no compatible root wheel",
        }
    artifact = artifacts[0]
    artifact["_index_url"] = index_url
    dependencies, metadata_error = _read_metadata_with_fallback(
        artifact,
        package,
        selected_version,
        metadata_cache,
        page_cache,
        target_tags,
        fallback_index,
    )
    if metadata_error:
        return {"version": str(version), "compatible": False, "error": metadata_error}
    dependency_error = _preferred_dependency_error(dependencies, preferred_versions)
    return {
        "version": str(version),
        "compatible": dependency_error is None,
        "error": dependency_error,
    }


def _preferred_dependency_error(dependencies, preferred_versions):
    for raw_requirement in dependencies:
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement:
            continue
        preferred = preferred_versions.get(requirement.name.lower().replace("_", "-"))
        if preferred and not requirement.specifier.contains(Version(preferred), prereleases=True):
            return (
                f"preferred runtime package {requirement.name}=={preferred} "
                f"does not satisfy root requirement {raw_requirement}"
            )
    return None


def _collect_node_constraints(
    current,
    *,
    constraints,
    constraint_text,
    extra_requests,
    index_hints,
):
    for raw_requirement in _active_dependencies(
        current["dependencies"], current.get("extras", ())
    ):
        try:
            requirement = Requirement(raw_requirement)
        except Exception:
            return "invalid dependency requirement: " + raw_requirement
        if requirement.url:
            return "direct URL dependency is not reproducibly indexed: " + requirement.name
        normalized = requirement.name.lower().replace("_", "-")
        constraints.setdefault(normalized, []).append(str(requirement.specifier))
        constraint_text.setdefault(normalized, []).append(str(requirement.specifier) or "any")
        extra_requests.setdefault(normalized, set()).update(requirement.extras)
        index_hints.setdefault(normalized, current["index_url"])
    return None


def _collect_constraints(order, selected, *, extra_requests, index_hints):
    constraints = {}
    constraint_text = {}
    for current_name in tuple(order):
        error = _collect_node_constraints(
            selected[current_name],
            constraints=constraints,
            constraint_text=constraint_text,
            extra_requests=extra_requests,
            index_hints=index_hints,
        )
        if error is not None:
            return constraints, constraint_text, error
    return constraints, constraint_text, None


def _closure_entries(constraints, *, index_hints, extra_requests):
    return tuple(
        (
            normalized,
            ",".join(value for value in values if value),
            index_hints[normalized],
            tuple(sorted(extra_requests.get(normalized, ()))),
        )
        for normalized, values in constraints.items()
    )


def _resolve_constrained_package(
    entry,
    *,
    selected,
    root_name,
    fallback_index,
    preferred_versions,
    page_cache,
    target_tags,
    metadata_cache,
):
    normalized, specifier_text, index_hint, requested_extras = entry
    existing = selected.get(normalized)
    requested_extras = tuple(sorted(set(requested_extras)))
    try:
        combined = SpecifierSet(specifier_text) if specifier_text else None
    except InvalidSpecifier:
        return normalized, None, True, "dependency closure requirement evaluation failed for " + normalized
    if existing is not None:
        existing_extras = set(existing.get("extras", ()))
        if (
            (combined is None or combined.contains(Version(existing["version"]), prereleases=True))
            and set(requested_extras).issubset(existing_extras)
        ):
            return normalized, existing, False, None
        if normalized == root_name:
            return normalized, None, True, "dependency closure constraints conflict with root package " + normalized
    candidate = None
    selected_index = index_hint
    indexes = [index_hint]
    if fallback_index not in indexes:
        indexes.append(fallback_index)
    for dependency_index in indexes:
        selection_specifier = combined
        preferred = preferred_versions.get(normalized)
        if preferred:
            selection_specifier = SpecifierSet(
                (specifier_text + "," if specifier_text else "") + "==" + str(preferred)
            )
        observed = _select(
            dependency_index,
            normalized,
            selection_specifier,
            (),
            page_cache,
            target_tags,
        )
        if observed[0] is not None and observed[1]:
            candidate = observed
            selected_index = dependency_index
            break
    if candidate is None:
        candidate = (None, (), None)
    if candidate[0] is None or not candidate[1]:
        return (
            normalized,
            None,
            True,
            "no compatible binary wheel satisfies all requirements for "
            + normalized
            + (": " + specifier_text if specifier_text else ""),
        )
    dependency_version, dependency_artifacts, dependency_error = candidate
    if dependency_error:
        return normalized, None, True, dependency_error + ": " + normalized
    dependency_artifact = dependency_artifacts[0]
    dependency_artifact["_index_url"] = selected_index
    dependency_deps, dependency_metadata_error = _read_metadata_with_fallback(
        dependency_artifact,
        normalized,
        dependency_version,
        metadata_cache,
        page_cache,
        target_tags,
        fallback_index,
    )
    if dependency_metadata_error:
        return normalized, None, True, dependency_metadata_error + ": " + normalized
    return (
        normalized,
        {
            "package": normalized,
            "version": dependency_version,
            "index_url": selected_index,
            "artifact": dependency_artifact,
            "dependencies": dependency_deps,
            "extras": requested_extras,
        },
        existing is None
        or existing["version"] != dependency_version
        or set(existing.get("extras", ())) != set(requested_extras),
        None,
    )


def _apply_resolution(resolved, *, selected, order, constraint_text):
    changed = False
    for normalized, node, node_changed, node_error in resolved:
        if node_error:
            suffix = (
                " [constraints=" + ",".join(constraint_text.get(normalized, ())) + "]"
                if constraint_text.get(normalized)
                else ""
            )
            return changed, node_error + suffix
        if node_changed:
            selected[normalized] = node
            if normalized not in order:
                order.append(normalized)
            changed = True
    return changed, None


def _resolve_dependency_closure(
    *,
    root_name,
    root_version,
    root_artifact,
    root_deps,
    index_url,
    fallback_index,
    preferred_versions,
    page_cache,
    metadata_cache,
    target_tags,
    initial_error,
):
    """Resolve the dependency graph through bounded, parallel fixed-point rounds.

    Algorithm-Complexity: O(N^2)
    Algorithm-Rationale: Each fixed-point round inspects the currently selected dependency nodes, and at most N new or changed nodes can force another round before the MAX_NODES safety bound terminates resolution.
    """
    selected = {
        root_name: {
            "package": root_name,
            "version": root_version,
            "index_url": index_url,
            "artifact": root_artifact,
            "dependencies": root_deps,
            "extras": (),
        }
    }
    order = [root_name]
    index_hints = {root_name: index_url}
    extra_requests = {}
    closure_error = initial_error
    iteration = 0
    while closure_error is None:
        iteration += 1
        if iteration > MAX_NODES or len(selected) > MAX_NODES:
            closure_error = "dependency closure exceeds observation limit"
            break
        constraints, constraint_text, closure_error = _collect_constraints(
            order,
            selected,
            extra_requests=extra_requests,
            index_hints=index_hints,
        )
        if closure_error is not None:
            break
        entries = _closure_entries(
            constraints,
            index_hints=index_hints,
            extra_requests=extra_requests,
        )
        resolved = _blocking_map(
            f"dependency-closure-{iteration}",
            lambda entry: _resolve_constrained_package(
                entry,
                selected=selected,
                root_name=root_name,
                fallback_index=fallback_index,
                preferred_versions=preferred_versions,
                page_cache=page_cache,
                target_tags=target_tags,
                metadata_cache=metadata_cache,
            ),
            entries,
        )
        changed, closure_error = _apply_resolution(
            resolved,
            selected=selected,
            order=order,
            constraint_text=constraint_text,
        )
        if closure_error is not None or not changed:
            break
    nodes = tuple(
        {
            "package": normalized,
            "version": selected[normalized]["version"],
            "index_url": selected[normalized]["index_url"],
            "artifact": _public_artifact(selected[normalized]["artifact"]),
        }
        for normalized in order
    )
    return nodes, closure_error


def _emit_root_error(root_error):
    print(json.dumps({
        "selected_version": None,
        "artifacts": [],
        "dependency_nodes": [],
        "dependency_closure_complete": False,
        "dependency_closure_error": root_error,
        "error": root_error,
    }, sort_keys=True))


def main(argv=None):
    global CACHE_ROOT
    argv = sys.argv if argv is None else argv
    index_url, package, raw_versions, fallback_index = argv[1], argv[2], json.loads(argv[3]), argv[4]
    preferred_versions = json.loads(argv[5])
    root_version_hint = argv[6] if len(argv) > 6 and argv[6] else None
    root_candidate_versions = json.loads(argv[7]) if len(argv) > 7 and argv[7] else []
    CACHE_ROOT = argv[8] if len(argv) > 8 and argv[8] else ""
    page_cache = {}
    metadata_cache = {}
    target_tags = {str(tag) for tag in sys_tags()}

    if root_candidate_versions:
        root_candidates = _blocking_map(
            "root-candidate-screen",
            lambda version: _screen_root_candidate(
                version,
                index_url=index_url,
                package=package,
                preferred_versions=preferred_versions,
                page_cache=page_cache,
                metadata_cache=metadata_cache,
                target_tags=target_tags,
                fallback_index=fallback_index,
            ),
            root_candidate_versions,
        )
        print(json.dumps({"root_candidates": root_candidates}, sort_keys=True))
        raise SystemExit(0)

    root_version, root_artifacts, root_error = _select(
        index_url,
        package,
        SpecifierSet("==" + root_version_hint) if root_version_hint else None,
        (root_version_hint,) if root_version_hint else raw_versions,
        page_cache,
        target_tags,
    )
    if root_error:
        _emit_root_error(root_error)
        raise SystemExit(0)

    root_artifact = root_artifacts[0]
    root_artifact["_index_url"] = index_url
    root_deps, root_metadata_error = _read_metadata_with_fallback(
        root_artifact,
        package,
        root_version,
        metadata_cache,
        page_cache,
        target_tags,
        fallback_index,
    )
    preferred_error = _preferred_dependency_error(root_deps, preferred_versions)
    root_name = package.lower().replace("_", "-")
    nodes, closure_error = _resolve_dependency_closure(
        root_name=root_name,
        root_version=root_version,
        root_artifact=root_artifact,
        root_deps=root_deps,
        index_url=index_url,
        fallback_index=fallback_index,
        preferred_versions=preferred_versions,
        page_cache=page_cache,
        metadata_cache=metadata_cache,
        target_tags=target_tags,
        initial_error=root_metadata_error or preferred_error,
    )
    print(json.dumps({
        "selected_version": root_version,
        "artifacts": [_public_artifact(item) for item in root_artifacts],
        "dependency_nodes": list(nodes),
        "dependency_closure_complete": closure_error is None,
        "dependency_closure_error": closure_error,
        "error": None,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
