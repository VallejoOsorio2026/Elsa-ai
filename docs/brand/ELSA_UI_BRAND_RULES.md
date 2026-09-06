# Reglas de identidad para la futura interfaz ELSA

## Naturaleza de estas reglas

Este documento define **decisiones UX propias de ELSA** para el Bloque 3.
Las reglas oficiales PAPELSA se limitan a las recogidas en
[PAPELSA_BRAND_GUIDE.md](PAPELSA_BRAND_GUIDE.md). Colores, fuentes, espaciado y
estados remiten a [DESIGN_TOKENS.md](DESIGN_TOKENS.md). Estas reglas no crean
rutas, componentes, servicios, permisos ni capacidades todavía inexistentes.

## Identidad permanente y navegación

| Área | Regla UX ELSA |
|---|---|
| Sidebar | Fondo `surface.panel`, texto `text.primary`, selección `surface.selected` con indicador `action.primary`, etiqueta y estado accesible. El acento lima puede acompañar, nunca reemplazar, la selección. |
| Marca en sidebar | Wordmark principal en zona blanca separada de navegación. Mantener 2X y mínimo digital una vez confirmada su medición; no convertir el símbolo en un icono pequeño para hacerlo caber. |
| Topbar | Fondo `surface.panel`, contexto y título legibles, acciones agrupadas. Si la marca no cabe en la sidebar, ubicar aquí el wordmark sin slogan. Evitar repetirlo en cada zona. |
| Diseño compacto | Colapsar navegación sin perder etiquetas accesibles ni el contexto del activo. No fijar ancho de sidebar o altura de topbar como una supuesta regla de marca. |
| Acciones | `action.primary` con `text.on-primary`; enlaces subrayados. Foco visible con `focus.ring` y `focus.gap`. Separar la acción principal de las destructivas. |

Los nombres de tokens en este documento omiten el prefijo `elsa.` por brevedad.
No acoplar la identidad PAPELSA a un estado de servicio, aprobación o permiso.
El logotipo conserva sus colores y proporciones también al cambiar el layout.

## Chat y fuentes de evidencia

- Identificar explícitamente remitente y respuesta de ELSA; la alineación o
  el color no bastan para distinguirlos. Mantener texto seleccionable y legible.
- Fondo blanco, texto principal oscuro y ancho de lectura `reading.max-width`.
  Puede usarse `surface.selected` para diferenciar mensajes del usuario.
  El verde lima no será un fondo dominante de lectura prolongada.
- Usar `font.body` para mensajes, `font.heading` para títulos breves y
  `font.code` cuando ayude a distinguir identificadores. No reconstruir el logo
  con tipografía ni usar Comfortaa Light para texto técnico denso.
- Las **fuentes documentales** se presentan como enlaces descriptivos:
  documento/registro, versión y referencia disponible. No inventar citas,
  revisiones, fechas ni niveles de confianza para completar una tarjeta.
- Diferenciar evidencia publicada, información pendiente y contenido sin
  evidencia mediante texto explícito. Una respuesta del asistente no adquiere
  estado «validado» por llevar colores corporativos.
- Mostrar ausencia de evidencia o servicio no disponible como estado concreto.
  No simular resultados para rellenar el diseño. Los datos de las fuentes
  respetarán los permisos existentes del backend.

## Advertencias, errores y confirmaciones

| Estado visual | Regla UX ELSA |
|---|---|
| Información | `status.info`, icono informativo y mensaje descriptivo. |
| Advertencia | `status.warning`, icono y motivo visible; indicar qué debe revisar la persona. |
| Error | `status.error`, descripción del fallo y recuperación disponible; no mostrar secretos ni trazas internas. |
| Éxito | `status.success` solo tras confirmación real del sistema; precisar qué operación terminó. |

