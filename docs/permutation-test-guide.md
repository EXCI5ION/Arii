# Nota técnica provisional: test de permutaciones

Esta nota documenta la implementación actual de Arii. Se integrará y ampliará
en la documentación oficial cuando se cierre la primera versión *single-omics*.

## Qué pregunta responde

El test estima con qué frecuencia un modelo construido después de destruir al
azar la relación entre `X` y la clase `Y` alcanza un rendimiento tan favorable
como el observado. No demuestra por sí solo validez clínica o capacidad de
generalización a otro estudio; funciona como control frente a una separación
obtenida por azar dentro del diseño disponible.

Las etiquetas se permutan por unidad de intercambio. Si se informó un
`biological_id`, sus réplicas se mantienen juntas; en caso contrario la unidad
es la muestra. Después de cada permutación se repite el mismo esquema Random
Subsets estratificado empleado para evaluar el modelo. El modelo observado y las
respuestas permutadas se evalúan sobre la misma lista de particiones. Mantener
fijos los conjuntos externos reduce el ruido debido al remuestreo y permite una
comparación pareada. Una permutación que dejara un entrenamiento sin alguna
clase se descarta y se vuelve a generar.

## Métricas y p empírico

Arii calcula todas las métricas en una misma ejecución. El selector **Métrica
mostrada** sólo modifica el histograma, no recalcula ni cambia el test.

- `Q²Y externo`: capacidad predictiva estimada exclusivamente con predicciones
  de validación; es la métrica primaria recomendada para la inferencia.
- `BER externo`: error de clasificación balanceado; resulta especialmente útil
  con clases desbalanceadas. Aquí un valor menor es mejor.
- `AUC macro externo`: discriminación promedio entre clases basada en
  predicciones externas.
- `R²Y`: bondad de ajuste del modelo completo. Es descriptiva y puede ser
  optimista; conviene interpretarla junto con Q²Y y no como sustituto de éste.

El p empírico usa la corrección `+1`:

```text
p = (1 + permutaciones al menos tan favorables como el observado) / (B + 1)
```

Para R²Y, Q²Y y AUC se usa la cola superior; para BER, la inferior. Con `B=5`,
el menor p posible es `1/6 = 0,1667`; para poder observar `p < 0,05` hacen falta
al menos 20 permutaciones y se recomiendan bastantes más para estimaciones
estables.

## Modos y vistas

La interfaz permite solicitar **Empírico**, **Comparación residual** o **Ambos**.
El modo combinado reutiliza las mismas predicciones; ejecutar Wilcoxon, Sign Test
y Randomization t-test agrega un coste insignificante frente al ajuste de los
modelos.

**Distribución nula** es la vista inferencial principal. El histograma muestra
los resultados bajo etiquetas permutadas y la línea naranja el resultado del
modelo actual. Una buena separación visual debe confirmarse con el p empírico.

**R²Y/Q²Y frente a correlación de Y** es un diagnóstico complementario inspirado
en PLS_Toolbox. Para permitir más de dos clases, Arii convierte Y en su matriz de
indicadores, aplana esa matriz y calcula la correlación de Pearson entre la Y
permutada y la original. Los puntos naranjas en correlación 1 representan el
modelo observado; las líneas discontinuas son tendencias descriptivas, no un
segundo test de significancia. Esta vista ayuda a detectar tendencias anómalas,
pero no reemplaza el histograma ni el p empírico.

**SSQ residual frente a correlación de Y** representa, para el ajuste y la
validación cruzada, la suma de cuadrados residual dividida por la variación total
de cada columna indicadora de Y. Un valor menor es mejor. Puede mostrarse de forma
global o por clase.

La comparación residual contrasta unilateralmente si los errores cuadrados por
muestra del modelo observado son menores que el error medio de esa muestra bajo
las respuestas permutadas. Mantener la muestra como unidad del contraste evita
tratar folds o permutaciones repetidas como observaciones independientes. Se
informan Wilcoxon de rangos con signo, prueba de signos y t de aleatorización por
cambios de signo con 9.999 aleatorizaciones. Son diagnósticos relacionados, no
tres oportunidades independientes de declarar significancia. La implementación
es conceptualmente compatible con la salida observada de PLS_Toolbox, pero no
pretende ser una copia bit a bit de su algoritmo propietario.

## Modelo que se pone a prueba

PLS-DA y OPLS-DA mantienen fija la complejidad del **modelo actual**. La rotación
ortogonal no se repite porque no cambia las predicciones usadas por las métricas.
Cambiar el modelo actual invalida el test anterior.

## Diferencia respecto de PLS_Toolbox

PLS_Toolbox representa medidas de error o suma de residuos frente a la
correlación de Y y ofrece varias pruebas sobre residuos. Arii implementa esa
familia de diagnósticos de forma transparente, pero conserva como resultado
inferencial principal un p de permutación empírico explícito sobre métricas
externas.

## Coste computacional

El coste crece aproximadamente con el número de permutaciones multiplicado por
las iteraciones y data splits. Arii registra el tiempo total, el ajuste observado
y la duración de cada permutación. Estos datos permitirán estimar recursos antes
de enviar el mismo contrato de trabajo a un clúster.

La lista de folds se genera una sola vez. El centrado y escalado se estiman sólo
con el entrenamiento de cada fold y esas matrices X ya preprocesadas se reutilizan
en todas las respuestas permutadas. El modelo actual queda fijado. El trabajador R permanece activo durante todo el
test y las métricas y contrastes comparten predicciones.

## Ejecución paralela

En Slurm, las permutaciones se reparten entre los CPU solicitados y, cuando se
configura más de un nodo, entre varios trabajos independientes que Arii reúne por
índice. En Windows se utilizan procesos R independientes. Cada permutación recibe
semillas separadas para el intercambio de etiquetas y para su validación, por lo
que cambiar la cantidad de CPU o nodos no cambia respuestas permutadas, métricas
ni valores p.
