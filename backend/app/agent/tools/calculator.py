import ast
import asyncio
import operator

from .base import ToolContext, ToolSpec

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Resource-exhaustion guards: the AST whitelist alone doesn't bound how much
# CPU/memory a *valid* expression can demand (e.g. a huge ** exponent), and
# that work is synchronous — asyncio.wait_for's timeout can't preempt it once
# it's running. Bound the inputs instead of relying on the timeout to save us.
_MAX_EXPRESSION_LENGTH = 200
_MAX_POW_EXPONENT = 1000


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numeric literals are allowed")
        return node.value
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BINOPS:
            raise ValueError(f"operator '{op_type.__name__}' is not allowed")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if op_type is ast.Pow and abs(right) > _MAX_POW_EXPONENT:
            raise ValueError(f"exponent magnitude too large (max {_MAX_POW_EXPONENT})")
        return _BINOPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARYOPS:
            raise ValueError(f"operator '{op_type.__name__}' is not allowed")
        return _UNARYOPS[op_type](_eval_node(node.operand))
    raise ValueError(f"expression element '{type(node).__name__}' is not allowed")


def safe_eval_arithmetic(expression: str) -> float:
    """Evaluates a plain arithmetic expression from its parsed AST — never via
    the eval or exec builtins. Only numeric literals, binary + - * / // % **,
    unary +/-, and parentheses are permitted; anything else (names, calls,
    attributes, comprehensions, subscripts, ...) raises ValueError. Expression
    length and ** exponent magnitude are bounded to prevent a valid-but-huge
    expression from exhausting CPU/memory synchronously."""
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise ValueError(f"expression too long (max {_MAX_EXPRESSION_LENGTH} characters)")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as e:
        raise ValueError(f"could not parse expression: {e}")
    return _eval_node(tree.body)


CALCULATOR_PARAMETERS = {
    "type": "object",
    "properties": {
        "expression": {
            "type": "string",
            "description": "Arithmetic expression to evaluate, e.g. '2 + 2 * (3 - 1)'",
        }
    },
    "required": ["expression"],
}


async def _calculator_handler(args: dict, ctx: ToolContext) -> str:
    expression = args.get("expression", "")
    try:
        # Offloaded to a thread (not just called inline) so run_tool's
        # asyncio.wait_for timeout can actually preempt the caller even if a
        # future change to the bounds above lets something slow through.
        result = await asyncio.to_thread(safe_eval_arithmetic, expression)
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
        return f"TOOL_ERROR: invalid expression — {e}"
    return str(result)


CALCULATOR_TOOL = ToolSpec(
    name="calculator",
    description="Evaluates a basic arithmetic expression (+, -, *, /, //, %, **, parentheses). No variables or functions.",
    parameters=CALCULATOR_PARAMETERS,
    handler=_calculator_handler,
)
