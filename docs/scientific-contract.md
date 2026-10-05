# Contrato científico inicial

## Matriz y metadatos

El núcleo usa `X` con forma `muestras x variables`. El eje ppm o los
identificadores de características pertenecen a los metadatos de variables y
nunca se tratan como muestras ni como predictores.
Las clases, e individuos pertenecen a los metadatos de
muestras.

## Centrado y escalado

Para cada variable `j`, el valor transformado es:

```text
(x_ij - media_j) / sqrt(desviación_estándar_j)
```

Además de Pareto, Arii permite varianza unitaria (división por la desviación
estándar) o ningún escalado tras el centrado. En modelos supervisados, media y
desviación se estiman exclusivamente con el conjunto de entrenamiento y luego
se aplican al conjunto de validación.

## Reproducibilidad

Todo resultado deberá registrar, como mínimo:

- especificación completa del trabajo;
- hash de los datos de entrada;
- versiones de Python, R y paquetes estadísticos;
- semilla aleatoria y particiones de validación;
- advertencias y errores del motor;
- artefactos numéricos independientes de las figuras.

## Elipse T² de Hotelling

En gráficos bidimensionales de *scores* se ofrece una elipse global, calculada
con las muestras incluidas en modelos PCA y PLS-DA. Para `p = 2` componentes y `n` muestras,
el límite usado es:

```text
T²(alpha) = p(n-1)/(n-p) * F(alpha; p, n-p)
```

La elipse no representa intervalos separados por clase ni demuestra separación
estadística entre grupos. El nivel elegido y el límite numérico se conservan en
los resultados.

## Motores

- `mixOmics`: PCA, PLS-DA y OPLS-DA.

La aplicación no expone objetos internos de esos paquetes como contrato público.

## Persistencia

Un proyecto `.arii` es un archivo ZIP con un manifiesto `project.json` y, cuando
existe, `results/model.json`. Los proyectos antiguos con `results/pca.json`
siguen siendo compatibles. El dataset de entrada se referencia por ruta y
SHA-256; no se incorpora automáticamente al contenedor para evitar duplicar
datos potencialmente grandes o sensibles.

## Metadatos y particiones

Los metadatos se unen por identificador de muestra y no por orden de filas. Los
campos `biological_id`, `replicate` y `batch` no alteran el PCA. En los modelos
supervisados, `biological_id` define la unidad de remuestreo cuando está
informado: todas las réplicas del mismo individuo permanecen en el mismo fold.
Un identificador biológico no puede pertenecer a más de una clase.

## Artefactos exportados

Los CSV son artefactos numéricos primarios y no se reconstruyen desde imágenes.
Las fracciones de varianza se exportan tanto en proporción como en porcentaje.
El manifiesto registra la huella del dataset y la configuración del análisis. Las
figuras representan el estado visual elegido por el usuario y se ofrecen en un
formato raster de alta resolución y otro vectorial.

## Test de permutaciones

Las etiquetas se permutan por unidad biológica cuando ésta está disponible. En
cada permutación se repite la validación externa y se calculan R²Y, Q²Y, BER y
AUC macro. El resultado inferencial principal es un p empírico con corrección
`+1`; la vista de R²Y/Q²Y frente a correlación de Y es un diagnóstico
complementario. Arii registra además la duración total y por permutación. La
definición completa y las pautas de interpretación están en
[`permutation-test-guide.md`](permutation-test-guide.md).

## Ejecución

Los motores reciben un contrato formado por worker, especificación JSON y ruta
de resultado. La ejecución local y el adaptador Slurm comparten ese límite. Los
perfiles remotos nunca forman parte del contrato
científico ni contienen secretos; véase
[`cluster-execution-design.md`](cluster-execution-design.md).

## Ajuste descriptivo del PCA

Para `a` componentes, la reconstrucción del modelo completo es:

```text
T = X * P_a
X_hat = T * transpose(P_a)
```

Se informa `RMSE = sqrt(mean((X - X_hat)^2))` y `R²X = 1 - SSE/TSS`. Estas
métricas describen el ajuste y la reconstrucción de las mismas muestras usadas
para estimar el PCA; no se presentan como validación externa ni como rendimiento
predictivo.

## Evaluación PLS-DA

PLS-DA se evalúa mediante Random Subsets repetido y estratificado. Por defecto,
cada una de 20 iteraciones vuelve a asignar aleatoriamente las unidades a 5
folds; los 5 folds se recorren como validación, generando 100 submodelos. Cada
unidad recibe una predicción externa por iteración. La proporción teórica por
submodelo es 80 % entrenamiento y 20 % validación, con pequeñas variaciones por
redondeo o por agrupación de réplicas.
Cada transformación dependiente de los datos se estima exclusivamente en el
entrenamiento. Se informa exactitud y BER por número de componentes; BER es la
media de los errores por clase y reduce el sesgo de la exactitud cuando los
tamaños de clase difieren. Las matrices de confusión agregan únicamente
predicciones de muestras externas a cada ajuste.

R²Y se calcula como `1 - SSE/TSS` sobre la matriz indicadora de clases y las
predicciones del modelo completo. Q²Y usa la misma forma, pero su PRESS agrega
únicamente predicciones externas y su TSS se centra respecto de las proporciones
de clase aprendidas en cada entrenamiento. ROC/AUC utiliza los valores continuos
en un esquema one-vs-rest; el AUC macro es la media no ponderada entre clases.
Se presentan dos fuentes por separado: `ajuste`, calculada al aplicar el modelo
completo a sus propias muestras, y `CV`, calculada después de promediar para cada
muestra sus predicciones externas entre iteraciones. La primera es descriptiva y
potencialmente optimista; la segunda estima rendimiento interno fuera de fold.

