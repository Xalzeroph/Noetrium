# Native Runtime Asset System

Native libraries are part of a serving/runtime qualification closure, not an implicit host precondition. Python dependency resolution alone cannot prove that a runtime has the CUDA, BLAS, collective, compiler, or other native assets required by the selected backend.

## Problem

A process can have a complete Python package graph and still fail at import or first execution because a required DSO is absent, incompatible, or not linker-visible. The platform therefore models native runtime assets as evidence-bearing dependencies.

## Ownership

The model/deployment qualification system owns the immutable qualification decision. Runtime-asset and environment/resource providers own discovery and materialization of their respective assets. Process/service runtime owns launch and health observations. No subsystem may silently install a native dependency after a qualification plan has been frozen.

## Native asset closure

A qualified plan may include Python packages and native assets. For every required native artifact the plan records enough identity to prove architecture, ABI/runtime family, provenance, and materialization intent.
## Qualification data flow

```text
read-only host/runtime facts
        ↓
backend + dependency closure
        ↓
native requirement resolution
        ↓
exact materialization plan
        ↓
post-materialization DSO/import/device/collective probes
        ↓
runtime qualification receipt
```

A candidate is rejected when its artifact type or provenance cannot prove that it supplies the required native capability. A similarly named package or a platform-independent placeholder is not sufficient evidence.

## Provider rule

Native repair is an explicit provider action with an operation receipt and post-install verification. The platform does not replace a runtime, change accelerator libraries, downgrade an engine, or choose an alternate package merely to make qualification pass.
## Verification boundary

Native-asset qualification proves a runtime prerequisite only. It is not a serving success, workload success, or downstream scientific result. Serving qualification still requires the exact endpoint/runtime probes defined by the deployment system.

Future providers should continue to improve linker/ELF inspection, architecture and ABI checks, system-toolkit discovery, and reversible materialization while preserving the same fail-closed contract.
