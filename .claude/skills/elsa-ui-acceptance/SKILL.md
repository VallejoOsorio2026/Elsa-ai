---
name: elsa-ui-acceptance
description: Aceptación de la interfaz de ELSA en web/ - responsive a 320/375/768/1024/1366/1920, foco visible, recorrido con Tab y Shift+Tab, scroll y desbordamiento, roles y nombres accesibles, captura de audio y flujos principales (aportar, revisar, mis aportes). Úsala al terminar un cambio en web/, antes de enseñar la demo, o cuando alguien pregunte si la interfaz está lista. NO la uses para escribir la interfaz desde cero, para decisiones de marca o tipografía (eso está en docs/brand/), ni para pruebas de backend (eso es elsa-testing).
---

# Aceptación de la interfaz de ELSA

La interfaz es estática y la sirve el propio backend (`web/`, servida por
FastAPI). No hay framework ni build. Reglas de marca, tipografía, color y
teclado: `docs/brand/ELSA_UI_BRAND_RULES.md` — es la autoridad, no repitas su
contenido.

Esta skill es la **lista de comprobación de aceptación**, no la guía de diseño.

## 1. Anchos

Comprueba a 320, 375, 768, 1024, 1366 y 1920 px de ancho.

En cada uno:

- Ningún scroll horizontal en el `body`. Lo ancho (tablas, código, listas de
  componentes) desborda dentro de su contenedor, no fuera de la página.
- Ningún texto cortado ni superpuesto, ni objetivo táctil menor a 44×44 px
  en 320 y 375.
- La cabecera y el logotipo respetan área de seguridad y tamaño mínimo.
- 320 es el caso duro: si algo se rompe, se rompe ahí.

## 2. Teclado

- El orden de tabulación lo da el DOM. Nada de `tabindex` positivo.
- `Tab` y `Shift+Tab` recorren todo lo interactivo, en el orden en que se lee,
  y vuelven atrás por el mismo camino.
- Lo oculto no se tabula.
- El foco es **siempre visible** y no se pierde: al abrir un panel se lleva, al
  cerrarlo vuelve al control que lo abrió.
- Ninguna acción escribe en un campo ni saca el cursor de él mientras el
  usuario escribe.
- Todo lo accionable con ratón lo es con teclado. `Enter` y `Espacio` activan.

## 3. Semántica

- Cada control tiene rol y nombre accesible; los iconos sin texto llevan
  etiqueta.
- Los estados (cargando, error, grabando, pendiente) se anuncian, no solo se
  colorean. El color nunca es el único portador de información.
- Los mensajes de error dicen qué hacer, y no filtran trazas internas.

## 4. Audio

- Grabar, detener y reintentar funcionan con ratón **y** con teclado; el
  contador no se come los clics.
- Se declara qué método de captura está activo.
- La transcripción simulada se declara como simulada — nunca se presenta como
  real (`health` la reporta `degraded`, y es correcto).
- Denegar el permiso de micrófono da un mensaje claro y deja la ruta escrita
  disponible.

## 5. Flujos principales

Recorre de punta a punta, con teclado:

1. **Aportar** — escribir un aporte, ver lo que ELSA reconoció antes de
   guardar, enviar. Queda `pending`.
2. **Mis aportes** — el aporte enviado aparece con su estado real.
3. **Revisar** — aprobar un aporte. La pantalla debe decir, donde el usuario
   está a punto de aprobar, que **aprobar no es publicar**: aprobar valida el
   aporte; publicar es una decisión posterior y explícita.
4. El activo sobre el que se trabaja lo deciden los permisos, no un valor fijo.
5. Sin permiso: 403 con mensaje entendible, no una pantalla vacía.

## 6. Reporte

Una línea por punto, con el resultado observado. Un punto no comprobado se
declara como no comprobado. Si no ejecutaste la interfaz, dilo: no describas
lo que crees que haría.
