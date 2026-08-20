"""
Dump the API contract so the frontend client can be written against it exactly.

Reads the OpenAPI document straight from the app (no server needed) and prints
each path, its methods, required request fields and response fields. Writing the
TypeScript client from this rather than from memory is what stops a whole class
of integration bug: a field renamed in the router but not the client fails
silently as ``undefined`` at runtime.

Usage:
    python scripts/dump_contract.py [substring-filter]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def resolve(schema: dict, spec: dict) -> dict:
    """Follow a $ref, and unwrap the allOf FastAPI emits for defaulted bodies.

    A Pydantic body parameter with a default renders as
    ``{"allOf": [{"$ref": ...}], "default": {}}``. Without unwrapping it the
    dump shows a bare "?" and looks like an untyped body when it is not.
    """
    if not schema:
        return {}

    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        return spec.get("components", {}).get("schemas", {}).get(name, {})

    all_of = schema.get("allOf")
    if all_of:
        # Merge the members; in practice FastAPI emits exactly one.
        merged: dict = {"properties": {}, "required": []}
        for member in all_of:
            part = resolve(member, spec)
            merged["properties"].update(part.get("properties") or {})
            merged["required"].extend(part.get("required") or [])
        return merged

    return schema


def describe(schema: dict, spec: dict) -> str:
    schema = resolve(schema, spec)
    props = schema.get("properties") or {}
    if not props:
        return schema.get("type", "?")
    required = set(schema.get("required") or [])
    parts = []
    for name, prop in props.items():
        prop = resolve(prop, spec)
        t = prop.get("type")
        if not t and "anyOf" in prop:
            inner = [resolve(o, spec).get("type") for o in prop["anyOf"]]
            t = "|".join(x for x in inner if x)
        parts.append(f"{name}{'' if name in required else '?'}:{t or '?'}")
    return "{ " + ", ".join(parts) + " }"


def main() -> int:
    from app.main import app

    spec = app.openapi()
    needle = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    for path in sorted(spec["paths"]):
        if needle and needle not in path.lower():
            continue
        for method, op in sorted(spec["paths"][path].items()):
            if method not in ("get", "post", "patch", "put", "delete"):
                continue
            print(f"\n{method.upper()} {path}")

            params = op.get("parameters") or []
            if params:
                rendered = ", ".join(
                    f"{p['name']}{'' if p.get('required') else '?'}"
                    f":{resolve(p.get('schema', {}), spec).get('type', '?')}"
                    f"({p.get('in')})"
                    for p in params
                )
                print(f"  params   {rendered}")

            body = (
                op.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if body:
                print(f"  body     {describe(body, spec)}")

            for code in sorted(op.get("responses", {})):
                content = (
                    op["responses"][code]
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema")
                )
                if not content:
                    continue
                if content.get("type") == "array":
                    print(f"  {code}      [{describe(content.get('items', {}), spec)}]")
                else:
                    print(f"  {code}      {describe(content, spec)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
