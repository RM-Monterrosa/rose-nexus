"""Authenticated, failure-isolated experimental LLM browser screen."""

from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

from ..ai.client import Answer, InferenceClient
from ..ai.errors import InferencePromptTooLong
from ..core.errors import RoseNexusError
from .html import _e, page
from .http_security import ApiProblem, require_csrf, require_session
from .models import Session, User

_MAX_PROMPT_CHARACTERS = 8000
_DEFAULT_SYSTEM = "Responde con brevedad y sin inventar datos."


def _text(value: object) -> str:
    """Accept only scalar values from the URL-encoded browser form."""

    return value if isinstance(value, str) else ""


def _metric(value: float | int | None) -> str:
    """Format measured values without replacing absent telemetry with zeroes."""

    if value is None:
        return "—"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "—"
        return f"{value:.2f}"
    return str(value)


def _metrics(answer: Answer) -> str:
    """Render only the content-free metrics exposed by the inference client."""

    metrics = answer.metrics
    rows = (
        ("Tokens de entrada", _metric(metrics.prompt_tokens)),
        ("Tokens de salida", _metric(metrics.completion_tokens)),
        ("Tokens totales", _metric(metrics.total_tokens)),
        ("Latencia", f"{_metric(metrics.latency_ms)} ms"),
        ("Velocidad", f"{_metric(metrics.tokens_per_second)} tok/s"),
        ("Motivo de finalización", _e(metrics.finish_reason or "—")),
    )
    return (
        '<section aria-label="Métricas de inferencia"><h2>Métricas</h2><dl>'
        + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows)
        + "</dl></section>"
    )


def _form(
    csrf_token: str,
    *,
    enabled: bool,
    system: str = _DEFAULT_SYSTEM,
    prompt: str = "",
    max_tokens: int,
) -> str:
    """Render a bounded form whose disabled state mirrors the server-side guard."""

    disabled = " disabled" if not enabled else ""
    return (
        '<form method="post" action="/app/llm" class="panel">'
        f'<input type="hidden" name="csrf_token" value="{_e(csrf_token)}"{disabled}>'
        f'<label for="llm-system">Instrucciones del sistema</label>'
        f'<input id="llm-system" name="system" required maxlength="4000" '
        f'value="{_e(system)}"{disabled}>'
        '<label for="llm-prompt">Mensaje</label>'
        f'<textarea id="llm-prompt" name="prompt" required maxlength="8000" '
        f'rows="8"{disabled}>{_e(prompt)}</textarea>'
        f'<label for="llm-max-tokens">Máximo de tokens</label>'
        f'<input id="llm-max-tokens" name="max_tokens" type="number" '
        f'min="1" max="{_e(max_tokens)}" value="{_e(max_tokens)}" required{disabled}>'
        f'<button type="submit"{disabled}>Consultar al modelo</button></form>'
    )


def llm_page(
    session: Session,
    client: InferenceClient,
    *,
    reachable: bool | None = None,
    health_error: str | None = None,
    system: str = _DEFAULT_SYSTEM,
    prompt: str = "",
    answer: Answer | None = None,
    error: tuple[str, str] | None = None,
) -> str:
    """Render status, warning and optional results with escaped dynamic content."""

    enabled = client.settings.enabled
    if not enabled:
        notice = (
            "La inferencia está deshabilitada. Configura ROSE_LLM_ENABLED=true "
            "para activar esta pantalla."
        )
        status = '<p class="error" role="alert">' + _e(notice) + "</p>"
        status += "<p>Estado: inferencia deshabilitada; endpoint no comprobado.</p>"
    elif reachable:
        status = '<p role="status">Estado: inferencia habilitada. Endpoint disponible.</p>'
    else:
        detail = f" ({health_error})" if health_error else ""
        status = (
            '<p class="error" role="alert">Estado: inferencia habilitada. '
            f"Endpoint no disponible{_e(detail)}.</p>"
        )
    warning = (
        '<p class="error" role="note"><strong>Experimental:</strong> '
        "el modelo puede equivocarse o producir errores factuales. "
        "Verifica la información antes de usarla.</p>"
    )
    navigation = (
        '<nav aria-label="Experimental"><a href="/app">Biblioteca</a> · '
        "Experimental: consultar al modelo</nav>"
    )
    error_html = ""
    if error is not None:
        code, message = error
        error_html = (
            '<section class="error" role="alert">'
            f"<p>{_e(message)}</p><p>Código: <strong>{_e(code)}</strong></p></section>"
        )
    answer_html = ""
    if answer is not None:
        completion_warning = ""
        if answer.metrics.finish_reason == "length":
            completion_warning = (
                '<p class="error" role="alert"><strong>Respuesta incompleta:</strong> '
                "la generación alcanzó max_tokens y el texto puede no estar completo.</p>"
            )
        answer_html = (
            '<section aria-label="Respuesta del modelo"><h2>Respuesta</h2>'
            + completion_warning
            + f"<pre>{_e(answer.text)}</pre></section>"
            + _metrics(answer)
        )
    body = (
        navigation
        + warning
        + status
        + error_html
        + _form(
            session.csrf_token,
            enabled=enabled,
            system=system,
            prompt=prompt,
            max_tokens=client.settings.max_tokens,
        )
        + answer_html
    )
    return page("Experimental: consultar al modelo", body)


