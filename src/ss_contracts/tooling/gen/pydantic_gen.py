"""Generate the committed Pydantic models under `ss_contracts.models`.

One module per contract (`sensor-reading` -> `sensor_reading.py`) holds one `ContractModel`
subclass; the package `__init__` re-exports every class and maps contract ids to classes in
`CONTRACTS`. Output is deterministic and already `ruff format`-clean, so the drift gate is a plain
text comparison.

Types: string `str`, bytes `ContractBytes` (standard base64 in JSON), int and long `int` (bounded to int32 and
int64), float and double `float`, boolean `bool`, timestamp `ContractTimestamp` (an aware datetime), date
`datetime.date`, json `dict[str, Any]`, array `list[T]`. An optional field is `T | None` with a
default of `None`.
"""

import json
import sys
import textwrap
import types
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from ss_contracts.tooling.odcs import ContractSpec, FieldSpec
from ss_contracts.tooling.types import INTEGER_BOUNDS

if TYPE_CHECKING:
    from ss_contracts.base import ContractModel

_PY_TYPES: dict[str, str] = {
    "string": "str",
    "bytes": "ContractBytes",
    "int": "int",
    "long": "int",
    "float": "float",
    "double": "float",
    "boolean": "bool",
    "timestamp": "ContractTimestamp",
    "date": "datetime.date",
    "json": "dict[str, Any]",
}

# ODCS logicalTypeOptions -> Pydantic Field keyword.
_OPTION_KWARGS: dict[str, str] = {
    "minLength": "min_length",
    "maxLength": "max_length",
    "pattern": "pattern",
    "minimum": "ge",
    "maximum": "le",
    "exclusiveMinimum": "gt",
    "exclusiveMaximum": "lt",
    "multipleOf": "multiple_of",
    "minItems": "min_length",
    "maxItems": "max_length",
}

# Output order of constraint keywords, so the generated source is stable.
_CONSTRAINT_ORDER: tuple[str, ...] = (
    "ge", "gt", "le", "lt", "multiple_of", "min_length", "max_length", "pattern",
)  # fmt: skip

_INDENT = "    "


def module_name(contract_id: str) -> str:
    return contract_id.replace("-", "_")


def class_name(spec: ContractSpec) -> str:
    return str(spec.generation_hints("pydantic")["className"])


def _literal(value: Any) -> str:
    """A Python literal for a JSON scalar, in ruff's preferred spelling."""
    if isinstance(value, bool) or value is None:
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    return repr(value)


def _dict_literal(value: Mapping[str, Any], indent: str) -> str:
    inner = indent + _INDENT
    lines = [
        f"{inner}{json.dumps(key)}: {_render_value(item, inner)}," for key, item in value.items()
    ]
    return "{\n" + "\n".join(lines) + f"\n{indent}}}"


def _render_value(value: Any, indent: str) -> str:
    if isinstance(value, Mapping):
        return _dict_literal(value, indent)
    return _literal(value)


def _annotation(fld: FieldSpec) -> str:
    item = _PY_TYPES[str(fld.item_kind)] if fld.kind == "array" else ""
    base = f"list[{item}]" if fld.kind == "array" else _PY_TYPES[fld.kind]
    return base if fld.required else f"{base} | None"


def _bounds(fld: FieldSpec) -> dict[str, Any]:
    if fld.kind not in INTEGER_BOUNDS:
        return {}
    low, high = INTEGER_BOUNDS[fld.kind]
    bounds: dict[str, Any] = {}
    if "minimum" not in fld.options and "exclusiveMinimum" not in fld.options:
        bounds["ge"] = low
    if "maximum" not in fld.options and "exclusiveMaximum" not in fld.options:
        bounds["le"] = high
    return bounds


def _schema_extra(fld: FieldSpec) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if "format" in fld.options and fld.logical_type == "string":
        extra["format"] = fld.options["format"]
    if fld.binding:
        extra["x-ss-binding"] = dict(fld.binding)
    return extra


def field_kwargs(fld: FieldSpec) -> dict[str, Any]:
    """Keyword arguments of the field's `Field(...)` call, in output order."""
    kwargs: dict[str, Any] = {}
    if not fld.required:
        kwargs["default"] = None
    kwargs["description"] = fld.description
    constraints = _bounds(fld)
    for option, value in fld.options.items():
        if option in _OPTION_KWARGS:
            constraints[_OPTION_KWARGS[option]] = value
    kwargs.update((key, constraints[key]) for key in _CONSTRAINT_ORDER if key in constraints)
    extra = _schema_extra(fld)
    if extra:
        kwargs["json_schema_extra"] = extra
    return kwargs


