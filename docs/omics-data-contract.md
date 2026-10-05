# Contrato de matrices ómicas y límites de interpretación

## Principio general

Arii distingue la **forma matemática** de una matriz de su **modalidad
experimental**. Dos archivos de proteómica y metabolómica pueden tener la misma
forma y no requerir el mismo procesamiento. La detección automática es por ello
una sugerencia que el usuario debe confirmar.

La primera ampliación admite matrices numéricas procesadas en CSV, TSV o TXT,
con identificadores en la primera fila y primera columna. Se aceptan las
orientaciones variables × muestras y muestras × variables. No se procesan por
ahora archivos instrumentales crudos, `mzML`, detección de picos,
deconvolución, alineamiento cromatográfico ni identificación molecular.

## Representaciones

- **Perfil continuo:** existe un eje ordenado con significado físico, por
  ejemplo ppm, tiempo de retención o longitud de onda. Las líneas entre puntos
  tienen significado visual.
- **Tabla de características:** las columnas o filas representan picos,
  metabolitos, genes, proteínas u otras entidades discretas. Arii no dibuja una
  curva continua entre variables porque su vecindad en el archivo no implica
  continuidad biológica.

## Requisitos comunes

- Identificadores de muestra y variable completos y únicos.
- Cuerpo de la matriz estrictamente numérico y finito.
- Registro de la modalidad, orientación y representación confirmadas.
- Documentación del procesamiento realizado antes de Arii.
- Clase, individuo, lote y estudio separados de las variables predictoras.
- Agrupación por individuo durante validación cuando existen medidas repetidas.

La versión inicial detecta y comunica valores ausentes, pero no los imputa. La
imputación futura deberá ser específica para la modalidad y, cuando aprenda
parámetros de los datos, realizarse dentro de cada partición de entrenamiento
para evitar fuga de información.

## Normalización, transformación y escalado

Son operaciones distintas:

1. La normalización corrige tamaño de biblioteca, cantidad total, deriva
   instrumental u otros efectos propios de la medición.
2. La transformación modifica la distribución, por ejemplo `log2`, VST o CLR.
3. El centrado resta la media de cada variable.
4. El escalado decide el peso relativo de las variables en el modelo.

Arii no debe asumir que una matriz normalizada está lista para cualquier
modelo. En esta etapa ofrece centrado seguido de Pareto, varianza unitaria o
ningún escalado. Sugiere Pareto para perfiles RMN y varianza unitaria para
tablas de características, pero la elección es explícita y se registra.

## Consideraciones por modalidad

### Metabolómica LC-MS y GC-MS

Debe conocerse si las celdas son intensidades de picos, áreas normalizadas o
abundancias identificadas. Ceros y ausencias pueden representar valores bajo
el límite de detección, fallos de alineamiento o ausencia biológica y no deben
tratarse automáticamente como equivalentes. Son relevantes blancos, muestras
QC, deriva por orden de inyección, lote, estándar interno, transformación y
anotaciones `m/z`/tiempo de retención.

### Proteómica

Debe documentarse si se importan péptidos o proteínas, el método de agregación,
la normalización y la transformación logarítmica. Los faltantes suelen ser
informativos y dependientes de abundancia; una imputación genérica puede crear
separación artificial. También deben controlarse contaminantes, identificadores
obsoletos y efectos de lote.

### Transcriptómica y datos de expresión

Los conteos crudos no deben introducirse directamente en PCA/PLS-DA con Pareto
o autoscaling como sustituto de normalización. Antes se requiere un tratamiento
adecuado del tamaño de biblioteca y de la relación media-varianza, por ejemplo
una transformación estabilizadora o valores de expresión normalizados. Deben
conservarse la versión de los identificadores y el procedimiento de filtrado.

### Genómica y genotipos

Una matriz de expresión génica no equivale a una matriz de genotipos 0/1/2.
Para genotipos importan frecuencia alélica, variantes raras, desequilibrio de
ligamiento, estructura poblacional y parentesco. La unidad de validación debe
evitar repartir individuos emparentados entre entrenamiento y validación.

### Microbioma y datos composicionales

Las abundancias relativas y conteos composicionales requieren filtrado,
tratamiento de ceros y transformaciones log-ratio como CLR. El escalado de una
tabla de proporciones sin atender su geometría composicional puede producir
correlaciones espurias.

### Single-cell

La enorme dispersión, ceros, dimensionalidad y dependencia entre células del
mismo donante hacen inadecuado validar por célula. El individuo, no cada célula,
es normalmente la unidad independiente; pueden requerirse agregación
`pseudobulk` y métodos específicos antes de Arii.

## Problemas estadísticos transversales

- En escenarios `p >> n`, un modelo no disperso puede ajustar ruido aunque la
  visualización parezca convincente.
- Filtrado supervisado, selección de variables, imputación y tuning realizados
  antes de la validación producen estimaciones optimistas.
- La selección de `keepX` en modelos sparse debe evaluarse mediante validación
  anidada o una separación externa apropiada.
- Lote, centro, corrida y orden experimental pueden explicar más variación que
  la clase biológica.
- Desbalance de clases y replicación desigual requieren BER, resultados por
  clase y particiones agrupadas, no sólo exactitud global.

## Referencias de implementación

- [Flujo oficial de mixOmics](https://mixomics.org/apply-your-method/)
- [Preguntas frecuentes y preprocesamiento](https://mixomics.org/faq/)
- [Preprocesamiento composicional mixMC](https://mixomics.org/mixmc/)
