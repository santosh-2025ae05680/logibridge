#!/usr/bin/env python3
"""OTA bandwidth saving for the layer-cache demo (Task D2).

Compares two tags in the local registry. Layers shared by both tags are already on
the truck, so an update only transfers the new layers (compressed sizes from the
registry manifests).
"""
import argparse
import json
import urllib.request

ACCEPT = ", ".join([
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
])


def fetch(registry, repo, ref):
    req = urllib.request.Request(f"http://{registry}/v2/{repo}/manifests/{ref}",
                                 headers={"Accept": ACCEPT})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def layers(registry, repo, tag):
    m = fetch(registry, repo, tag)
    if "manifests" in m:                    # image index: take the first real image
        entry = next(e for e in m["manifests"]
                     if e.get("platform", {}).get("os") != "unknown")
        m = fetch(registry, repo, entry["digest"])
    return {layer["digest"]: layer["size"] for layer in m["layers"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--registry", default="localhost:5000")
    p.add_argument("--repo", default="logibridge-inference")
    p.add_argument("--old", required=True, help="tag already on the trucks")
    p.add_argument("--new", required=True, help="tag being rolled out")
    p.add_argument("--trucks", type=int, default=85)
    p.add_argument("--cost-per-mb", type=float, default=0.10)
    a = p.parse_args()

    old = layers(a.registry, a.repo, a.old)
    new = layers(a.registry, a.repo, a.new)
    print(f"{'layer':14}{'size KB':>12}  status")
    for digest, size in new.items():
        status = "shared (already on truck)" if digest in old else "NEW"
        print(f"{digest[7:19]:14}{size / 1024:12.1f}  {status}")

    full = sum(new.values())
    delta = sum(s for d, s in new.items() if d not in old)
    n, c = a.trucks, a.cost_per_mb
    print(f"\nFull image pull : {full / 1e6:10.3f} MB/truck x {n} = {full / 1e6 * n:10.2f} MB"
          f"  -> Rs {full / 1e6 * n * c:.2f}")
    print(f"Layer-cache OTA : {delta / 1e6:10.5f} MB/truck x {n} = {delta / 1e6 * n:10.4f} MB"
          f"  -> Rs {delta / 1e6 * n * c:.4f}")
    print(f"Saving          : {100 * (1 - delta / full):.2f}%  ({full / max(delta, 1):,.0f}x less data)")


if __name__ == "__main__":
    main()
