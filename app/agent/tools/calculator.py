from sympy import N, Pow, factorial
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application


TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)

MAX_LEN = 200          # reject absurdly long expressions
MAX_EXPONENT = 1000    # block 9**9**9-style blowups that hang sympy
MAX_FACTORIAL = 10000


def calculator(expression: str) -> dict:
    if len(expression) > MAX_LEN:
        return {"expression": expression[:60] + "…", "error": "expression too long"}
    try:
        # evaluate=False builds the expression tree WITHOUT computing it, so we can
        # reject resource-exhaustion inputs (e.g. 9**9**9) before they're evaluated.
        expr = parse_expr(expression, transformations=TRANSFORMATIONS, evaluate=False)

        # Guard against resource-exhaustion inputs before evaluating
        for p in expr.atoms(Pow):
            if p.exp.is_number and abs(float(p.exp)) > MAX_EXPONENT:
                return {"expression": expression, "error": "exponent too large"}
        for f in expr.atoms(factorial):
            arg = f.args[0]
            if arg.is_number and float(arg) > MAX_FACTORIAL:
                return {"expression": expression, "error": "factorial argument too large"}

        result = N(expr, 15)
        return {"expression": expression, "result": str(result)}
    except Exception as e:
        return {"expression": expression, "error": str(e)}


TOOL_SPEC = {
    "name": "calculator",
    "description": "Evaluate mathematical expressions precisely using symbolic math. Supports arithmetic, algebra, trigonometry, logarithms, and unit conversions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Mathematical expression to evaluate. Examples: '2**10', 'sqrt(144)', 'log(1000, 10)', '(3.14159 * 6371**2) * 4'",
            }
        },
        "required": ["expression"],
    },
}
