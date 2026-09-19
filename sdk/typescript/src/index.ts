export type MachineKind =
  | "experiment" | "run" | "method" | "agent"
  | "memory" | "environment" | "evaluation";

export interface ProgramLock {
  code_digest: string;
  dependency_digest: string;
  schema_digest: string;
  interpreter_digest: string;
  data_digest: string;
  config_digest: string;
  lock_digest: string;
}

export interface MachineCommand {
  command_id: string;
  machine_id: string;
  expected_revision: number;
  kind: string;
  payload: unknown;
  scope: readonly string[];
  deadline_at?: number;
  parent_command_id?: string;
  idempotency_key?: string;
  payload_digest: string;
}

export interface RunBinding {
  kernel_abi_version: string;
  machine_implementation_digest: string;
  program_digest: string;
  capability_provider_versions: readonly (readonly [string, string])[];  schema_versions: readonly string[];
  environment_version: string;
  policy_version: string;
  binding_digest: string;
}

export interface MachineInspection {
  machine_id: string;
  revision: number;
  status: string;
  state_digest: string;
  commit_ids: readonly string[];
  evidence_refs: readonly string[];
  artifact_refs: readonly string[];
}

function normalize(value: unknown): unknown {
  if (value === null || typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("canonical JSON rejects non-finite numbers");
    return value;
  }
  if (Array.isArray(value)) return value.map(normalize);
  if (typeof value === "object") {
    const object = value as Record<string, unknown>;    return Object.keys(object).sort().reduce<Record<string, unknown>>((out, key) => {
      out[key] = normalize(object[key]);
      return out;
    }, {});
  }
  throw new TypeError("canonical JSON accepts JSON values only");
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(normalize(value));
}

export async function sha256Hex(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((item) => item.toString(16).padStart(2, "0"))
    .join("");
}

export function assertSha256(value: string, field = "digest"): string {
  if (!/^[0-9a-f]{64}$/.test(value)) throw new TypeError(field + " must be lowercase SHA-256");
  return value;
}export function commandIdentity(command: Omit<MachineCommand, "payload_digest">): unknown {
  return {
    command_id: command.command_id,
    machine_id: command.machine_id,
    expected_revision: command.expected_revision,
    kind: command.kind,
    payload: command.payload,
    scope: command.scope,
    deadline_at: command.deadline_at ?? null,
    parent_command_id: command.parent_command_id ?? null,
    idempotency_key: command.idempotency_key ?? null,
  };
}

export async function withCommandDigest(
  command: Omit<MachineCommand, "payload_digest">,
): Promise<MachineCommand> {
  return { ...command, payload_digest: await sha256Hex(commandIdentity(command)) };
}

export async function bindingIdentity(binding: Omit<RunBinding, "binding_digest">): Promise<string> {
  return sha256Hex({
    kernel_abi_version: binding.kernel_abi_version,
    machine_implementation_digest: binding.machine_implementation_digest,
    program_digest: binding.program_digest,    capability_provider_versions: binding.capability_provider_versions,
    schema_versions: binding.schema_versions,
    environment_version: binding.environment_version,
    policy_version: binding.policy_version,
  });
}

export function requireScope(granted: readonly string[], required: string): void {
  if (!granted.includes(required)) throw new Error("capability scope denied: " + required);
}
