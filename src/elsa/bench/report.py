"""Informe comparativo reproducible.

Dos corridas iguales producen informes idénticos. Lo que varía entre
máquinas —tiempos, memoria, CPU— se aparta en una sección propia y se
excluye de la huella, de modo que la parte de calidad se puede comparar
byte a byte y la de coste se lee sabiendo que depende del hardware.
"""

import hashlib
import json
from collections.abc import Sequence

from elsa.bench.model import GoldenQuery, GoldenSet
from elsa.bench.runner import BenchmarkRun

__all__ = [
    "comparison_fingerprint",
    "golden_block",
    "render_json",
    "render_markdown",
    "render_query_diagnostics",
]


def comparison_fingerprint(runs: Sequence[BenchmarkRun]) -> str:
    """Huella de la parte comparable: identidad de cada corrida y su marcador."""
    payload = json.dumps(
        [
            {"identity": dict(run.metadata.identity()), "scoreboard": run.scoreboard.as_dict()}
            for run in runs
        ],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def golden_block(golden: GoldenSet) -> dict[str, object]:
    """El conjunto dorado, **una sola vez** en el informe.

    Los rankings de cada corrida solo guardan `query_id`; el texto, el eje y
    lo que se esperaba viven aquí y se cruzan por ese identificador. Repetirlo
    por corrida multiplicaría el archivo por el número de recuperadores sin
    añadir un solo dato.
    """
    return {
        "fingerprint": golden.fingerprint,
        "queries": [
            {
                "id": query.id,
                "text": query.text,
                "axis": query.axis.value,
                "match_kind": query.match_kind.value,
                "difficulty": query.difficulty.value,
                "is_diagnostic": query.is_diagnostic,
                "is_confusability": query.is_confusability,
                # `relevant` es la relevancia graduada: 2 responde, 1 parcial.
                "must_retrieve": dict(query.relevant),
                "must_not_retrieve": list(query.must_not_retrieve),
            }
            for query in golden.queries
        ],
    }


def render_json(
    runs: Sequence[BenchmarkRun],
    *,
    golden: GoldenSet | None = None,
    unmeasured: Sequence[dict[str, str]] = (),
) -> str:
    payload: dict[str, object] = {
        "tool": "embedding-benchmark",
        "comparison_fingerprint": comparison_fingerprint(runs),
    }
    if golden is not None:
        payload["golden"] = golden_block(golden)
    payload["runs"] = [run.as_dict() for run in runs]
    payload["unmeasured_candidates"] = list(unmeasured)
    return (
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


def _abstention_cell(run: BenchmarkRun) -> str:
    """`N/A` cuando el umbral no significa nada sobre esta puntuación.

    Distinguirlo de un guion importa: un guion se lee como «no había consultas
    que medir», y aquí lo que ocurre es que la métrica **no aplica**. Una
    fusión RRF suma recíprocos, no similitudes, así que cualquier umbral
    pensado para coseno la marcaría siempre como abstenida.
    """
    rate = run.scoreboard.abstention_rate
    if rate is not None:
        return f"{rate:.3f}"
    if any("NOT calibrated" in note for note in run.scoreboard.notes):
        return "N/A — no calibrada"
    return "—"


def _row(label: str, run: BenchmarkRun) -> str:
    primary = run.scoreboard.primary
    return (
        f"| {label} | {primary.queries} | "
        f"{primary.recall[1]:.3f} | {primary.recall[3]:.3f} | {primary.recall[5]:.3f} | "
        f"{primary.recall[10]:.3f} | {primary.mrr_at_10:.3f} | {primary.ndcg_at_10:.3f} | "
        f"{primary.precision_at_5:.3f} |"
    )


def render_markdown(
    runs: Sequence[BenchmarkRun], *, unmeasured: Sequence[dict[str, str]] = ()
) -> str:
    lines: list[str] = [
        "# Informe del banco de embeddings",
        "",
        "Generado por `elsa.tools.embedding_benchmark`. Corpus y conjunto dorado",
        "**sintéticos**: ningún dato de PAPELSA.",
        "",
        f"- Huella comparable: `{comparison_fingerprint(runs)[:32]}`",
    ]
    if runs:
        lines += [
            f"- Huella del corpus: `{runs[0].metadata.corpus_fingerprint[:32]}`",
            f"- Huella del conjunto dorado: `{runs[0].metadata.golden_fingerprint[:32]}`",
        ]
    lines += [
        "",
        "> Los ejes diagnósticos (códigos) **no** entran en la puntuación principal:",
        "> los resuelve el canal léxico o estructurado del Bloque 4.3, no el vector.",
        "> `confusion@5` mide **confusabilidad** del ranking, nunca autorización: el",
        "> aislamiento lo impone el filtro de la consulta, que este banco no aplica",
        "> a propósito para poder medir la confusión.",
        "",
        "## 1. Puntuación principal",
        "",
        "| Corrida | Consultas | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | P@5 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [_row(run.metadata.model_name, run) for run in runs]

    lines += ["", "## 2. Por eje", ""]
    axes = sorted({score.label for run in runs for score in run.scoreboard.per_axis})
    lines.append("| Eje | " + " | ".join(run.metadata.model_name for run in runs) + " |")
    lines.append("|---" * (len(runs) + 1) + "|")
    for axis in axes:
        cells = []
        for run in runs:
            found = next((s for s in run.scoreboard.per_axis if s.label == axis), None)
            cells.append("—" if found is None else f"{found.recall[5]:.3f}")
        lines.append(f"| {axis} (R@5) | " + " | ".join(cells) + " |")

    lines += ["", "## 3. Diagnóstico: códigos (no puntúa)", ""]
    lines.append("| Corrida | R@1 | R@5 | MRR@10 |")
    lines.append("|---|---|---|---|")
    for run in runs:
        codes = next((s for s in run.scoreboard.diagnostic if s.label == "codes"), None)
        if codes is None:
            lines.append(f"| {run.metadata.model_name} | — | — | — |")
        else:
            lines.append(
                f"| {run.metadata.model_name} | {codes.recall[1]:.3f} | "
                f"{codes.recall[5]:.3f} | {codes.mrr_at_10:.3f} |"
            )

    lines += ["", "## 4. Confusabilidad y abstención", ""]
    lines.append("| Corrida | confusion@5 | Abstención |")
    lines.append("|---|---|---|")
    for run in runs:
        confusions = [
            s.confusion_at_5 for s in run.scoreboard.per_axis if s.confusion_at_5 is not None
        ]
        average = f"{sum(confusions) / len(confusions):.3f}" if confusions else "—"
        lines.append(f"| {run.metadata.model_name} | {average} | {_abstention_cell(run)} |")

    lines += [
        "",
        "## 5. Coste y hardware",
        "",
        "Depende de la máquina; no se compara como calidad.",
        "",
    ]
    lines.append(
        "| Corrida | Runtime | Disp. | Dim. | Corpus (s) | p50 (ms) | p95 (ms) | "
        "RSS pico (MB) | Carga (s) | MB/1000 chunks |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for run in runs:
        meta = run.metadata
        lines.append(
            f"| {meta.model_name} | {meta.runtime} | {meta.device} | {meta.dimension} | "
            f"{meta.corpus_embed_seconds} | {meta.query_latency_p50_ms or '—'} | "
            f"{meta.query_latency_p95_ms or '—'} | {meta.peak_rss_mb or '—'} | "
            f"{meta.load_seconds or '—'} | {meta.vectors_mb_per_1000_chunks or '—'} |"
        )
    if runs:
        meta = runs[0].metadata
        lines += ["", f"Máquina: {meta.cpu} · {meta.ram_gb} GB RAM · GPU: {meta.gpu}", ""]

    if unmeasured:
        lines += [
            "## 6. Candidatos SIN MEDIR",
            "",
            "Un candidato sin medir **no se descarta ni se elige**. No se sustituye",
            "por puntuaciones públicas: no son comparables con esta medición.",
            "",
            "| Candidato | Motivo |",
            "|---|---|",
        ]
        lines += [f"| `{item['model']}` | {item['reason']} |" for item in unmeasured]
        lines.append("")

    notes = sorted({note for run in runs for note in run.scoreboard.notes})
    if notes:
        lines += ["## Notas de la medición", ""]
        lines += [f"- {note}" for note in notes]
        lines.append("")
    return "\n".join(lines)


def _rank_of_expected(query: GoldenQuery, ranked: Sequence[str]) -> int | None:
    """Posición del primer chunk esperado, o `None` si no salió."""
    for position, chunk_id in enumerate(ranked, start=1):
        if chunk_id in query.relevant:
            return position
    return None


def render_query_diagnostics(runs: Sequence[BenchmarkRun], golden: GoldenSet) -> str:
    """Comparación consulta por consulta entre corridas.

    Existe porque un promedio no dice **qué** consulta se degradó. Aquí se ve,
    para cada una, qué puso primero cada corrida y en qué posición quedó lo que
    se esperaba — que es lo que permite clasificar después dónde una fusión
    ayuda y dónde estorba.

    **No saca conclusiones ni recomienda nada**: presenta los datos.
    """
    lines = [
        "# Diagnóstico por consulta",
        "",
        "Qué puso primero cada corrida, y en qué posición quedó lo esperado.",
        "`—` significa que lo esperado **no** apareció en la lista devuelta.",
        "",
        "| Consulta | Eje | " + " | ".join(f"1.º {r.metadata.model_name}" for r in runs) + " |",
        "|---" * (len(runs) + 2) + "|",
    ]
    for query in golden.queries:
        if not query.expects_an_answer:
            continue
        cells = []
        for run in runs:
            result = run.results.get(query.id)
            ranked = list(result.ranked) if result else []
            position = _rank_of_expected(query, ranked)
            top = ranked[0][:8] if ranked else "—"
            cells.append(f"`{top}` (esperado en {position or '—'})")
        lines.append(f"| {query.text[:52]} | {query.axis.value} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Los identificadores van truncados a 8 caracteres para que la tabla se lea;",
        "los completos están en `informe.json`, bajo `rankings` de cada corrida.",
        "",
    ]
    return "\n".join(lines)
