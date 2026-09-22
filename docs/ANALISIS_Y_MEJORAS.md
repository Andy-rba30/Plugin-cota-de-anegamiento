# Análisis de la aplicación y propuesta de mejoras

Complemento QGIS «Cota de Anegamiento» (v1.0.0 recibida → v1.1.0 en este repositorio).

## 1. Qué hace y cómo está construida

La aplicación es un complemento de QGIS con un proveedor de Procesos. Su flujo es:

1. **Lectura del DEM** con GDAL (`algoritmo.py`).
2. **Relleno de depresiones** con Priority-Flood (Barnes et al., 2014) en `core.py`, que da la cota
   de rebose de cada depresión y un puntero de flujo por celda.
3. **Etiquetado** de las depresiones (scipy si existe; si no, un recorrido en Python).
4. **Área de aporte**: la primera depresión que encuentra el camino de flujo de cada celda.
5. **Balance hídrico en cascada**: lámina escurrida (SCS-CN o C) × área de aporte contra la curva
   cota-volumen de cada depresión; el excedente pasa a la depresión de aguas abajo.
6. **Escenario con vía**: se elevan las celdas del eje (rasterizado con conectividad 4) y se
   repite el análisis para ver dónde represa el terraplén.
7. **Perfil del eje** (`herramientas.py`): cota de diseño = máximo entre agua sin vía, agua con
   vía y lámina de desborde (Manning) en un radio alrededor de cada punto; rasante = cota + borde
   libre.
8. **Salidas**: polígonos, puntos del eje, rásters, CSV de curvas e informe HTML.

Puntos fuertes:

- Núcleo de cálculo **sin dependencias externas** (numpy + biblioteca estándar); GDAL solo en la
  capa QGIS. Instala en cualquier QGIS.
- Método hidrológico razonable y bien documentado (guía PDF con parámetros, limitaciones y texto
  de sustento para el perfil).
- Buena compatibilidad de API: QGIS 3.16 a 3.4x y Qt6.
- Cancelación y progreso conectados al diálogo de Procesos.

## 2. Verificación del núcleo

Se probó `core.py` con DEM sintéticos (sin QGIS):

| Prueba | Resultado |
|---|---|
| Cubeta parabólica (r = 100 m, h = 2 m) | Volumen al rebose 31 411 m³ frente a 31 416 m³ teóricos (0.02 %). Nivel de agua coherente con la curva cota-volumen. |
| Dos cubetas en cascada | La pequeña rebosa y su excedente llega a la grande (ver corrección 3.1). |
| Filtro de ruido | Una cubeta de 0.2 m se descarta con profundidad mínima 0.3 m. |
| Hueco sin datos en el fondo | Se comporta como sumidero (limitación documentada; motiva el relleno automático). |
| Terraplén que cruza un valle | Crea la depresión aguas arriba, toca la vía y vierte por el punto más bajo del terraplén. |
| Rendimiento | 1 M de celdas ≈ 6 s; 4 M ≈ 30 s (Python puro, un núcleo). |

## 3. Problemas encontrados y corregidos en 1.1.0

### 3.1 Dirección de flujo sesgada en llanuras (corrección de fondo)

El área de aporte se calculaba siguiendo el puntero «padre» del Priority-Flood. Ese puntero
apunta a la celda desde la que se **descubrió** cada celda, no a la de máxima pendiente. En una
ladera uniforme (caso típico de las llanuras de Piura) las celdas de igual cota se desempatan por
índice, y el flujo se desplazaba una columna por fila de forma sistemática. Consecuencia: el
excedente de una depresión podía «no llegar» a la depresión de aguas abajo y salir por el borde.

Solución: dirección **D8 de máxima pendiente sobre el DEM rellenado** y puntero del
Priority-Flood solo donde no hay descenso (zonas planas y depresiones rellenadas). Se demuestra
en `tests/test_core.py::test_flujo_d8_en_ladera_plana` y `test_cascada_dos_cubetas`.

### 3.2 El DEM debía venir listo (reproyectado, recortado, sin huecos)

La versión 1.0 rechazaba DEM en grados y obligaba a reproyectar, recortar y rellenar a mano.
Ahora `_preparar_dem` hace todo eso en memoria con GDAL: elección automática de la zona UTM por
el centroide, remuestreo con `average` cuando hay demasiadas celdas, y `FillNodata` limitado a los
huecos interiores (los que no tocan el borde), para no inventar terreno fuera del DEM.

