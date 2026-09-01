"""Python/Notebook AST scanner that never imports or executes untrusted code."""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Final, Literal, cast

from aegisquant.data.hashing import canonical_sha256
from aegisquant.intelligence.static_analysis.models import (
    ArtifactKind,
    SourceArtifact,
    StaticAnalysisReport,
    StaticFinding,
    StaticReviewState,
)

NETWORK_ROOTS: Final = frozenset({"aiohttp", "httpx", "requests", "socket", "urllib", "websockets"})
SUBPROCESS_ROOTS: Final = frozenset({"subprocess"})
DESERIALIZATION_CALLS: Final = frozenset(
    {
        "dill.load",
        "dill.loads",
        "joblib.load",
        "marshal.loads",
        "pickle.load",
        "pickle.loads",
        "shelve.open",
        "torch.load",
        "yaml.load",
    }
)
DYNAMIC_EXECUTION_CALLS: Final = frozenset(
    {"compile", "eval", "exec", "__import__", "importlib.import_module"}
)
FILE_CALLS: Final = frozenset(
    {
        "open",
        "pathlib.Path.open",
        "pathlib.Path.read_bytes",
        "pathlib.Path.read_text",
        "pathlib.Path.write_bytes",
        "pathlib.Path.write_text",
        "pathlib.Path.touch",
    }
)
DELETION_CALLS: Final = frozenset(
    {
        "os.remove",
        "os.replace",
        "os.rmdir",
        "os.unlink",
        "pathlib.Path.rmdir",
        "pathlib.Path.unlink",
        "shutil.rmtree",
    }
)
PROCESS_CALLS: Final = frozenset(
    {
        "os.popen",
        "os.spawnl",
        "os.spawnv",
        "os.system",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
        "subprocess.run",
    }
)
CREDENTIAL_CALLS: Final = frozenset(
    {"dotenv.load_dotenv", "keyring.get_password", "os.getenv", "os.environ.get"}
)
CREDENTIAL_NAMES: Final = ("api_key", "apikey", "cookie", "password", "secret", "token")

PLATFORM_APIS: Final = frozenset(
    {
        "attribute_history",
        "get_all_securities",
        "get_current_data",
        "get_fundamentals",
        "get_index_stocks",
        "get_price",
        "history",
        "order",
        "order_target",
        "order_target_value",
        "order_value",
        "run_daily",
        "run_monthly",
        "run_weekly",
        "set_benchmark",
        "set_commission",
        "set_option",
        "set_order_cost",
        "set_slippage",
    }
)
SCHEDULE_CALLS: Final = frozenset({"run_daily", "run_weekly", "run_monthly", "schedule_function"})
DATA_CALLS: Final = frozenset(
    {
        "attribute_history",
        "get_all_securities",
        "get_current_data",
        "get_fundamentals",
        "get_index_stocks",
        "get_price",
        "history",
    }
)
TRADE_CALLS: Final = frozenset(
    {"buy", "cancel_order", "order", "order_target", "order_target_value", "order_value", "sell"}
)
RISK_CALLS: Final = frozenset(
    {"set_commission", "set_order_cost", "set_slippage", "stop_loss", "take_profit"}
)

type Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _base_call_name(value: str) -> str:
    return value.rsplit(".", maxsplit=1)[-1]


def _finding(
    *, category: str, severity: Severity, line: int, symbol: str, message: str
) -> StaticFinding:
    identity = {
        "category": category,
        "severity": severity,
        "line": line,
        "symbol": symbol,
        "message": message,
    }
    return StaticFinding(
        finding_id=canonical_sha256(identity),
        category=category,
        severity=severity,
        line=max(line, 1),
        symbol=symbol,
        message=message,
    )


