# Historial de cambios

## 1.1.0

### Nuevo
- Algoritmo **Análisis rápido: cota de anegamiento solo con el DEM**. Solo pide el DEM (y el
  eje de la vía, opcional); todo lo demás va en «Parámetros avanzados» con valores por defecto.
  El ícono de la barra de herramientas abre este algoritmo.
- **Preparación automática del DEM**: reproyección a la zona UTM correspondiente cuando el DEM
  está en grados, remuestreo automático cuando supera los 6 millones de celdas (o al tamaño de
  celda de trabajo que indique el usuario), y relleno de huecos interiores sin datos con
  `gdal.FillNodata` (solo los huecos que no tocan el borde).
- **Simbología automática** en las salidas: rampas de azules para tirante y cota de agua,
  paleta por id para las áreas de aporte, depresiones en azul / naranja (toca la vía) / rojo
  (vierte sobre la vía) y perfil del eje graduado por tirante.
- Salida opcional **Áreas de aporte por depresión** (ráster de ids).
- **Salidas numéricas** (cota de agua máxima, rasante mínima, tirante máximo, número de
  depresiones, resumen) para encadenar en el Modelador de Procesos.
- **Gráfico SVG del perfil** longitudinal en el informe HTML (terreno, agua sin/con vía,
  rasante mínima y zona anegada).
- Avisos en el registro cuando el filtro de ruido descarta todas las depresiones o acepta
  demasiadas, y cuando las celdas no son cuadradas.
- Menú con entrada **Guía de uso (PDF)**; la guía viaja dentro del ZIP.
- Pruebas automáticas con `pytest` (núcleo, herramientas, definición de parámetros) y flujo de
  CI que ejecuta las pruebas y publica el ZIP como artefacto.

### Corregido
- **Dirección de flujo en llanuras**: el área de aporte usaba solo el puntero del Priority-Flood,
  que en laderas uniformes desviaba el flujo sistemáticamente hacia un lado según el orden de
  visita de las celdas. Ahora se usa D8 (máxima pendiente) sobre el DEM rellenado y el puntero
  del Priority-Flood solo en zonas planas. El excedente de una depresión llega así a la
  depresión realmente situada aguas abajo.
- La serie de precipitaciones acepta saltos de línea además de comas y puntos y coma.
- El resumen del informe sin eje de vía muestra el tirante máximo y el número de depresiones
  analizadas.

## 1.0.0
- Versión inicial.
