from __future__ import annotations

from math import ceil
from typing import Sequence, TypeVar

from fastapi import Query
from pydantic import BaseModel


T = TypeVar("T")


class PaginationDTO(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


def pagination_params(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
) -> tuple[int, int]:
    return page, per_page


def pagination_meta(*, page: int, per_page: int, total: int) -> dict:
    total_pages = ceil(total / per_page) if per_page else 1
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(total_pages, 1),
    }


def paginate_items(items: Sequence[T], *, page: int, per_page: int) -> dict:
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": list(items[start:end]),
        "pagination": pagination_meta(page=page, per_page=per_page, total=total),
    }
