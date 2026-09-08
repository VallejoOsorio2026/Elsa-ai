"""Documentos sintéticos para las pruebas del conocimiento documental.

**Ninguno procede de la planta.** Son manuales inventados que reproducen la
*forma* de un documento técnico real —títulos numerados, pasos, advertencias,
tablas, saltos de página— sin un solo dato de PAPELSA. Los documentos reales
no entran en Git (CLAUDE.md, sección 6); la prueba de aceptación contra
archivos reales se ejecuta fuera del repositorio.

Los códigos y denominaciones que aparecen son deliberadamente ficticios
(``XX-000``, «Bomba de ejemplo») para que ni siquiera por casualidad puedan
confundirse con información de planta.
"""

FORM_FEED = "\f"

MANUAL_V1 = """# Manual de ejemplo del equipo de laboratorio

Este documento es sintético y existe para probar la ingesta. No describe
ningun equipo real.

## 1. Alcance

El alcance cubre la revision periodica del conjunto de ejemplo XX-000.
Aplica unicamente al banco de pruebas del laboratorio.

## 2. Seguridad

ADVERTENCIA: bloquear y etiquetar la fuente de energia antes de abrir
cualquier tapa. La omision de este paso puede causar lesiones graves.

- Usar guantes de proteccion.
- Verificar ausencia de tension.
- Despresurizar el circuito auxiliar.

## 3. Procedimiento de revision

### 3.1 Desmontaje

1. Retirar los cuatro tornillos de la tapa superior.
2. Extraer el conjunto de ejemplo sin forzar los apoyos.
3. Marcar la orientacion antes de separar las mitades.

### 3.2 Inspeccion

Revisar el desgaste de las superficies de contacto y anotar las medidas
obtenidas en el formato de registro.

| Componente | Medida nominal | Tolerancia |
|---|---|---|
| Eje de ejemplo | 40 mm | 0,05 mm |
| Buje de ejemplo | 42 mm | 0,10 mm |
| Tapa de ejemplo | 12 mm | 0,20 mm |

Tabla 1. Medidas de referencia del conjunto de ejemplo.

## 4. Registro

Anotar la fecha de intervencion y el responsable en el formato interno.
"""

# Misma estructura, con una tolerancia cambiada en 3.2 y un paso nuevo en
# 3.1. Sirve para comprobar que la comparacion entre versiones distingue lo
# que cambio de lo que no.
MANUAL_V2 = MANUAL_V1.replace(
    "3. Marcar la orientacion antes de separar las mitades.",
    "3. Marcar la orientacion antes de separar las mitades.\n"
    "4. Retirar el buje de ejemplo con extractor.",
).replace("| Buje de ejemplo | 42 mm | 0,10 mm |", "| Buje de ejemplo | 42 mm | 0,08 mm |")

# Un parrafo que empieza en una pagina y termina en la siguiente. El avance
# de pagina no debe partirlo.
CROSS_PAGE = (
    "# Manual con salto de pagina\n"
    "\n"
    "## 1. Descripcion\n"
    "\n"
    "El conjunto de ejemplo se compone de un eje, dos bujes y una tapa que\n"
    + FORM_FEED
    + "cierra el alojamiento y sostiene el sello de ejemplo en su posicion.\n"
    "\n"
    "## 2. Ajustes\n"
    "\n"
    "El ajuste se verifica con galgas de laminas.\n"
)

# Un parrafo unico y muy largo: obliga al corte por tamano y por tanto al
# solape.
LONG_SECTION = (
    "# Manual extenso\n"
    "\n"
    "## 1. Descripcion detallada\n"
    "\n"
    + " ".join(
        f"La frase numero {index} describe una caracteristica del conjunto de "
        f"ejemplo y ocupa espacio suficiente para forzar el corte por tamano."
        for index in range(1, 41)
    )
    + "\n"
)

# Un paso numerado descomunal: es indivisible, no se parte y se marca.
INDIVISIBLE_STEP = (
    "# Manual con un paso enorme\n"
    "\n"
    "## 1. Procedimiento\n"
    "\n"
    "1. " + " ".join(f"accion {index} del mismo paso" for index in range(1, 401)) + "\n"
)

# Tabla larga sin encabezado declarado y tabla larga con el.
LONG_TABLE_WITH_HEADER = (
    "# Manual con tabla larga\n"
    "\n"
    "## 1. Tabla\n"
    "\n"
    "| Codigo | Denominacion | Cantidad |\n"
    "|---|---|---|\n"
    + "".join(
        f"| XX-{index:03d} | Componente de ejemplo numero {index} con una "
        f"denominacion larga | {index} |\n"
        for index in range(1, 61)
    )
)

# Ningun bloque legible.
EMPTY_DOCUMENT = "\n   \n\n\t\n"

# Un binario disfrazado de texto.
NOT_TEXT = b"%PDF-1.7\n\x00\x00\x00\x01binario"


def encoded(text: str) -> bytes:
    """El documento tal y como llegaria al backend."""
    return text.encode("utf-8")
