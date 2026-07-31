from __future__ import annotations

import hmac
import math
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Annotated, Any

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .analytics import add_months, balance_on, budget_balance_on, month_end, month_start
from .categories import seed_categories
from .config import get_settings
from .csv_import import parse_euro_cents
from .db import SessionLocal, database_is_ready, engine, get_db
from .errors import AppError, NotFoundError, PermissionDeniedError, ValidationError
from .i18n import (
    format_date,
    format_datetime,
    format_money,
    normalize_locale,
    translate,
)
from .mcp_server import mcp, mcp_asgi_app
from .models import Account, AuditEvent, Category, TransactionNote, User
from .security import (
    Actor,
    WebSession,
    create_form_token,
    create_web_session,
    delete_web_session,
    get_web_session,
    secure_compare,
    verify_form_token,
)
from .services import CAPABILITIES, FinanceService, render_markdown

PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
settings = get_settings()


def run_migrations() -> None:
    config = AlembicConfig(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    run_migrations()
    with SessionLocal() as db:
        seed_categories(db)
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Fin",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
app.mount("/mcp", mcp_asgi_app)


class SecurityHeadersMiddleware:
    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                            b"script-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'",
                        ),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)


class McpCanonicalPathMiddleware:
    """Serve the transport at /mcp without an authentication-bypassing slash redirect."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
            scope["raw_path"] = b"/mcp/"
        await self.app(scope, receive, send)


app.add_middleware(McpCanonicalPathMiddleware)


class LoginLimiter:
    def __init__(self) -> None:
        self.attempts: dict[str, deque[float]] = defaultdict(deque)

    def allowed(self, key: str) -> bool:
        now = time.monotonic()
        queue = self.attempts[key]
        while queue and queue[0] < now - settings.login_window_seconds:
            queue.popleft()
        return len(queue) < settings.login_attempts

    def fail(self, key: str) -> None:
        self.attempts[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        self.attempts.pop(key, None)


login_limiter = LoginLimiter()


@dataclass
class WebContext:
    user: User
    session: WebSession
    actor: Actor


def optional_context(request: Request, db: Session) -> WebContext | None:
    session = get_web_session(db, settings, request.cookies.get("fp_session"))
    if not session:
        return None
    return WebContext(session.user, session, Actor.human(session.user))


def require_context(request: Request, db: Session = Depends(get_db)) -> WebContext:
    context = optional_context(request, db)
    if context is None:
        raise HTTPException(status_code=401)
    return context


def require_csrf(context: WebContext, csrf_token: str) -> None:
    if not hmac.compare_digest(context.session.csrf_token, csrf_token):
        raise AppError("invalid_csrf", "error.csrf", status_code=403)


def parse_month(value: str | None) -> date:
    try:
        return date.fromisoformat(f"{value}-01") if value else date.today().replace(day=1)
    except ValueError as exc:
        raise ValidationError("month", "error.validation") from exc


def parse_year(value: str | None) -> int:
    try:
        year = int(value) if value else date.today().year
    except ValueError as exc:
        raise ValidationError("year", "error.validation") from exc
    if year < 1900 or year > 9999:
        raise ValidationError("year", "error.validation")
    return year


def redirect(url: str, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(url, status_code=status_code)


def base_context(
    request: Request,
    db: Session,
    context: WebContext | None,
    *,
    title_key: str,
    account: Account | None = None,
    value_month: date | None = None,
    **values: Any,
) -> dict[str, Any]:
    locale = context.user.locale if context else normalize_locale(request.query_params.get("lang"))
    service = FinanceService(db)
    accounts = service.list_accounts(context.actor) if context else []
    template_context = {
        "request": request,
        "locale": locale,
        "t": lambda key, **kwargs: translate(locale, key, **kwargs),
        "money": lambda cents: format_money(cents, locale),
        "datefmt": lambda value, format="medium": format_date(value, locale, format),
        "datetimefmt": lambda value: format_datetime(value, locale),
        "markdown": render_markdown,
        "page_title": translate(locale, title_key),
        "user": context.user if context else None,
        "csrf_token": context.session.csrf_token if context else None,
        "accounts": accounts,
        "account": account,
        "month": value_month,
        "is_admin": bool(context and context.user.is_admin),
    }
    template_context.update(values)
    return template_context


def render(
    request: Request,
    db: Session,
    context: WebContext | None,
    template: str,
    *,
    title_key: str,
    status_code: int = 200,
    **values: Any,
) -> HTMLResponse:
    account = values.pop("account", None)
    value_month = values.pop("value_month", None)
    return templates.TemplateResponse(
        request,
        template,
        base_context(
            request,
            db,
            context,
            title_key=title_key,
            account=account,
            value_month=value_month,
            **values,
        ),
        status_code=status_code,
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, error: AppError):
    if request.url.path.startswith("/mcp"):
        return JSONResponse(
            {"error": {"code": error.code, "message_key": error.message_key, "details": error.details}},
            status_code=error.status_code,
        )
    with SessionLocal() as db:
        context = optional_context(request, db)
        return render(
            request,
            db,
            context,
            "error.html",
            title_key="error.title",
            status_code=error.status_code,
            error=error,
        )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, error: HTTPException):
    if error.status_code == 401:
        return redirect(f"/login?next={request.url.path}")
    with SessionLocal() as db:
        context = optional_context(request, db)
        app_error = NotFoundError() if error.status_code == 404 else PermissionDeniedError()
        return render(
            request,
            db,
            context,
            "error.html",
            title_key="error.title",
            status_code=error.status_code,
            error=app_error,
        )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, _error: RequestValidationError):
    with SessionLocal() as db:
        context = optional_context(request, db)
        return render(
            request,
            db,
            context,
            "error.html",
            title_key="error.title",
            status_code=422,
            error=ValidationError("request", "error.validation"),
        )


@app.get("/health/live", name="health_live")
def health_live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready", name="health_ready")
def health_ready():
    writable = True
    for directory in (settings.database_path.parent, settings.backup_dir):
        try:
            probe = directory / ".finanzplaner-write-probe"
            probe.touch(exist_ok=True)
            probe.unlink()
        except OSError:
            writable = False
    if not database_is_ready(engine) or not writable:
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ready"}


@app.get("/", include_in_schema=False)
def index(request: Request, db: Session = Depends(get_db)):
    service = FinanceService(db)
    if service.user_count() == 0:
        return redirect("/setup")
    context = optional_context(request, db)
    if context is None:
        return redirect("/login")
    accounts = service.list_accounts(context.actor)
    if not accounts:
        return render(
            request,
            db,
            context,
            "empty_accounts.html",
            title_key="dashboard.title",
        )
    return redirect(f"/accounts/{accounts[0].id}/overview")


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db)):
    if FinanceService(db).user_count() > 0:
        raise NotFoundError()
    locale = normalize_locale(request.query_params.get("lang"))
    return render(
        request,
        db,
        None,
        "setup.html",
        title_key="setup.title",
        form_token=create_form_token(settings, "setup"),
        locale_override=locale,
    )


@app.post("/setup")
def setup_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    setup_token: Annotated[str, Form()],
    form_token: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    if FinanceService(db).user_count() > 0:
        raise NotFoundError()
    if not verify_form_token(settings, form_token, "setup"):
        raise AppError("invalid_csrf", "error.csrf", status_code=403)
    if not secure_compare(setup_token, settings.setup_token):
        raise ValidationError("setup_token", "error.setup_token")
    user = FinanceService(db).setup_admin(username, password)
    signed, _session = create_web_session(db, settings, user)
    db.commit()
    response = redirect("/")
    response.set_cookie(
        "fp_session",
        signed,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if FinanceService(db).user_count() == 0:
        return redirect("/setup")
    if optional_context(request, db):
        return redirect("/")
    return render(
        request,
        db,
        None,
        "login.html",
        title_key="login.title",
        form_token=create_form_token(settings, "login"),
        next_url=request.query_params.get("next", "/"),
        login_error=None,
    )


@app.post("/login")
def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    form_token: Annotated[str, Form()],
    next_url: Annotated[str, Form()] = "/",
    db: Session = Depends(get_db),
):
    if not verify_form_token(settings, form_token, "login"):
        raise AppError("invalid_csrf", "error.csrf", status_code=403)
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{username.strip().casefold()}"
    if not login_limiter.allowed(key):
        return render(
            request,
            db,
            None,
            "login.html",
            title_key="login.title",
            status_code=429,
            form_token=create_form_token(settings, "login"),
            next_url="/",
            login_error="login.rate_limited",
        )
    user = FinanceService(db).authenticate(username, password)
    if user is None:
        login_limiter.fail(key)
        return render(
            request,
            db,
            None,
            "login.html",
            title_key="login.title",
            status_code=401,
            form_token=create_form_token(settings, "login"),
            next_url="/",
            login_error="login.invalid",
        )
    login_limiter.clear(key)
    signed, _record = create_web_session(db, settings, user)
    db.commit()
    safe_next = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/"
    response = redirect(safe_next)
    response.set_cookie(
        "fp_session",
        signed,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return response


@app.post("/logout")
def logout(
    request: Request,
    csrf_token: Annotated[str, Form()],
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    delete_web_session(db, settings, request.cookies.get("fp_session"))
    response = redirect("/login")
    response.delete_cookie("fp_session", path="/")
    return response


def build_chart(
    db: Session,
    account_id: str,
    forecast: dict[str, Any],
    value_month: date,
    today: date | None = None,
) -> dict[str, Any]:
    now = today or date.today()
    chart_year = value_month.year
    year_months = [date(chart_year, month, 1) for month in range(1, 13)]

    actual = []
    for month in year_months:
        if chart_year > now.year or (
            chart_year == now.year and month.month > now.month
        ):
            continue
        target = (
            now
            if chart_year == now.year and month.month == now.month
            else month_end(month)
        )
        balance, _effective, reliable = balance_on(db, account_id, target)
        if balance is not None and reliable:
            actual.append(
                {
                    "month": month,
                    "date": target,
                    "value": balance,
                    "reliable": reliable,
                }
            )

    actual_by_month = {point["month"]: point for point in actual}
    budget = []
    for month in year_months:
        actual_point = actual_by_month.get(month)
        if actual_point is None:
            continue
        balance, reliable = budget_balance_on(
            db, account_id, date(chart_year, 1, 1), actual_point["date"]
        )
        if balance is not None and reliable:
            budget.append(
                {
                    "month": month,
                    "date": actual_point["date"],
                    "value": balance,
                    "reliable": reliable,
                }
            )
    if all(
        point["value"] == actual_by_month[point["month"]]["value"]
        for point in budget
    ):
        budget = []

    raw_forecast = [
        {
            "month": point["month"],
            "date": month_end(point["month"]),
            "value": point["balance_cents"],
            "low": point["low_cents"],
            "high": point["high_cents"],
        }
        for point in forecast.get("points", [])
        if point["month"].year == chart_year
    ]
    projected = []
    forecast_line = []
    if chart_year == now.year and raw_forecast:
        anchor = actual[-1] if actual else raw_forecast[0]
        projected = [
            point for point in raw_forecast if point["month"] > anchor["month"]
        ]
        if projected:
            forecast_line = [
                {
                    "month": anchor["month"],
                    "date": anchor["date"],
                    "value": anchor["value"],
                    "low": anchor["value"],
                    "high": anchor["value"],
                },
                *projected,
            ]

    values = [point["value"] for point in actual + budget + forecast_line]
    for point in forecast_line:
        values.extend([point["low"], point["high"]])
    empty = {
        "actual": actual,
        "budget": budget,
        "projected": projected,
        "actual_points": "",
        "budget_points": "",
        "forecast_points": "",
        "band": "",
        "actual_dots": [],
        "budget_dots": [],
        "forecast_dots": [],
        "axis_points": [
            {"month": month, "x": 40 + index * (640 / 11)}
            for index, month in enumerate(year_months)
        ],
    }
    if not values:
        return empty

    value_min, value_max = min(values), max(values)

    def rounded_outer_bound(value: int) -> int:
        magnitude = 10 ** math.floor(math.log10(max(100, abs(value))))
        step = max(100, magnitude // 4)
        return math.ceil(abs(value) / step) * step

    low = 0 if value_min >= 0 else -rounded_outer_bound(value_min)
    high = rounded_outer_bound(value_max) if value_max > 0 else 0
    if low == high:
        high = 10_000

    def x(month: date) -> float:
        return 40 + (month.month - 1) * (640 / 11)

    def y(value: int) -> float:
        return 195 - (value - low) / (high - low) * 155

    def dot(point: dict[str, Any]) -> dict[str, Any]:
        return {**point, "x": x(point["month"]), "y": y(point["value"])}

    actual_dots = [dot(point) for point in actual]
    budget_dots = [dot(point) for point in budget]
    forecast_dots = [dot(point) for point in projected]
    actual_coords = [
        f"{point['x']:.1f},{point['y']:.1f}" for point in actual_dots
    ]
    budget_coords = [
        f"{point['x']:.1f},{point['y']:.1f}" for point in budget_dots
    ]
    forecast_coords = [
        f"{x(point['month']):.1f},{y(point['value']):.1f}"
        for point in forecast_line
    ]
    upper = [
        f"{x(point['month']):.1f},{y(point['high']):.1f}"
        for point in forecast_line
    ]
    lower_coords = [
        f"{x(point['month']):.1f},{y(point['low']):.1f}"
        for point in reversed(forecast_line)
    ]
    return {
        **empty,
        "actual_points": " ".join(actual_coords),
        "budget_points": " ".join(budget_coords),
        "forecast_points": " ".join(forecast_coords),
        "band": " ".join(upper + lower_coords),
        "actual_dots": actual_dots,
        "budget_dots": budget_dots,
        "forecast_dots": forecast_dots,
        "min_cents": low,
        "max_cents": high,
    }


@app.get("/accounts/{account_id}/overview", response_class=HTMLResponse)
def overview(
    request: Request,
    account_id: str,
    month: str | None = None,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    value_month = parse_month(month)
    service = FinanceService(db)
    account = service.get_account(context.actor, account_id)
    summary = service.summary(context.actor, account_id, value_month)
    forecast = service.forecast(context.actor, account_id)
    chart = build_chart(db, account_id, forecast, value_month)
    return render(
        request,
        db,
        context,
        "overview.html",
        title_key="dashboard.title",
        account=account,
        value_month=value_month,
        summary=summary,
        forecast=forecast,
        chart=chart,
        previous_month=add_months(value_month, -1),
        next_month=add_months(value_month, 1),
    )


@app.get("/accounts/{account_id}/transactions", response_class=HTMLResponse)
def transactions_page(
    request: Request,
    account_id: str,
    month: str | None = None,
    category_id: str | None = None,
    uncategorized: bool = False,
    direction: str | None = None,
    tag: str | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    service = FinanceService(db)
    account = service.get_account(context.actor, account_id)
    value_month = parse_month(month)

    def amount_or_none(value: str | None) -> int | None:
        if not value:
            return None
        try:
            return abs(parse_euro_cents(value))
        except ValueError as exc:
            raise ValidationError("amount", "error.validation") from exc

    page = service.list_transactions(
        context.actor,
        account_id,
        value_month=value_month,
        category_id=category_id,
        uncategorized=uncategorized,
        direction=direction,
        tag=tag,
        min_amount_cents=amount_or_none(min_amount),
        max_amount_cents=amount_or_none(max_amount),
        text=q,
        cursor=cursor,
        page_size=75,
    )
    categories = service.list_categories(context.actor)
    return render(
        request,
        db,
        context,
        "transactions.html",
        title_key="transactions.title",
        account=account,
        value_month=value_month,
        page=page,
        categories=categories,
        tags=service.list_tags(context.actor, account_id),
        filters={
            "category_id": category_id,
            "uncategorized": uncategorized,
            "direction": direction,
            "tag": tag,
            "min_amount": min_amount or "",
            "max_amount": max_amount or "",
            "q": q or "",
        },
    )


@app.get("/transactions/{transaction_id}", response_class=HTMLResponse)
def transaction_detail(
    request: Request,
    transaction_id: str,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    service = FinanceService(db)
    transaction = service.get_transaction(context.actor, transaction_id)
    account = service.get_account(context.actor, transaction.account_id)
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.object_id.in_([transaction.id, *(note.id for note in transaction.notes)]))
        .order_by(AuditEvent.created_at.desc())
        .limit(50)
    ).all()
    return render(
        request,
        db,
        context,
        "transaction_detail.html",
        title_key="transaction.title",
        account=account,
        value_month=month_start(transaction.booking_date),
        transaction=transaction,
        categories=service.list_categories(context.actor),
        transfer=service.get_transfer_presentation(context.actor, transaction.id),
        events=events,
    )


@app.post("/transactions/{transaction_id}/category")
def update_transaction_category(
    transaction_id: str,
    category_id: Annotated[str, Form()] = "",
    revision: Annotated[int, Form()] = 1,
    return_to: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    result = FinanceService(db).categorize(
        context.actor, transaction_id, category_id or None, revision
    )
    if result["status"] == "conflict":
        raise AppError(result["code"], "error.revision", status_code=409)
    db.commit()
    destination = (
        return_to
        if return_to.startswith("/") and not return_to.startswith("//")
        else f"/transactions/{transaction_id}"
    )
    return redirect(destination)


@app.post("/transactions/{transaction_id}/notes")
def add_transaction_note(
    transaction_id: str,
    content: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).add_note(context.actor, transaction_id, content)
    return redirect(f"/transactions/{transaction_id}")


@app.post("/notes/{note_id}")
def edit_transaction_note(
    note_id: str,
    content: Annotated[str, Form()] = "",
    delete: Annotated[bool, Form()] = False,
    csrf_token: Annotated[str, Form()] = "",
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    note = db.get(TransactionNote, note_id)
    if not note:
        raise NotFoundError()
    transaction_id = note.transaction_id
    FinanceService(db).update_human_note(context.actor, note_id, None if delete else content)
    return redirect(f"/transactions/{transaction_id}")


@app.post("/transactions/{transaction_id}/tags")
def add_transaction_tags(
    transaction_id: str,
    tags: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).add_tags(context.actor, transaction_id, tags.split(","))
    return redirect(f"/transactions/{transaction_id}")


@app.get("/accounts/{account_id}/import", response_class=HTMLResponse)
def import_page(
    request: Request,
    account_id: str,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    service = FinanceService(db)
    account = service.get_account(context.actor, account_id)
    return render(
        request,
        db,
        context,
        "import.html",
        title_key="import.title",
        account=account,
        value_month=date.today().replace(day=1),
        imports=service.list_imports(context.actor, account_id),
        result=request.query_params,
        form_action=f"/accounts/{account.id}/import",
    )


@app.post("/accounts/{account_id}/import")
async def import_submit(
    account_id: str,
    file: Annotated[UploadFile, File()],
    expected_account_id: Annotated[str, Form()] = "",
    new_account_name: Annotated[str, Form()] = "",
    new_account_visibility: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    if file.filename and not file.filename.casefold().endswith(".csv"):
        raise ValidationError("filename", "error.import_layout")
    data = await file.read(settings.max_upload_bytes + 1)
    batch = FinanceService(db).import_dkb(
        context.actor,
        data,
        max_bytes=settings.max_upload_bytes,
        expected_account_id=expected_account_id or None,
        new_account_name=new_account_name or None,
        new_account_visibility=new_account_visibility or None,
    )
    return redirect(
        f"/accounts/{batch.account_id}/import?rows={batch.row_count}"
        f"&inserted={batch.inserted_count}&duplicates={batch.duplicate_count}"
    )


@app.get("/import", response_class=HTMLResponse)
def first_import_page(
    request: Request,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    return render(
        request,
        db,
        context,
        "import.html",
        title_key="import.title",
        account=None,
        value_month=date.today().replace(day=1),
        imports=[],
        result=request.query_params,
        form_action="/import",
    )


@app.post("/import")
async def first_import_submit(
    file: Annotated[UploadFile, File()],
    expected_account_id: Annotated[str, Form()] = "",
    new_account_name: Annotated[str, Form()] = "",
    new_account_visibility: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    if file.filename and not file.filename.casefold().endswith(".csv"):
        raise ValidationError("filename", "error.import_layout")
    data = await file.read(settings.max_upload_bytes + 1)
    batch = FinanceService(db).import_dkb(
        context.actor,
        data,
        max_bytes=settings.max_upload_bytes,
        expected_account_id=expected_account_id or None,
        new_account_name=new_account_name or None,
        new_account_visibility=new_account_visibility or None,
    )
    return redirect(
        f"/accounts/{batch.account_id}/import?rows={batch.row_count}"
        f"&inserted={batch.inserted_count}&duplicates={batch.duplicate_count}"
    )


@app.get("/categories", response_class=HTMLResponse)
def categories_page(
    request: Request,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    FinanceService(db).require_admin(context.actor)
    categories = db.scalars(
        select(Category)
        .where(Category.active.is_(True))
        .order_by(Category.parent_id.is_not(None), Category.sort_order)
    ).all()
    roots = [category for category in categories if category.parent_id is None]
    children = defaultdict(list)
    for category in categories:
        if category.parent_id:
            children[category.parent_id].append(category)
    return render(
        request,
        db,
        context,
        "categories.html",
        title_key="category.title",
        roots=roots,
        children=children,
    )


@app.post("/categories")
def create_category(
    parent_id: Annotated[str, Form()] = "",
    key: Annotated[str, Form()] = "",
    label_de: Annotated[str, Form()] = "",
    label_en: Annotated[str, Form()] = "",
    sort_order: Annotated[int, Form()] = 0,
    csrf_token: Annotated[str, Form()] = "",
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).create_category(
        context.actor,
        parent_id=parent_id or None,
        key=key,
        label_de=label_de,
        label_en=label_en or None,
        sort_order=sort_order,
    )
    return redirect("/categories")


@app.post("/categories/{category_id}")
def edit_category(
    category_id: str,
    label_de: Annotated[str, Form()],
    label_en: Annotated[str, Form()] = "",
    sort_order: Annotated[int, Form()] = 0,
    active: Annotated[bool, Form()] = False,
    csrf_token: Annotated[str, Form()] = "",
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).update_category(
        context.actor,
        category_id,
        label_de=label_de,
        label_en=label_en or None,
        sort_order=sort_order,
        active=active,
    )
    return redirect("/categories")


@app.get("/accounts/{account_id}/forecast", response_class=HTMLResponse)
def forecast_page(
    request: Request,
    account_id: str,
    month: str | None = None,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    service = FinanceService(db)
    account = service.get_account(context.actor, account_id)
    value_month = parse_month(month)
    forecast = service.forecast(context.actor, account_id)
    chart = build_chart(db, account_id, forecast, value_month)
    series = {item.id: item for item in service.list_recurring(context.actor, account_id)}
    return render(
        request,
        db,
        context,
        "forecast.html",
        title_key="forecast.title",
        account=account,
        value_month=value_month,
        forecast=forecast,
        chart=chart,
        series=series,
    )


@app.get("/accounts/{account_id}/report", response_class=HTMLResponse)
def year_report_page(
    request: Request,
    account_id: str,
    year: str | None = None,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    value_year = parse_year(year)
    service = FinanceService(db)
    account = service.get_account(context.actor, account_id)
    return render(
        request,
        db,
        context,
        "year_report.html",
        title_key="report.title",
        account=account,
        value_month=date(value_year, 1, 1),
        year=value_year,
        summary=service.year_summary(context.actor, account_id, value_year),
    )


@app.get("/accounts/{account_id}/trends", response_class=HTMLResponse)
def trends_page(
    request: Request,
    account_id: str,
    category_id: str | None = None,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    service = FinanceService(db)
    account = service.get_account(context.actor, account_id)
    categories = service.list_categories(context.actor)
    assignable_categories = [category for category in categories if category.assignable]
    selected_id = category_id or (
        assignable_categories[0].id if assignable_categories else None
    )
    trend = service.trend(context.actor, account_id, selected_id) if selected_id else None
    moving_by_month = {
        item["month"]: item["amount_cents"]
        for item in (trend["moving_average"] if trend else [])
    }
    return render(
        request,
        db,
        context,
        "trends.html",
        title_key="trend.title",
        account=account,
        value_month=date.today().replace(day=1),
        categories=categories,
        selected_id=selected_id,
        trend=trend,
        moving_by_month=moving_by_month,
    )


@app.get("/accounts/{account_id}/recurring", response_class=HTMLResponse)
def recurring_page(
    request: Request,
    account_id: str,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    service = FinanceService(db)
    account = service.get_account(context.actor, account_id)
    return render(
        request,
        db,
        context,
        "recurring.html",
        title_key="recurring.title",
        account=account,
        value_month=date.today().replace(day=1),
        recurring=service.list_recurring(context.actor, account_id),
    )


@app.post("/accounts/{account_id}/recurring/detect")
def recurring_detect(
    account_id: str,
    csrf_token: Annotated[str, Form()],
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).detect_recurring(context.actor, account_id)
    return redirect(f"/accounts/{account_id}/recurring")


@app.post("/recurring/{series_id}")
def recurring_update(
    series_id: str,
    status: Annotated[str, Form()],
    cadence: Annotated[str, Form()],
    typical_amount: Annotated[str, Form()],
    expected_next_date: Annotated[date, Form()],
    enabled: Annotated[bool, Form()] = False,
    csrf_token: Annotated[str, Form()] = "",
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    series = FinanceService(db).update_recurring(
        context.actor,
        series_id,
        status=status,
        cadence=cadence,
        typical_amount_cents=parse_euro_cents(typical_amount),
        expected_next_date=expected_next_date,
        enabled=enabled,
    )
    return redirect(f"/accounts/{series.account_id}/recurring")


@app.get("/accounts/{account_id}/review", response_class=HTMLResponse)
def review_page(
    request: Request,
    account_id: str,
    month: str | None = None,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    service = FinanceService(db)
    account = service.get_account(context.actor, account_id)
    value_month = parse_month(month)
    history = service.review_history(context.actor, account_id, value_month)
    return render(
        request,
        db,
        context,
        "review.html",
        title_key="review.title",
        account=account,
        value_month=value_month,
        review=history[0] if history else None,
        history=history,
    )


@app.post("/accounts/{account_id}/review")
def review_submit(
    account_id: str,
    month: Annotated[str, Form()],
    content: Annotated[str, Form()],
    expected_revision: Annotated[int, Form()],
    csrf_token: Annotated[str, Form()],
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).save_review(
        context.actor, account_id, parse_month(month), content, expected_revision
    )
    return redirect(f"/accounts/{account_id}/review?month={month}")


@app.get("/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    return render(
        request,
        db,
        context,
        "users.html",
        title_key="users.title",
        users=FinanceService(db).list_users(context.actor),
    )


@app.post("/users")
def create_user(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    locale: Annotated[str, Form()] = "de",
    is_admin: Annotated[bool, Form()] = False,
    csrf_token: Annotated[str, Form()] = "",
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).create_user(context.actor, username, password, is_admin, locale)
    return redirect("/users")


@app.post("/users/{user_id}/status")
def user_status(
    user_id: str,
    active: Annotated[bool, Form()],
    csrf_token: Annotated[str, Form()],
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).set_user_active(context.actor, user_id, active)
    return redirect("/users")


@app.post("/users/{user_id}/password")
def user_password(
    user_id: str,
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).reset_password(context.actor, user_id, password)
    return redirect("/users")


@app.get("/tokens", response_class=HTMLResponse)
def tokens_page(
    request: Request,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    service = FinanceService(db)
    return render(
        request,
        db,
        context,
        "tokens.html",
        title_key="tokens.title",
        tokens=service.list_agent_tokens(context.actor),
        visible_accounts=service.list_accounts(context.actor),
        capabilities=sorted(CAPABILITIES),
        plaintext_token=None,
    )


@app.post("/tokens")
def tokens_create(
    request: Request,
    name: Annotated[str, Form()],
    account_ids: Annotated[list[str], Form()],
    capabilities: Annotated[list[str], Form()],
    expires: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    expires_at = None
    if expires:
        expires_at = datetime.combine(date.fromisoformat(expires), datetime_time.max, tzinfo=UTC)
    service = FinanceService(db)
    _token, raw = service.create_agent_token(
        context.actor,
        name=name,
        account_ids=account_ids,
        capabilities=capabilities,
        expires_at=expires_at,
    )
    return render(
        request,
        db,
        context,
        "tokens.html",
        title_key="tokens.title",
        tokens=service.list_agent_tokens(context.actor),
        visible_accounts=service.list_accounts(context.actor),
        capabilities=sorted(CAPABILITIES),
        plaintext_token=raw,
    )


@app.post("/tokens/{token_id}/revoke")
def token_revoke(
    token_id: str,
    csrf_token: Annotated[str, Form()],
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).revoke_agent_token(context.actor, token_id)
    return redirect("/tokens")


@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    return render(request, db, context, "settings.html", title_key="settings.title")


@app.post("/settings")
def settings_update(
    locale: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    context: WebContext = Depends(require_context),
    db: Session = Depends(get_db),
):
    require_csrf(context, csrf_token)
    FinanceService(db).set_locale(context.actor, locale)
    return redirect("/settings")