def _render_field(fld: FieldSpec) -> list[str]:
    inner = _INDENT * 2
    lines = [f"{_INDENT}{fld.name}: {_annotation(fld)} = Field("]
    for key, value in field_kwargs(fld).items():
        lines.append(f"{inner}{key}={_render_value(value, inner)},")
    lines.append(f"{_INDENT})")
    return lines


def _docstring(text: str) -> list[str]:
    safe = text.replace("\\", "/").replace('"', "'")
    wrapped = textwrap.wrap(safe, width=92)
    if len(wrapped) == 1:
        return [f'{_INDENT}"""{wrapped[0]}"""']
    return [
        f'{_INDENT}"""{wrapped[0]}',
        *(f"{_INDENT}{line}" for line in wrapped[1:]),
        f'{_INDENT}"""',
    ]


def _imports(spec: ContractSpec) -> list[str]:
    kinds = {fld.kind for fld in spec.fields} | {fld.item_kind for fld in spec.fields}
    lines: list[str] = []
    if "date" in kinds:
        lines.append("import datetime")
    lines.append(
        "from typing import Any, ClassVar" if "json" in kinds else "from typing import ClassVar"
    )
    lines.append("")
    lines.append("from pydantic import Field")
    lines.append("")
    base_names = ["ContractModel"]
    base_names += ["ContractBytes"] if "bytes" in kinds else []
    base_names += ["ContractTimestamp"] if "timestamp" in kinds else []
    lines.append(f"from ss_contracts.base import {', '.join(sorted(base_names))}")
    return lines


def render_module(spec: ContractSpec, source_label: str) -> str:
    """Python source of one contract's model module."""
    header = (
        f"Contract {spec.contract_id} {spec.version}, generated from {source_label}; do not edit."
    )
    lines = [f'"""{header}"""', "", *_imports(spec), "", ""]
    lines.append(f"class {class_name(spec)}(ContractModel):")
    lines.extend(_docstring(spec.purpose))
    lines.append("")
    lines.append(f"{_INDENT}CONTRACT_ID: ClassVar[str] = {_literal(spec.contract_id)}")
    lines.append(f"{_INDENT}CONTRACT_VERSION: ClassVar[str] = {_literal(spec.version)}")
    if spec.binding:
        rendered = _dict_literal(spec.binding, _INDENT)
        lines.append(f"{_INDENT}SS_BINDING: ClassVar[dict[str, str]] = {rendered}")
    lines.append("")
    for fld in spec.fields:
        lines.extend(_render_field(fld))
    return "\n".join(lines) + "\n"


def render_package_init(specs: Iterable[ContractSpec]) -> str:
    """Python source of the models package `__init__`."""
    ordered = sorted(specs, key=lambda spec: module_name(spec.contract_id))
    lines = [
        '"""Generated contract models; do not edit. Regenerate with `make contracts-gen`."""',
        "",
    ]
    lines.append("from ss_contracts.base import ContractModel")
    if ordered:
        lines.append("")
    for spec in ordered:
        lines.append(f"from .{module_name(spec.contract_id)} import {class_name(spec)}")
    if ordered:
        lines.extend(["", "CONTRACTS: dict[str, type[ContractModel]] = {"])
        for spec in sorted(ordered, key=lambda s: s.contract_id):
            lines.append(f"{_INDENT}{_literal(spec.contract_id)}: {class_name(spec)},")
        lines.append("}")
    else:
        lines.extend(["", "CONTRACTS: dict[str, type[ContractModel]] = {}"])
    names = sorted(["CONTRACTS", "ContractModel", *(class_name(spec) for spec in ordered)])
    lines.extend(["", "__all__ = ["])
    lines.extend(f"{_INDENT}{_literal(name)}," for name in names)
    lines.append("]")
    return "\n".join(lines) + "\n"


def load_model(spec: ContractSpec, source: str) -> "type[ContractModel]":
    """Execute generated module source in a throwaway module and return its model class."""
    name = f"_ss_contracts_generated_{module_name(spec.contract_id)}"
    module = types.ModuleType(name)
    sys.modules[name] = module
    try:
        exec(compile(source, f"<generated {spec.contract_id}>", "exec"), module.__dict__)
    finally:
        del sys.modules[name]
    model: type[ContractModel] = getattr(module, class_name(spec))
    return model
