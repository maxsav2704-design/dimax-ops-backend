from sqlalchemy import Numeric, case, cast, func, null


def factory_rate(rates, kind, target):
    prices = {key[1]: rate for key, rate in rates.items() if key[0] == kind}
    if not prices:
        return cast(null(), Numeric(12, 2))
    return case(prices, value=target, else_=None)


def complete_sum(value):
    # SQL SUM ignores nulls; an unpriced row must invalidate the financial total.
    return case((func.count() > func.count(value), None), else_=func.coalesce(func.sum(value), 0))