La complejidad sugerida usa la regla de un error estándar: se localiza el BER CV
medio mínimo y se selecciona el menor número de LVs cuyo BER no supera ese mínimo
más su error estándar entre iteraciones. Como selección y estimación se realizan
sobre el mismo esquema CV, se etiqueta como exploratoria. Una estimación final
sin sesgo de selección requerirá validación anidada o un conjunto externo.

La sugerencia y la decisión final son estados distintos. Al terminar el análisis,
la sugerencia se convierte en el modelo actual inicial; el usuario puede adoptar
otra cantidad de LVs. Todas las vistas interpretativas, el resumen, la exportación
y los tests de permutaciones se refieren al modelo actual. Las métricas
CV de los candidatos permanecen disponibles para comparación y no se recalculan
al cambiar la selección.

Las curvas de sensibilidad y especificidad frente al umbral usan esas mismas
fuentes. El umbral exploratorio maximiza `sensibilidad + especificidad - 1`
(índice de Youden), con desempate por equilibrio entre ambas tasas. No se usa
para recalcular las métricas del modelo y no representa un threshold validado.

## OPLS-DA

OPLS-DA es una transformación posterior de un PLS-DA binario calculado con
`mixOmics`. La dirección de la respuesta continua define el eje **Predictiva**;
una base QR del subespacio latente residual genera **Ortogonal 1**, **Ortogonal
2**, etc. Los loadings se reestiman por mínimos cuadrados sobre los scores
rotados. La operación no vuelve a ajustar las clases ni altera predicciones,
R²Y, Q²Y, BER, confusión o ROC.

La rotación se calcula por separado para cada complejidad `k = 1..ncomp`: el
modelo `k` contiene una dirección predictiva y `k-1` direcciones ortogonales.
Por ello, componentes homónimas de modelos con distinta `k` no deben compararse
como si fueran una base latente fija. La misma implementación se ejecuta local o
remotamente y los tests de permutación fijan la complejidad del modelo actual.

## Gráfico de valores de carga

La pestaña **Loadings** conserva la representación estándar del loading
`p_jk` de la variable `j` sobre el componente `k`. La pestaña independiente
**Loading plot** presenta una versión reescalada a partir del mismo vector. Para
el preprocesamiento Pareto de Arii:

```text
valor_jk = sqrt(desviación_estándar_j) * p_jk
```

Con escalado de varianza unitaria el multiplicador es la desviación estándar;
sin escalado se conserva `p_jk`.

El eje Y usa `valor_jk` y el color de cada segmento usa el loading `p_jk`
original con una escala tipo `jet`. El eje ppm se muestra en orden descendente;
las tablas de características usan puntos discretos y no una curva que sugiera
continuidad entre genes, proteínas o metabolitos adyacentes.
La trasposición que aparece en implementaciones MATLAB no forma parte del
cálculo: Arii guarda siempre la matriz como `variables × componentes` y extrae
la columna seleccionada. Tampoco necesita convertir el último punto en `NaN`,
porque dibuja segmentos abiertos y no un polígono `patch` cerrado.

En PCA pueden seleccionarse PC1, PC2, etc. En OPLS-DA pueden seleccionarse la
componente Predictiva y las Ortogonales disponibles en el modelo actual. Las
ortogonales describen variación de X no asociada directamente con Y y no deben
interpretarse como biomarcadores discriminantes. El signo de un componente
latente es indeterminado: dos programas pueden mostrar simultáneamente loading,
valor reescalado y colores con signo opuesto sin que los modelos difieran.

## Permutaciones de la respuesta

El test permuta la respuesta entre unidades de intercambio. Si existen
`biological_id`, la etiqueta se asigna a la unidad completa y todas sus réplicas
permanecen juntas; en ausencia de identificadores, la muestra es la unidad. Se
conserva el número de unidades por clase. Los folds estratificados se generan una
vez con la respuesta observada y se reutilizan en todo el test. El preprocesado se
estima exclusivamente dentro de cada entrenamiento y, como X y los folds no
cambian, sus matrices transformadas se almacenan y reutilizan. Las respuestas
permutadas que dejarían algún entrenamiento sin una clase se vuelven a generar.

Las estadísticas son R²Y del ajuste completo, Q²Y externo, BER externo y AUC macro
externo. Los valores p empíricos se calculan como `(1 + b) / (B + 1)`, donde `b`
es el número de estadísticas nulas al menos tan extremas como la observada. La cola
es superior para R²Y, Q²Y y AUC, e inferior para BER. Por tanto, con `B`
permutaciones la resolución mínima es `1/(B+1)`.

PLS-DA y OPLS-DA prueban la complejidad del modelo actual. La
ortogonalización no se repite porque no modifica predicciones ni las estadísticas
del test.

El test queda vinculado al modelo actual: cambiar su cantidad de LVs invalida el
resultado previo. La modalidad futura de comparación exhaustiva/anidada podrá
distribuir permutaciones, folds y candidatos entre nodos de clúster sin alterar
este contrato.

Como diagnóstico complementario, el mismo conjunto de predicciones alimenta una
comparación residual global y por clase. Arii representa SSQ estandarizada de
ajuste y CV frente a la correlación de Y e informa contrastes unilaterales de
Wilcoxon, signos y t de aleatorización. La unidad del contraste es la muestra y
su referencia es el error medio de esa muestra bajo las permutaciones. Estas
pruebas son compatibles conceptualmente, no bit a bit, con la salida observada de
PLS_Toolbox y no reemplazan el p empírico principal.
