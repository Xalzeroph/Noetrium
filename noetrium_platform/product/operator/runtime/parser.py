from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog="noetrium-forensics",description="Noetrium unified operator control plane")
    sub=p.add_subparsers(dest="command",required=True)
    def forensic(name,help):
        sp=sub.add_parser(name,help=help); sp.add_argument("root",type=Path,help="forensic run root"); return sp
    forensic("verify-evidence","verify authoritative forensic chains")
    sp=forensic("status","joined read-only subsystem status"); sp.add_argument("--model-state",type=Path); sp.add_argument("--study-state",type=Path)
    sp=forensic("locate","locate one opaque ID across forensic evidence"); sp.add_argument("object_id")
    sp=forensic("why","diagnose one failure"); sp.add_argument("failure_id"); sp.add_argument("--graph",action="store_true")
    sp=forensic("graph","explicit-reference causal graph for one object"); sp.add_argument("object_id"); sp.add_argument("--limit",type=int,default=200)
    sp=forensic("timeline","time-correlated forensic timeline; adjacency is not causality"); sp.add_argument("object_id"); sp.add_argument("--seconds",type=float,default=30.0)
    sp=forensic("last-writer","last authoritative writer for a state"); sp.add_argument("run_id"); sp.add_argument("state_name")
    sp=forensic("unclosed-operations","list operation invocations with STARTED but no terminal event"); sp.add_argument("--run-id"); sp.add_argument("--limit",type=int,default=100)
    sp=forensic("crash-bundle","publish immutable crash-bundle manifest"); sp.add_argument("failure_id"); sp.add_argument("output",type=Path)
    sp=forensic("debug-snapshot","joined one-shot debugging snapshot for an object/failure"); sp.add_argument("object_id"); sp.add_argument("--seconds",type=float,default=30.0); sp.add_argument("--telemetry-db",type=Path); sp.add_argument("--metric-limit",type=int,default=2000)
    sp=forensic("triage-plan","deterministic evidence-first debugging plan for one failure"); sp.add_argument("failure_id")
    forensic("index-status","compare derived forensic index cut with authoritative ledgers")
    sp=forensic("rebuild-index","explicitly rebuild disposable forensic index from verified ledgers")
    sp=sub.add_parser("telemetry-query",help="read raw telemetry without mutating its database"); sp.add_argument("db",type=Path); sp.add_argument("run_id"); sp.add_argument("--metric"); sp.add_argument("--decision-cycle-id"); sp.add_argument("--limit",type=int,default=1000)
    sp=sub.add_parser("telemetry-summary",help="compute exact sample summary from raw metric rows"); sp.add_argument("db",type=Path); sp.add_argument("run_id"); sp.add_argument("metric")
    sp=sub.add_parser("recovery-state",help="read durable exact-recovery transaction state"); sp.add_argument("path",type=Path)
    sp=sub.add_parser("release-verify",help="verify source tree against hash-complete release manifest"); sp.add_argument("root",type=Path); sp.add_argument("manifest",type=Path)
    sp=sub.add_parser("runtime-status",help="joined exact runtime/service/model/forensic status from one layout"); sp.add_argument("layout",type=Path)
    sp=sub.add_parser("runtime-recovery-plan",help="read-only component recovery plan from joined runtime status"); sp.add_argument("layout",type=Path)
    sp=sub.add_parser("failure-catalog",help="query stable failure taxonomy and recovery semantics"); sp.add_argument("--domain"); sp.add_argument("--code")
    sp=sub.add_parser("crash-bundle-verify",help="verify an offline crash bundle without opening forensic DB"); sp.add_argument("path",type=Path)
    sp=sub.add_parser("architecture-report",help="physical import/authority/hotspot report"); sp.add_argument("source_root",type=Path)
    sub.add_parser("architecture-gate",help="run declared architecture gate")
    return p