def create_llm_router() -> APIRouter:
    """Create authenticated routes using the single app-scoped inference client."""

    router = APIRouter()

    @router.get("/app/llm", include_in_schema=False)
    async def llm_form(
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> HTMLResponse:
        session, _ = resolved
        client: InferenceClient = request.app.state.inference_client
        reachable: bool | None = None
        health_error: str | None = None
        if client.settings.enabled:
            try:
                health = await run_in_threadpool(client.health)
                reachable = health.available and health.model_present
                if not reachable:
                    health_error = "model_not_present"
            except RoseNexusError as error:
                reachable = False
                health_error = error.code
        content = llm_page(
            session,
            client,
            reachable=reachable,
            health_error=health_error,
        )
        return HTMLResponse(content, headers={"Cache-Control": "no-store"})

    @router.post("/app/llm", include_in_schema=False)
    async def llm_submit(
        request: Request,
        resolved: Annotated[tuple[Session, User], Depends(require_session)],
    ) -> Response:
        session, _ = resolved
        form = await request.form()
        try:
            require_csrf(request, _text(form.get("csrf_token")) or None)
        except ApiProblem as problem:
            return PlainTextResponse(
                f"{problem.code}: {problem.message}",
                status_code=problem.status_code,
                headers={"Cache-Control": "no-store"},
            )

        client: InferenceClient = request.app.state.inference_client
        system = _text(form.get("system"))
        prompt = _text(form.get("prompt"))
        max_tokens = _text(form.get("max_tokens"))
        page_arguments = {"system": system, "prompt": prompt}
        error: tuple[str, str] | None = None
        answer: Answer | None = None
        if not client.settings.enabled:
            error = (
                "inference_disabled",
                "La inferencia está deshabilitada. Configura ROSE_LLM_ENABLED=true para activarla.",
            )
        elif not prompt.strip():
            error = "invalid_prompt", "El mensaje no puede estar vacío."
        elif len(prompt) > _MAX_PROMPT_CHARACTERS:
            error = (
                "invalid_prompt_length",
                "El mensaje no puede superar los 8000 caracteres.",
            )
        elif max_tokens != str(client.settings.max_tokens):
            error = (
                "invalid_max_tokens",
                f"El máximo de tokens debe ser {client.settings.max_tokens} en esta pantalla experimental.",
            )
        elif not system.strip():
            error = (
                "invalid_system",
                "Las instrucciones del sistema no pueden estar vacías.",
            )
        else:
            try:
                answer = await run_in_threadpool(client.ask, system, prompt)
            except InferencePromptTooLong as inference_error:
                error = (
                    inference_error.code,
                    "El mensaje supera el presupuesto de contexto del modelo: "
                    f"{inference_error.message}",
                )
            except RoseNexusError as inference_error:
                error = (
                    inference_error.code,
                    "No se pudo consultar al modelo. Inténtalo de nuevo más tarde.",
                )
        content = llm_page(
            session,
            client,
            reachable=None if not client.settings.enabled else answer is not None,
            health_error=None if error is None else error[0],
            answer=answer,
            error=error,
            **page_arguments,
        )
        return HTMLResponse(content, headers={"Cache-Control": "no-store"})

    return router
