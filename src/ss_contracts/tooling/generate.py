"""Generate every output format from the registry, and the drift gate for committed models.

| Format | Output | Committed |
| --- | --- | --- |
| `pydantic` | `<modelsDir>/<module>.py` and `<modelsDir>/__init__.py` | yes, drift-gated |
| `jsonschema` | `<generatedDir>/jsonschema/<id>.schema.json` | no |
| `avro` | `<generatedDir>/avro/<id>.avsc` | no |
| `proto` | `<generatedDir>/proto/<module>.proto`, compiled to `<module>.pb` and `<module>_pb2.py` | no |
| `parquet` | `<generatedDir>/parquet/<id>.parquet.json` and `<id>.schema.parquet` | no |

`check=True` generates the Python models in memory and compares them with the committed files:
a contract edited without regenerating, a hand edit, a missing module, or a stale module fails.
"""

import pathlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from ss_contracts.tooling.gen import avro, jsonschema_gen, parquet, proto, pydantic_gen
from ss_contracts.tooling.gen.checker import FORMATS, generation_errors
from ss_contracts.tooling.odcs import ContractSpec
from ss_contracts.tooling.registry import Registry

INIT_MODULE = "__init__.py"

# Suffixes each format owns inside its generated directory; stale files are removed.
_OWNED_SUFFIXES: dict[str, tuple[str, ...]] = {
    "jsonschema": (".schema.json",),
    "avro": (".avsc",),
    "proto": (".proto", ".pb", "_pb2.py"),
    "parquet": (".parquet.json", ".schema.parquet"),
}


@dataclass
class GenerationReport:
    written: list[pathlib.Path] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.drift


def source_label(registry: Registry, spec: ContractSpec) -> str:
    return spec.source.resolve().relative_to(registry.root).as_posix()


def model_sources(registry: Registry, specs: Iterable[ContractSpec]) -> dict[str, str]:
    """Generated model files keyed by file name, including the package `__init__`."""
    specs = list(specs)
    sources = {
        f"{pydantic_gen.module_name(spec.contract_id)}.py": pydantic_gen.render_module(
            spec, source_label(registry, spec)
        )
        for spec in specs
    }
    sources[INIT_MODULE] = pydantic_gen.render_package_init(specs)
    return sources


def model_drift(registry: Registry, sources: Mapping[str, str]) -> list[str]:
    """Differences between freshly generated model sources and the committed files."""
    models_dir = registry.models_dir
    drift: list[str] = []
    for name, text in sorted(sources.items()):
        path = models_dir / name
        if not path.is_file():
            drift.append(f"{path} is missing; run 'make contracts-gen'")
        elif path.read_text(encoding="utf-8") != text:
            drift.append(f"{path} differs from its contract; run 'make contracts-gen'")
    if models_dir.is_dir():
        for path in sorted(models_dir.glob("*.py")):
            if path.name not in sources:
                drift.append(f"{path} has no registered contract; run 'make contracts-gen'")
    return drift


def _write_models(registry: Registry, sources: Mapping[str, str]) -> list[pathlib.Path]:
    models_dir = registry.models_dir
    models_dir.mkdir(parents=True, exist_ok=True)
    for path in models_dir.glob("*.py"):
        if path.name not in sources:
            path.unlink()
    written = []
    for name, text in sorted(sources.items()):
        path = models_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def _fresh_dir(registry: Registry, fmt: str) -> pathlib.Path:
    out_dir = registry.generated_dir / fmt
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in out_dir.iterdir():
        if path.is_file() and path.name.endswith(_OWNED_SUFFIXES[fmt]):
            path.unlink()
    return out_dir


def _write_jsonschema(
    registry: Registry, spec: ContractSpec, out_dir: pathlib.Path
) -> list[pathlib.Path]:
    source = pydantic_gen.render_module(spec, source_label(registry, spec))
    model = pydantic_gen.load_model(spec, source)
    path = out_dir / f"{spec.contract_id}.schema.json"
    path.write_text(
        jsonschema_gen.render(spec, model, registry.json_schema_id_base), encoding="utf-8"
    )
    return [path]


def _write_avro(
    registry: Registry, spec: ContractSpec, out_dir: pathlib.Path
) -> list[pathlib.Path]:
    path = out_dir / f"{spec.contract_id}.avsc"
    path.write_text(avro.render(spec), encoding="utf-8")
    return [path]


def _write_proto(
    registry: Registry, spec: ContractSpec, out_dir: pathlib.Path
) -> list[pathlib.Path]:
    path = out_dir / f"{pydantic_gen.module_name(spec.contract_id)}.proto"
    path.write_text(proto.render(spec), encoding="utf-8")
    return [path, proto.compile_proto(path)]


def _write_parquet(
    registry: Registry, spec: ContractSpec, out_dir: pathlib.Path
) -> list[pathlib.Path]:
    descriptor = out_dir / f"{spec.contract_id}.parquet.json"
    descriptor.write_text(parquet.render(spec), encoding="utf-8")
    schema_file = out_dir / f"{spec.contract_id}.schema.parquet"
    parquet.write_schema_file(spec, schema_file)
    return [descriptor, schema_file]


_WRITERS: dict[str, Callable[[Registry, ContractSpec, pathlib.Path], list[pathlib.Path]]] = {
    "jsonschema": _write_jsonschema,
    "avro": _write_avro,
    "proto": _write_proto,
    "parquet": _write_parquet,
}


def _readiness(specs: Iterable[ContractSpec], formats: Iterable[str]) -> list[str]:
    return [error for spec in specs for fmt in formats for error in generation_errors(spec, fmt)]


def generate(
    registry: Registry, formats: Iterable[str] = FORMATS, *, check: bool = False
) -> GenerationReport:
    """Generate (or, with `check`, drift-check) the requested formats for every contract."""
    formats = list(formats)
    report = GenerationReport()
    contracts, report.errors = registry.load_contracts()
    specs = [contracts[cid] for cid in sorted(contracts)]
    report.errors += _readiness(specs, ["pydantic", *formats])
    if report.errors:
        return report
    sources = model_sources(registry, specs)
    if check:
        report.drift = model_drift(registry, sources)
        return report
    if "pydantic" in formats:
        report.written += _write_models(registry, sources)
    for fmt in (f for f in FORMATS if f in formats and f in _WRITERS):
        out_dir = _fresh_dir(registry, fmt)
        for spec in specs:
            try:
                report.written += _WRITERS[fmt](registry, spec, out_dir)
            except (proto.ProtoCompileError, ValueError) as exc:
                report.errors.append(f"{spec.contract_id} [{fmt}]: {exc}")
    return report