def _string_constant(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _open_is_write(call: ast.Call) -> bool:
    mode: str | None = None
    if len(call.args) >= 2:
        mode = _string_constant(call.args[1])
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = _string_constant(keyword.value)
    return mode is None or any(flag in mode for flag in "wax+")


def _subscript_is_negative_one(node: ast.Subscript) -> bool:
    slice_node = node.slice
    return (
        isinstance(slice_node, ast.UnaryOp)
        and isinstance(slice_node.op, ast.USub)
        and isinstance(slice_node.operand, ast.Constant)
        and slice_node.operand.value == 1
    )


def _extract_notebook(raw: bytes) -> str:
    loaded = json.loads(raw.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("AQ-KNOWLEDGE-NOTEBOOK-FORMAT-REJECTED")
    payload = cast("dict[str, object]", loaded)
    if payload.get("nbformat") not in {4}:
        raise ValueError("AQ-KNOWLEDGE-NOTEBOOK-FORMAT-REJECTED")
    cells_value = payload.get("cells")
    if not isinstance(cells_value, list):
        raise ValueError("AQ-KNOWLEDGE-NOTEBOOK-CELLS-INVALID")
    cells = cast("list[object]", cells_value)
    code: list[str] = []
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            continue
        typed_cell = cast("dict[str, object]", cell)
        if typed_cell.get("cell_type") != "code":
            continue
        source = typed_cell.get("source", [])
        if isinstance(source, str):
            text = source
        elif isinstance(source, list):
            typed_source = cast("list[object]", source)
            if not all(isinstance(item, str) for item in typed_source):
                raise ValueError("AQ-KNOWLEDGE-NOTEBOOK-CODE-CELL-INVALID")
            text = "".join(cast("str", item) for item in typed_source)
        else:
            raise ValueError("AQ-KNOWLEDGE-NOTEBOOK-CODE-CELL-INVALID")
        code.append(f"# notebook-cell-{index}\n{text}\n")
    return "\n".join(code)


class _Scanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports: set[str] = set()
        self.platform_apis: set[str] = set()
        self.parameters: set[str] = set()
        self.scheduled_callbacks: set[str] = set()
        self.data_calls: set[str] = set()
        self.trade_calls: set[str] = set()
        self.risk_calls: set[str] = set()
        self.findings: list[StaticFinding] = []
        self._scope_depth = 0

    def _add(
        self,
        category: str,
        severity: Severity,
        node: ast.AST,
        symbol: str,
        message: str,
    ) -> None:
        self.findings.append(
            _finding(
                category=category,
                severity=severity,
                line=getattr(node, "lineno", 1),
                symbol=symbol,
                message=message,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", maxsplit=1)[0]
            self.imports.add(alias.name)
            if root in NETWORK_ROOTS:
                self._add(
                    "network_import", "HIGH", node, alias.name, "network-capable module imported"
                )
            if root in SUBPROCESS_ROOTS:
                self._add(
                    "subprocess_import", "HIGH", node, alias.name, "subprocess module imported"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        self.imports.add(module)
        root = module.split(".", maxsplit=1)[0]
        if root in NETWORK_ROOTS:
            self._add("network_import", "HIGH", node, module, "network-capable module imported")
        if root in SUBPROCESS_ROOTS:
            self._add("subprocess_import", "HIGH", node, module, "subprocess module imported")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.parameters.update(
            argument.arg for argument in (*node.args.posonlyargs, *node.args.args)
        )
        self._scope_depth += 1
        self.generic_visit(node)
        self._scope_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.parameters.update(
            argument.arg for argument in (*node.args.posonlyargs, *node.args.args)
        )
        self._scope_depth += 1
        self.generic_visit(node)
        self._scope_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if self._scope_depth == 0:
            self.parameters.update(names)
        for name in names:
            if any(token in name.casefold() for token in CREDENTIAL_NAMES):
                self._add(
                    "embedded_credential",
                    "CRITICAL",
                    node,
                    name,
                    "secret-like global assignment detected; value intentionally not reported",
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        base = _base_call_name(name)
        root = name.split(".", maxsplit=1)[0]
        if base in PLATFORM_APIS:
            self.platform_apis.add(base)
        if base in SCHEDULE_CALLS:
            self.scheduled_callbacks.add(base)
        if base in DATA_CALLS:
            self.data_calls.add(base)
        if base in TRADE_CALLS:
            self.trade_calls.add(base)
        if base in RISK_CALLS:
            self.risk_calls.add(base)

        if name in DYNAMIC_EXECUTION_CALLS or base in DYNAMIC_EXECUTION_CALLS:
            self._add(
                "dynamic_execution",
                "CRITICAL",
                node,
                name or base,
                "dynamic code execution detected",
            )
        if root in NETWORK_ROOTS:
            self._add("network_call", "HIGH", node, name, "network-capable call detected")
        if name in PROCESS_CALLS or root == "subprocess":
            self._add("subprocess", "CRITICAL", node, name, "process execution detected")
        if name in DESERIALIZATION_CALLS:
            self._add(
                "unsafe_deserialization",
                "HIGH",
                node,
                name,
                "unsafe or code-capable deserialization detected",
            )
        if name in DELETION_CALLS:
            self._add(
                "destructive_file_operation",
                "CRITICAL",
                node,
                name,
                "destructive file operation detected",
            )
        if name in FILE_CALLS or base in {
            "open",
            "read_text",
            "read_bytes",
            "write_text",
            "write_bytes",
            "touch",
        }:
            write = base in {"write_text", "write_bytes", "touch"} or (
                base == "open" and _open_is_write(node)
            )
            self._add(
                "file_write" if write else "file_read",
                "HIGH" if write else "MEDIUM",
                node,
                name,
                "filesystem write detected" if write else "filesystem read detected",
            )
        if name in CREDENTIAL_CALLS or base in {"getenv", "get_password"}:
            self._add(
                "credential_access", "HIGH", node, name, "credential or environment access detected"
            )
        if name in {"datetime.now", "datetime.utcnow", "date.today"}:
            self._add(
                "wall_clock_access",
                "MEDIUM",
                node,
                name,
                "non-injected wall clock can break replay semantics",
            )
        if base == "shift" and node.args:
            first = node.args[0]
            if isinstance(first, ast.UnaryOp) and isinstance(first.op, ast.USub):
                self._add(
                    "lookahead", "CRITICAL", node, name, "negative shift can expose future data"
                )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        name = _call_name(node.value)
        if name.endswith(".iloc") and _subscript_is_negative_one(node):
            self._add(
                "time_index_semantics",
                "HIGH",
                node,
                name,
                "last-row positional access requires point-in-time review",
            )
        self.generic_visit(node)


def scan_source_bytes(
    *, source_id: str, artifact: SourceArtifact, raw: bytes
) -> StaticAnalysisReport:
    """Parse one artifact in memory; no source module is imported or evaluated."""
    if hashlib.sha256(raw).hexdigest() != artifact.sha256:
        raise ValueError("AQ-KNOWLEDGE-STATIC-HASH-MISMATCH")
    if artifact.kind not in {ArtifactKind.PYTHON, ArtifactKind.NOTEBOOK}:
        raise ValueError("static scanner accepts only Python or Notebook artifacts")
    language = "python-notebook" if artifact.kind is ArtifactKind.NOTEBOOK else "python"
    try:
        source = (
            _extract_notebook(raw)
            if artifact.kind is ArtifactKind.NOTEBOOK
            else raw.decode("utf-8")
        )
        tree = ast.parse(source, filename=artifact.relative_path, mode="exec")
    except (SyntaxError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        line = getattr(error, "lineno", 1) or 1
        finding = _finding(
            category="syntax_or_format",
            severity="CRITICAL",
            line=line,
            symbol=type(error).__name__,
            message="source cannot be parsed safely",
        )
        return StaticAnalysisReport(
            source_id=source_id,
            artifact_id=artifact.artifact_id,
            artifact_sha256=artifact.sha256,
            language=language,
            syntax_valid=False,
            imports=(),
            platform_apis=(),
            parameters=(),
            scheduled_callbacks=(),
            data_calls=(),
            trade_calls=(),
            risk_calls=(),
            findings=(finding,),
            review_state=StaticReviewState.QUARANTINED,
        )
    scanner = _Scanner()
    scanner.visit(tree)
    findings = tuple(
        sorted(
            {item.finding_id: item for item in scanner.findings}.values(),
            key=lambda item: (item.line, item.category, item.symbol),
        )
    )
    dangerous = any(item.severity in {"HIGH", "CRITICAL"} for item in findings)
    return StaticAnalysisReport(
        source_id=source_id,
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.sha256,
        language=language,
        syntax_valid=True,
        imports=tuple(sorted(scanner.imports)),
        platform_apis=tuple(sorted(scanner.platform_apis)),
        parameters=tuple(sorted(scanner.parameters)),
        scheduled_callbacks=tuple(sorted(scanner.scheduled_callbacks)),
        data_calls=tuple(sorted(scanner.data_calls)),
        trade_calls=tuple(sorted(scanner.trade_calls)),
        risk_calls=tuple(sorted(scanner.risk_calls)),
        findings=findings,
        review_state=(
            StaticReviewState.QUARANTINED if dangerous else StaticReviewState.REVIEW_REQUIRED
        ),
    )


def scan_artifact_path(
    *, source_id: str, artifact: SourceArtifact, path: Path
) -> StaticAnalysisReport:
    """Read one regular file and delegate to the in-memory scanner."""
    if not path.is_file() or path.is_symlink():
        raise ValueError("static scan path must be a regular non-symlink file")
    return scan_source_bytes(source_id=source_id, artifact=artifact, raw=path.read_bytes())


def normalized_ast_sha256(raw: bytes, *, notebook: bool = False) -> str:
    """Hash semantics-oriented AST with locations and formatting removed."""
    source = _extract_notebook(raw) if notebook else raw.decode("utf-8")
    tree = ast.parse(source, mode="exec")
    return hashlib.sha256(
        ast.dump(tree, annotate_fields=True, include_attributes=False).encode()
    ).hexdigest()


def source_lines(raw: bytes, *, notebook: bool = False) -> tuple[str, ...]:
    source = _extract_notebook(raw) if notebook else raw.decode("utf-8")
    return tuple(source.splitlines())


def iter_calls(raw: bytes, *, notebook: bool = False) -> Iterable[ast.Call]:
    source = _extract_notebook(raw) if notebook else raw.decode("utf-8")
    tree = ast.parse(source, mode="exec")
    return tuple(node for node in ast.walk(tree) if isinstance(node, ast.Call))
