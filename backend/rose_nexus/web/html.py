"""Small escaping-first HTML renderers for the server-rendered Spanish UI."""

from __future__ import annotations

import html

from .models import Artifact, Document, Job, User


def _e(value: object) -> str:
    """Escape every dynamic value before placing it in text or an attribute."""

    return html.escape(str(value), quote=True)


def page(title: str, body: str, *, refresh: bool = False) -> str:
    """Wrap already-rendered body fragments in the common same-origin page shell."""

    refresh_meta = '<meta http-equiv="refresh" content="2">' if refresh else ""
    return (
        "<!doctype html>"
        '<html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{refresh_meta}<title>{_e(title)} · Rose Nexus</title>"
        '<link rel="stylesheet" href="/static/app.css"></head>'
        f"<body><main><header><p class=\"brand\">Rose Nexus</p><h1>{_e(title)}</h1></header>"
        f"{body}</main></body></html>"
    )


def _navigation(csrf_token: str) -> str:
    return (
        '<nav aria-label="Sesión"><a href="/app">Biblioteca</a>'
        '<form method="post" action="/logout" class="inline">'
        f'<input type="hidden" name="csrf_token" value="{_e(csrf_token)}">'
        '<button type="submit" class="secondary">Cerrar sesión</button></form></nav>'
    )


def login_page(username: str = "", error: str | None = None) -> str:
    """Render the unauthenticated form without a password value or CSRF field."""

    notice = f'<p class="error" role="alert">{_e(error)}</p>' if error else ""
    body = (
        f"{notice}<form method=\"post\" action=\"/login\" class=\"panel\">"
        '<label for="username">Usuario</label>'
        f'<input id="username" name="username" autocomplete="username" required value="{_e(username)}">'
        '<label for="password">Contraseña</label>'
        '<input id="password" name="password" type="password" '
        'autocomplete="current-password" required>'
        '<button type="submit">Iniciar sesión</button></form>'
    )
    return page("Iniciar sesión", body)


def _documents_table(documents: list[Document]) -> str:
    if not documents:
        return "<p>Todavía no hay documentos en tu biblioteca.</p>"
    rows = "".join(
        "<tr>"
        f'<td data-label="Documento">{_e(document.filename)}</td>'
        f'<td data-label="Bytes">{_e(document.bytes)}</td>'
        f'<td data-label="Creado">{_e(document.created_at)}</td>'
        "</tr>"
        for document in documents
    )
    return (
        "<table><caption>Documentos</caption><thead><tr><th>Documento</th>"
        "<th>Bytes</th><th>Creado</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _jobs_table(jobs: list[Job]) -> str:
    if not jobs:
        return "<p>Todavía no hay trabajos de conversión.</p>"
    rows = "".join(
        "<tr>"
        f'<td data-label="Trabajo"><a href="/app/jobs/{_e(job.id)}">{_e(job.id)}</a></td>'
        f'<td data-label="Estado">{_e(job.status)}</td>'
        f'<td data-label="Marca">{_e(job.brand)}</td>'
        f'<td data-label="Creado">{_e(job.created_at)}</td>'
        "</tr>"
        for job in jobs
    )
    return (
        "<table><caption>Trabajos</caption><thead><tr><th>Trabajo</th><th>Estado</th>"
        f"<th>Marca</th><th>Creado</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def app_page(
    user: User,
    csrf_token: str,
    documents: list[Document],
    jobs: list[Job],
    max_input_bytes: int,
    pdf_enabled: bool,
) -> str:
    """Render upload guidance and only the authenticated user's library and jobs."""

    formats = (
        "Se generarán: TeX y PDF."
        if pdf_enabled
        else "Se generará: TeX. El PDF está deshabilitado hasta configurar el sandbox."
    )
    body = (
        f"<p>Sesión de <strong>{_e(user.username)}</strong>.</p>{_navigation(csrf_token)}"
        '<section><h2>Subir documento</h2>'
        '<form method="post" action="/app/upload" enctype="multipart/form-data" class="panel">'
        f'<input type="hidden" name="csrf_token" value="{_e(csrf_token)}">'
        '<label for="file">Documento Markdown o texto</label>'
        '<input id="file" name="file" type="file" accept=".md,.txt" required>'
        f"<p>Máximo: {_e(max_input_bytes)} bytes. {_e(formats)}</p>"
        '<button type="submit">Convertir documento</button></form></section>'
        f'<section><h2>Biblioteca</h2>{_documents_table(documents)}</section>'
        f'<section><h2>Actividad</h2>{_jobs_table(jobs)}</section>'
    )
    return page("Documentos", body)


def job_page(job: Job, artifacts: list[Artifact]) -> str:
    """Render job state, timestamps, failures and database-backed artifact links."""

    refresh = job.status in {"pending", "running"}
    details = [
        f"<dt>Estado</dt><dd>{_e(job.status)}</dd>",
        f"<dt>Creado</dt><dd>{_e(job.created_at)}</dd>",
        f"<dt>Iniciado</dt><dd>{_e(job.started_at or '—')}</dd>",
        f"<dt>Finalizado</dt><dd>{_e(job.finished_at or '—')}</dd>",
    ]
    if job.duration_ms is not None:
        details.append(f"<dt>Duración</dt><dd>{_e(job.duration_ms)} ms</dd>")
    body = (
        '<p><a href="/app">← Volver a la biblioteca</a></p>'
        f"<dl>{''.join(details)}</dl>"
    )
    if job.status == "failed":
        body += (
            '<section class="error" role="alert"><h2>Error de conversión</h2>'
            f"<p><strong>{_e(job.error_code or 'internal_error')}</strong>: "
            f"{_e(job.error_message or 'No se pudo convertir el documento.')}</p></section>"
        )
    if job.status == "completed" and artifacts:
        labels = {"source": "Original", "tex": "Documento .tex", "pdf": "Documento .pdf"}
        links = "".join(
            f'<li><a href="/api/jobs/{_e(job.id)}/artifacts/{_e(artifact.kind)}" '
            f'download>{_e(labels.get(artifact.kind, artifact.kind))}</a></li>'
            for artifact in artifacts
        )
        body += f'<section><h2>Descargas</h2><ul>{links}</ul></section>'
    elif refresh:
        body += "<p>La conversión está en curso. Esta página se actualizará automáticamente.</p>"
    return page("Trabajo de conversión", body, refresh=refresh)
