# Cota de Anegamiento – complemento para QGIS

Calcula la **cota de anegamiento teórica** a partir de un modelo digital de elevación (DEM),
pensado para el diseño de drenaje vial a nivel de perfil. **Basta con elegir el DEM**: el
complemento lo prepara solo, encuentra las depresiones del terreno, hace el balance hídrico
con la lluvia de diseño y entrega mapas, tablas e informe.

Solo usa `numpy` y GDAL, que ya vienen con QGIS. Funciona en QGIS 3.16 o superior (Qt5 y Qt6).

## Instalación

1. Descarga `cota_anegamiento.zip` (pestaña *Releases* o el artefacto de la acción de CI), o
   genéralo con `python scripts/empaquetar.py`.
2. En QGIS: **Complementos › Administrar e instalar complementos › Instalar a partir de ZIP**.
3. Aparecerá un ícono en la barra de herramientas, el menú **Complementos › Cota de Anegamiento**
   y el grupo **Cota de Anegamiento › Hidrología vial** en la caja de herramientas de Procesos.

## Uso rápido

1. Carga el DEM en el proyecto (en metros o en grados, da igual).
2. Pulsa el ícono **Cota de anegamiento (análisis rápido)**.
3. Elige el DEM. Revisa los datos de entrada que aparecen debajo (lluvia de diseño, CN,
   filtros de ruido, altura del terraplén y borde libre; vienen con valores por defecto) y
   pulsa **Ejecutar**. Solo el DEM es obligatorio.

El complemento:

- recorta el DEM a la zona que indiques (opcional);
- lo **reproyecta a la zona UTM correspondiente** si está en grados;
- lo **remuestrea** si tiene más de 6 millones de celdas;
- **rellena los huecos interiores** sin datos (hasta 10 celdas);
- identifica las depresiones (Priority-Flood), descarta el ruido, calcula el área de aporte de
  cada una y hace el balance hídrico en cascada con la lluvia de diseño (150 mm y CN = 88 por
  defecto);
- carga las capas de salida **ya con simbología** y escribe un informe HTML con el resumen, las
  tablas y el gráfico del perfil.

Si además indicas el **eje de la vía**, obtienes la cota de agua y la rasante mínima cada 20 m,
y un segundo escenario con la vía en terraplén para ubicar las alcantarillas.

Si indicas la **red de drenes** (líneas con capacidad, ancho y profundidad), el balance descuenta
de cada depresión el volumen que sus drenes pueden evacuar durante el evento y, si das la
profundidad, los graba en el DEM para que conecten las depresiones que atraviesan.

## Análisis completo

Menú **Complementos › Cota de Anegamiento › Análisis completo…** muestra todos los parámetros:
lluvia de diseño o serie de máximas anuales (Gumbel), método de escorrentía (SCS-CN o
coeficiente C), filtros de ruido, altura del terraplén, borde libre, tamaño de celda de trabajo,
relleno de huecos y desborde del río en lámina (Manning).

Los mismos parámetros están en la sección «Parámetros avanzados» del análisis rápido.

## Salidas

| Salida | Contenido |
|---|---|
| Depresiones (polígonos) | Una fila por depresión y escenario: cota de rebose, volumen, área de aporte, volumen que le llega, volumen evacuado por drenes, si se llena, cota de agua, tirante, si toca la vía o vierte sobre ella, progresiva más cercana. |
| Perfil del eje (puntos) | Cada 20 m: terreno, agua sin vía y con vía, lámina de desborde, cota de diseño, rasante mínima, altura mínima de terraplén y escenario que controla. |
| Tirante sin vía / con vía (ráster) | Profundidad del agua (m). |
| Cota de agua sin vía (ráster) | Nivel del agua (msnm). |
| Áreas de aporte (ráster, opcional) | Id de la depresión a la que drena cada celda. |
| Curvas cota-volumen (CSV) | Curva de cada depresión relevante, cada 0.10 m. |
| Informe de cálculo (HTML) | Resumen, tramos anegados, datos de entrada, lluvia y escorrentía, tablas, gráfico del perfil, limitaciones y texto de sustento para el perfil. |

Además, el algoritmo devuelve valores numéricos (cota máxima, rasante mínima, tirante máximo,
número de depresiones) utilizables en el Modelador de Procesos.

## Documentación

- [Guía paso a paso (PDF)](docs/Guia_Cota_Anegamiento.pdf): datos de entrada, parámetros,
  interpretación de resultados, problemas frecuentes y método.
- [Manual de parámetros](docs/MANUAL_PARAMETROS.md): criterios, fuentes y valores típicos para
  llenar cada dato de entrada, incluida la red de drenes.
- [Análisis de la aplicación y mejoras](docs/ANALISIS_Y_MEJORAS.md).
- [Historial de cambios](CHANGELOG.md).

## Desarrollo

```bash
pip install numpy pytest
python -m pytest            # pruebas del núcleo de cálculo (no necesitan QGIS)
python scripts/empaquetar.py   # genera dist/cota_anegamiento.zip
```

Estructura:

```
cota_anegamiento/
  core.py          núcleo de cálculo (numpy): Priority-Flood, áreas de aporte, balance hídrico
  herramientas.py  eje de la vía, perfil, CSV, informe HTML y gráfico SVG
  algoritmo.py     algoritmos de Procesos (completo y rápido), preparación del DEM, estilos
  provider.py      proveedor de Procesos
  plugin.py        menú y barra de herramientas
tests/             pruebas con pytest (usa un sustituto mínimo de PyQGIS para importar el código)
scripts/           empaquetado del ZIP
docs/              guía en PDF y análisis
```

El resultado es referencial, apropiado para estudios a nivel de perfil. En el expediente
técnico debe validarse con topografía de detalle, huellas de inundación y un modelo hidráulico.

## Licencia

GPL-2.0 o posterior. Ver [LICENSE](LICENSE).
