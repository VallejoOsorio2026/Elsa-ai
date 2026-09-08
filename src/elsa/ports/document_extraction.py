"""Puerto de extracción documental.

Convierte los bytes de un documento en **bloques estructurales ordenados**:
títulos, párrafos, elementos de lista, pasos numerados, advertencias y
tablas. No decide nada sobre el conocimiento; solo dice qué hay escrito, en
qué orden y en qué página.

Existe separado del puerto ``ocr`` a propósito. OCR responde «qué texto hay
en esta imagen»; la extracción documental responde «qué estructura tiene
este documento». Un motor puede resolver las dos cosas (Docling), pero son
contratos distintos y se reemplazan por separado: cambiar de OCR no debería
obligar a cambiar el chunking, ni al revés.

**En este bloque no hay OCR.** Un documento escaneado no se interpreta: se
rechaza con un aviso claro. Inventar texto que nadie leyó sería la peor
forma posible de romper la regla 5 de ``CLAUDE.md``.

La salida es **determinística**: los mismos bytes producen exactamente los
mismos bloques, con los mismos desplazamientos y los mismos números de
página. De ahí depende que un chunk pueda repetirse y dar el mismo hash.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from elsa.ingestion.model import IngestionWarning

__all__ = [
    "BlockKind",
    "DocumentExtractionPort",
    "ExtractedBlock",
    "ExtractedDocument",
    "UnsupportedDocumentError",
]


class UnsupportedDocumentError(Exception):
    """El motor configurado no sabe leer este tipo de documento.

    Es distinto de «el documento está mal»: aquí el archivo puede ser
    perfectamente válido y simplemente no haber todavía un extractor para
    él. Se distingue para que el mensaje al administrador no culpe al
    archivo de una limitación del backend.
    """


class BlockKind(StrEnum):
    """Qué es un bloque dentro del documento.

    La lista es corta y deliberadamente estructural: son las unidades que el
    chunking respeta como indivisibles o como frontera natural. Un tipo que
    no cambia ninguna decisión de chunking no merece existir.
    """

    HEADING = "heading"
    """Título o subtítulo. Abre una sección y define su profundidad."""

    PARAGRAPH = "paragraph"
    """Prosa corrida."""

    LIST_ITEM = "list_item"
    """Elemento de una lista sin orden."""

    STEP = "step"
    """Paso de un procedimiento numerado. El orden es parte del significado."""

    WARNING = "warning"
    """Advertencia, precaución o peligro.

    Se distingue del párrafo porque **nunca puede separarse de su contexto**
    ni partirse: una advertencia a medias es peor que ninguna.
    """

    TABLE = "table"
    """Tabla técnica. Es una unidad coherente: sus filas no significan nada sueltas."""

    CAPTION = "caption"
    """Pie de figura o de tabla. Acompaña al bloque anterior."""


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    """Una unidad estructural del documento, tal como venía escrita.

    ``char_start`` y ``char_end`` son desplazamientos dentro de
    :attr:`ExtractedDocument.text`. Son lo que permite volver del chunk al
    texto fuente exacto sin volver a procesar el archivo, y lo que hace
    verificable la afirmación «este chunk dice esto porque el documento
    decía esto».
    """

    ordinal: int
    """Posición del bloque en el documento, desde 0 y sin huecos."""

    kind: BlockKind
    text: str
    char_start: int
    char_end: int
    page_start: int | None = None
    page_end: int | None = None
    """Página final. Distinta de :attr:`page_start` cuando el bloque cruza
    un salto de página: un párrafo partido entre dos páginas sigue siendo un
    párrafo, y su procedencia son las dos."""

    level: int | None = None
    """Profundidad del título (1-6) o nivel de anidamiento de la lista."""

    number_label: str | None = None
    """Numeración impresa en el documento (``3.2``, ``1.``, ``a)``), si la trae.

    Se conserva literal: es como el ingeniero se refiere al paso o a la
    sección cuando habla por teléfono con la planta.
    """

    rows: tuple[tuple[str, ...], ...] = ()
    """Filas de la tabla, solo para :attr:`BlockKind.TABLE`."""

    header_rows: int = 0
    """Cuántas filas iniciales de :attr:`rows` son encabezado.

    Si una tabla hay que partirla, el encabezado se repite en cada trozo:
    una tabla técnica sin sus rótulos no se puede leer.
    """

    @property
    def pages(self) -> tuple[int, ...]:
        """Páginas que ocupa el bloque, en orden."""
        if self.page_start is None:
            return ()
        end = self.page_end if self.page_end is not None else self.page_start
        return tuple(range(self.page_start, end + 1))


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """Resultado completo de extraer un documento."""

    text: str
    """Texto normalizado al que apuntan los desplazamientos de los bloques."""

    blocks: tuple[ExtractedBlock, ...] = ()
    page_count: int | None = None
    content_type: str = "text/plain"

    extractor: str = "unknown"
    """Nombre del motor que produjo esta extracción."""

    extractor_version: str = "0"
    """Versión del motor. Entra en la identidad de la versión del documento.

    Cambiar de motor cambia el resultado aunque el archivo sea idéntico, así
    que una versión no puede decir solo «vino de este PDF»: tiene que decir
    también «leído por este extractor». Sin eso, dos versiones distintas
    parecerían la misma.
    """

    warnings: tuple[IngestionWarning, ...] = field(default_factory=tuple)

    @property
    def headings(self) -> tuple[ExtractedBlock, ...]:
        return tuple(block for block in self.blocks if block.kind is BlockKind.HEADING)


@runtime_checkable
class DocumentExtractionPort(Protocol):
    """Motor de extracción documental reemplazable."""

    @property
    def name(self) -> str:
        """Identificador estable del motor, que se persiste con la versión."""
        ...

    @property
    def version(self) -> str:
        """Versión del motor. Cambiarla invalida la equivalencia de versiones."""
        ...

    def supports(self, content_type: str, filename: str | None = None) -> bool:
        """Indica si este motor puede leer ese tipo de documento."""
        ...

    async def extract(
        self,
        content: bytes,
        *,
        content_type: str,
        filename: str | None = None,
    ) -> ExtractedDocument:
        """Extrae la estructura del documento.

        Lanza :class:`UnsupportedDocumentError` si el motor no lo soporta.
        """
        ...
