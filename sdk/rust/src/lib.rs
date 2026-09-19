use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct ProgramLock {
    pub code_digest: String,
    pub dependency_digest: String,
    pub schema_digest: String,
    pub interpreter_digest: String,
    pub data_digest: String,
    pub config_digest: String,
    pub lock_digest: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct MachineCommand {
    pub command_id: String,
    pub machine_id: String,
    pub expected_revision: u64,
    pub kind: String,
    pub payload: Value,
    pub scope: Vec<String>,
    pub deadline_at: Option<f64>,
    pub parent_command_id: Option<String>,
    pub idempotency_key: Option<String>,
    pub payload_digest: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct RunBinding {
    pub kernel_abi_version: String,
    pub machine_implementation_digest: String,
    pub program_digest: String,
    pub capability_provider_versions: Vec<(String, String)>,
    pub schema_versions: Vec<String>,
    pub environment_version: String,
    pub policy_version: String,
    pub binding_digest: String,
}
fn canonical_value(value: &Value) -> Value {
    match value {
        Value::Object(object) => {
            let mut sorted = BTreeMap::new();
            for (key, item) in object {
                sorted.insert(key.clone(), canonical_value(item));
            }
            let mut result = Map::new();
            for (key, item) in sorted {
                result.insert(key, item);
            }
            Value::Object(result)
        }
        Value::Array(items) => Value::Array(items.iter().map(canonical_value).collect()),
        other => other.clone(),
    }
}

pub fn canonical_json(value: &Value) -> Result<String, serde_json::Error> {
    serde_json::to_string(&canonical_value(value))
}

pub fn sha256_hex(value: &Value) -> Result<String, serde_json::Error> {
    let bytes = canonical_json(value)?;
    let mut hasher = Sha256::new();
    hasher.update(bytes.as_bytes());
    Ok(format!("{:x}", hasher.finalize()))
}

pub fn assert_sha256(value: &str) -> Result<(), String> {
    if value.len() == 64 && value.bytes().all(|item| item.is_ascii_hexdigit() && !item.is_ascii_uppercase()) {
        Ok(())
    } else {
        Err("value must be lowercase SHA-256".to_string())
    }
}
pub fn command_identity(command: &MachineCommand) -> Value {
    serde_json::json!({
        "command_id": command.command_id,
        "machine_id": command.machine_id,
        "expected_revision": command.expected_revision,
        "kind": command.kind,
        "payload": command.payload,
        "scope": command.scope,
        "deadline_at": command.deadline_at,
        "parent_command_id": command.parent_command_id,
        "idempotency_key": command.idempotency_key,
    })
}

pub fn require_scope(granted: &[String], required: &str) -> Result<(), String> {
    if granted.iter().any(|item| item == required) {
        Ok(())
    } else {
        Err(format!("capability scope denied: {}", required))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_object_order_is_stable() {
        let value: Value = serde_json::json!({"z": 1, "a": {"y": 2, "b": 3}});
        assert_eq!(canonical_json(&value).unwrap(), r#"{"a":{"b":3,"y":2},"z":1}"#);
    }

    #[test]
    fn scope_is_explicit() {
        assert!(require_scope(&["run.read".into()], "run.read").is_ok());
        assert!(require_scope(&[], "run.read").is_err());
    }
}