Estos colores semánticos **no son colores corporativos oficiales adicionales**.
No usar verde lima como sinónimo universal de correcto, ni gris claro para
ocultar advertencias. Las alertas deben entenderse sin percibir el color, tener
contraste suficiente y permanecer disponibles el tiempo necesario para leerlas.
Las comunicaciones críticas no dependen de un aviso fugaz ni de sonido.

## Audio

- Reservar una representación coherente para controles futuros: escuchar,
  pausar, detener, grabar y cancelar, solo cuando exista la capacidad real.
- Mostrar etiqueta, estado y duración cuando estén disponibles. «Grabando»
  exige texto y señal visual inequívoca; el color rojo, si se usa, es semántico
  ELSA y no una regla de marca. No animar el símbolo PAPELSA como indicador.
- Reproducción y captura comienzan por acción explícita; no reproducir audio
  automáticamente. Esta política de ELSA es más restrictiva que la condición
  WCAG para audio automático superior a tres segundos:
  [W3C, control de audio](https://www.w3.org/WAI/WCAG22/Understanding/audio-control.html).
- Conservar una vía textual equivalente para información técnica. No añadir
  transcripción ficticia: si no existe, indicar su ausencia y mantener accesible
  el contenido textual disponible. Controles operables por teclado y con nombre
  accesible; no depender de ondas animadas para comunicar estado.

## Centro de Revisión

- Presentación sobria: `surface.panel`, texto oscuro, títulos breves y tablas
  con encabezados claros. Priorizar fuente, versión, diferencias y estado sobre
  decoración. La marca no sustituye la trazabilidad.
- Exponer los estados que entregue el backend con etiquetas en español. Por
  ejemplo, «pendiente de revisión», «aprobado» y «publicado» deben distinguirse;
  una aprobación no implica publicación. No crear estados ni transiciones aquí.
- Usar advertencia para atención pendiente y éxito únicamente para una
  confirmación efectiva. Diferencias respecto de SAP no significan por sí solas
  error de Ingeniería: explicar su naturaleza mediante texto y evidencia.
- Separar acciones de revisión y publicación, y hacer visible su alcance y
  versión afectada. La confirmación de una acción sensible es una decisión UX;
  no redefine las reglas de autorización o el flujo de revisión del backend.
- La futura interfaz reflejará los permisos existentes. Ocultar o deshabilitar
  un botón no constituye un control de seguridad. No mostrar acciones exitosas
  antes de recibir confirmación del servidor.

## Accesibilidad y comprobación de diseño

Objetivo ELSA: WCAG 2.2 AA. Los pares de contraste y las referencias W3C
están documentados en [DESIGN_TOKENS.md](DESIGN_TOKENS.md). El cumplimiento
completo solo podrá verificarse cuando exista una interfaz; estos documentos
no lo certifican por adelantado.

En la futura revisión visual se comprobarán:

- Foco visible, orden de navegación coherente y operación por teclado.
- Etiquetas accesibles para iconos, controles de audio y navegación compacta.
  Si el logo es un enlace, su nombre accesible describe el destino; si solo
  duplica una identificación textual contigua, evitar una lectura redundante.
- Texto ampliable, distribución que se adapte al zoom y ausencia de controles
  ocultos por cabeceras o paneles. Las tablas densas pueden tener su propia
  región de desplazamiento, sin encerrar toda la lectura en ella.
- Contraste en reposo, hover, foco, selección y error; sin confiar solo en color,
  posición, iconos sin etiqueta o tipografía tenue.
- Área operable objetivo de 44 px, según los tokens, y preferencia de movimiento
  reducido. Nada de parpadeos, efectos en el logo o audio automático.
- Diferencia explícita entre identidad corporativa, estado del sistema y
  validación técnica del contenido.

## Decisiones abiertas acotadas

Confirmar la geometría X y el alcance de los 80 px antes de convertir la regla
del logo en medidas de layout; verificar licencias y archivos antes de cargar
las fuentes corporativas. No se proponen variantes nuevas, tema oscuro,
framework, rutas ni implementación funcional como parte de esta base.
