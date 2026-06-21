from sympy import sympify, N
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application


TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)


def calculator(expression: str) -> dict:
    try:
        expr = parse_expr(expression, transformations=TRANSFORMATIONS)
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
