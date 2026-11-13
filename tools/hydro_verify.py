#!/usr/bin/env python3
"""
hydro_verify.py — unified fast verification gate for HYDRO BRAIN (inspired by
claude-code-best-practice Stop/verification loops and Harness2 checks).

Usage:
    python3 -I tools/hydro_verify.py --quick [--json]
    python3 -I tools/hydro_verify.py --full [--json]
"""
import argparse, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
import tree_validate  # noqa: E402


def _run(cmd, timeout=180):
    p = subprocess.run(cmd, cwd=B.ROOT, capture_output=True, text=True, timeout=timeout)
    return {
        "cmd": " ".join(cmd),
        "ok": p.returncode == 0,
        "code": p.returncode,
        "stdout": p.stdout.strip(),
        "stderr": p.stderr.strip(),
    }


def quick_verify(root=None):
    root = root or B.ROOT
    err, warn = tree_validate.validate(root)
    checks = [{
        "name": "tree_validate",
        "ok": not err,
        "errors": err,
        "warnings": len(warn),
    }]
    # Quick route_eval check against eval sets
    eval_res = _run([sys.executable, "-I", os.path.join(root, "tools", "route_eval.py")], timeout=60)
    checks.append({
        "name": "route_eval",
        "ok": eval_res["ok"],
        "summary": eval_res["stdout"].splitlines(),
    })
    ok = all(c["ok"] for c in checks)
    return {"mode": "quick", "ok": ok, "checks": checks}


def full_verify(root=None):
    root = root or B.ROOT
    res = quick_verify(root)
    res["mode"] = "full"
    scan_out = "/tmp/hydro-verify-scan"
    audit_out = "/tmp/hydro-verify-audit"
    for name, cmd in (
        ("vault_scan", [sys.executable, "-I", os.path.join(root, "tools", "vault_scan.py"), "--vault", os.path.join(root, "Brain System"), "--out", scan_out]),
        ("vault_audit", [sys.executable, "-I", os.path.join(root, "tools", "vault_audit.py"), "--vault", os.path.join(root, "Brain System"), "--out", audit_out]),
        ("test_all", ["bash", os.path.join(root, "tools", "test_all.sh")]),
    ):
        r = _run(cmd, timeout=240)
        res["checks"].append({"name": name, "ok": r["ok"], "code": r["code"], "stdout": r["stdout"][-1200:], "stderr": r["stderr"][-600:]})
    res["ok"] = all(c["ok"] for c in res["checks"])
    return res


def main():
    ap = argparse.ArgumentParser(description="Verify HYDRO BRAIN harness, routing evals, vault hygiene, and test suite.")
    ap.add_argument("--quick", action="store_true", help="Run fast tree_validate + route_eval gate")
    ap.add_argument("--full", action="store_true", help="Run quick checks + vault_scan + vault_audit + test_all.sh")
    ap.add_argument("--json", action="store_true", help="Emit JSON output")
    ap.add_argument("--root", default=B.ROOT)
    a = ap.parse_args()

    out = full_verify(a.root) if a.full else quick_verify(a.root)
    if a.json:
        print(json.dumps(out, indent=1, ensure_ascii=False))
    else:
        status = "PASS" if out["ok"] else "FAIL"
        print(f"hydro_verify ({out['mode']}): {status}")
        for c in out["checks"]:
            mark = "OK" if c["ok"] else "FAIL"
            print(f"  [{mark}] {c['name']}")
            if not c["ok"]:
                print("   ", json.dumps(c, ensure_ascii=False)[:600])
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
