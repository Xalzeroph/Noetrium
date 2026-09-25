# Server tmux runtime policy

The production server uses **tmux for terminal/controller persistence**, not as a replacement for the platform's runtime authorities.

## Authority split

```text
tmux session
  └─ keeps the outer exact RuntimeManager command alive across SSH disconnects

RuntimeManager
  └─ owns exact verification / reconciliation / start ordering

Service OS
  └─ owns exact PID + process-start identity + readiness + stop semantics

Checkpoint / effect journals
  └─ own scientific and external-effect recovery truth

Forensics
  └─ owns durable causal evidence
```

A tmux session existing does **not** mean a model service or Study is healthy. `tmux has-session` must never replace exact process reconciliation or runtime status.

## Immutable code updates

Active runs execute from content-addressed release directories:

```text
SERVER_ROOT/
  releases/
    <release_sha256>/
      ... frozen code ...
```

Do not edit the code inside an active release directory. A code change must produce:

```text
new source tree
→ new release digest
→ new release directory
→ new RunLaunchManifest
→ new tmux session binding
```

The tmux session name includes the runtime manifest digest. The durable session
binding also freezes the full controller argv/cwd, target-launcher digest,
controller-environment digest and tmux transport identity. The server
bootstrap reads argv and launcher identity from `RunLaunchManifest`; it cannot
receive a competing argv. Reusing the same session name with different
code/command/transport is a hard drift error.

## Managed server runtime entry

The runtime controller is launched only through the server profile and the
frozen `RunLaunchManifest`. The entry does not accept a release root, tmux
executable, binding root or replacement command from the caller:

```bash
python scripts/server_runtime.py server-a \
  --profile-file configs/server_profiles/server-a.local.env \
  --control-id project-runtime \
  --manifest-file /local/run-manifest.json \
  --controller-environment-file /local/controller.env \
  --interactive
```

The manifest owns the exact controller argv, release digest, launcher identity,
environment digest, host/model/experiment identities and session policy. The
server composition owns the remote release layout, tmux binary, local binding
and recovery state. The entry first verifies the remote content-addressed
release directory through an observation port, then performs the durable
bootstrap transaction. A failed or uncertain session mutation enters the same
server operation recovery gate as release publication and file transfer.

Use `scripts/server_session.py status` for the operator shell and the normal
runtime/service health authorities for scientific process health. A tmux
session alone never proves that a model, environment service or study is healthy.
