# Historical Documents

Historical notes record platform engineering decisions at a point in time. They are retained for auditability but never override current architecture, governance, infrastructure, or status contracts.

The upstream repository keeps platform-owned engineering history under [`rounds/platform/`](rounds/platform/).

Project-specific scientific methods, benchmark/environment work, deployment incidents, experiment execution, and result history belong in the downstream repository that owns those concerns. The 0.43.0 repository split deliberately removes that history from the reusable upstream tree while preserving it in downstream Git history.

When a current platform decision changes, update the owning current document and add a new platform round note that explains the migration and evidence.