### 3.3 Demasiados parámetros para el uso habitual

Se añadió el algoritmo **rápido**: DEM (y eje opcional) visibles; el resto en «avanzados».
Mismo código, sin duplicación (subclase que solo cambia las banderas de los parámetros).

### 3.4 Salidas sin simbología

Las capas se cargaban en gris. Ahora un post-procesador de Procesos aplica estilos al cargar:
rampas de azules (tirante, cota), reglas para depresiones (toca / vierte sobre la vía) y perfil
graduado por tirante. El estilo nunca hace fallar el algoritmo (errores → aviso en el registro).

### 3.5 Otros

- Informe: gráfico SVG del perfil, nota de preparación del DEM, resumen sin eje más completo.
- Avisos de diagnóstico: filtro de ruido demasiado estricto o demasiado laxo, celdas no cuadradas.
- Salidas numéricas para el Modelador; ráster de áreas de aporte; guía PDF dentro del ZIP.
- Serie de lluvias con saltos de línea; `finalize()` de los sinks cuando existe.
- Pruebas automáticas y CI (pytest + empaquetado del ZIP).

## 4. Mejoras propuestas para versiones siguientes

Ordenadas por relación beneficio / esfuerzo.

1. **Rendimiento del Priority-Flood** (esfuerzo medio). El bucle es Python puro. Opciones: (a)
   `numba` opcional si está instalado, (b) procesar por bloques con costura, (c) implementar el
   relleno con `scipy.ndimage` (reconstrucción morfológica por iteraciones) cuando scipy exista.
   Meta: DEM de 20–25 M de celdas en menos de un minuto.
2. **Alcantarillas existentes o propuestas** (esfuerzo medio). Capa de puntos/líneas con cota de
   fondo y diámetro; el escenario «con vía» perforaría el terraplén en esas celdas (bajar la cota
   del DEM elevado). Permite pasar de «dónde van» a «si bastan».
3. **Sensibilidad automática** (esfuerzo bajo). Ejecutar en una sola corrida CN bajo / CN alto /
   llenado hasta el rebose y entregar la envolvente, como recomienda la guía (sección 6.4).
4. **Hidrograma simplificado** (esfuerzo alto). Hoy el balance es volumétrico (toda la lluvia
   escurre a la depresión). Un método racional o SCS con tiempo de concentración permitiría
   estimar caudal pico para dimensionar las obras de cruce, no solo ubicarlas.
5. **Lluvia por zonas** (esfuerzo bajo). Aceptar un ráster o polígonos de CN en vez de un valor
   único, para cuencas con usos de suelo mixtos.
6. **Doble Gumbel / otras distribuciones** (esfuerzo bajo-medio). La guía ya advierte que Gumbel
   simple subestima en años El Niño; incorporar Log-Pearson III o Gumbel mixta con prueba de
   bondad de ajuste.
7. **Perfil interactivo** (esfuerzo medio). Un panel en QGIS con el gráfico del perfil (matplotlib
   o QtCharts) sincronizado con el mapa, en lugar de solo el SVG del informe.
8. **Exportación DXF/LandXML** del perfil (esfuerzo bajo) para llevar rasante y cota de agua a
   Civil 3D / AutoCAD.
9. **Traducción** (esfuerzo bajo). Los textos ya pasan por `tr()`; falta el archivo `.ts` para
   inglés si se publica en el repositorio oficial de QGIS.
10. **Publicación en el repositorio oficial de complementos** (esfuerzo bajo): requiere licencia
    explícita (GPL-2+), correo del autor en `metadata.txt` y una URL de seguimiento de errores.
11. **Vista previa de las depresiones antes del balance** (esfuerzo bajo): un algoritmo ligero
    que solo etiquete depresiones y sus atributos morfométricos para afinar los filtros de ruido
    sin esperar el balance completo.

## 5. Limitaciones que siguen vigentes

- Los bordes del DEM y los huecos exteriores son salidas de agua: usa un DEM con margen amplio.
- Balance volumétrico sin infiltración durante el evento, evaporación, bombeo ni drenes.
- Un solo espejo de agua por depresión; el escenario con vía supone terraplén continuo.
- El desborde del río se evalúa como lámina uniforme; no sustituye un modelo hidráulico 2D.
- La precisión depende del DEM: con 30 m de celda los resultados son solo indicativos.
