"""Response envelope models, so OpenAPI (and the generated frontend types) describe real shapes."""

from pydantic import BaseModel


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


class DataResponse[T](BaseModel):
    data: T


class PageResponse[T](BaseModel):
    data: list[T]
    meta: PageMeta
