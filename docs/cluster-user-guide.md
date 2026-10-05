# Guía inicial para ejecutar Arii en un clúster Slurm

Esta guía está escrita para usuarios que no administran servidores. La interfaz
de Arii realiza ya este primer flujo y traduce los errores principales a lenguaje
claro.

## La idea general

El programa tiene dos partes:

1. **Cliente local:** la interfaz de Arii, el proyecto y las figuras permanecen
   en la computadora del investigador.
2. **Trabajo remoto:** Arii prepara datos, parámetros y un worker R, los copia a
   una carpeta privada del usuario, solicita recursos a Slurm y recupera el JSON
   resultante.

`sbatch` no ejecuta necesariamente el análisis en el acto. Registra el trabajo,
devuelve un identificador y Slurm lo deja pendiente hasta que haya recursos. La
interfaz muestra estados como *preparando*, *en cola*, *ejecutando*,
*completado*, *fallido* o *cancelado*.

## ¿Hay que guardar scripts en el clúster?

No manualmente. Arii gestionará dos zonas bajo una carpeta elegida por el usuario:

```text
/scratch/usuario/arii/
├── runtime/             versión de workers y entorno reproducible
└── jobs/
    └── identificador/   job.json, datos, submit.sbatch, log y result.json
```

En la primera implementación se podrá copiar el worker correspondiente dentro
de cada trabajo. Más adelante Arii podrá reutilizar archivos por huella para no
volver a transferir datasets grandes. Nunca escribirá fuera de la carpeta remota
configurada.

## ¿Hay que instalar R?

R debe existir en los **nodos de cálculo**, no solamente en el servidor de
acceso. Para el runtime remoto aprobado hacen falta `mixOmics`, `jsonlite` y sus
dependencias. OPLS-DA permanece basado en `mixOmics` y no requiere `ropls`.
Hay tres estrategias posibles:

1. **R y paquetes administrados por el clúster.** Es la opción más sencilla si
   ya existe un módulo adecuado. Normalmente se selecciona un módulo de R antes
   de ejecutar el worker.
2. **Biblioteca privada con renv.** No suele requerir privilegios de administrador.
   Un archivo `renv.lock` registra versiones y `renv::restore()` reconstruye la
   biblioteca del proyecto. La instalación inicial puede tardar y algunos
   paquetes necesitan compiladores o bibliotecas del sistema.
3. **Contenedor Apptainer/Singularity.** Suele ser la alternativa más reproducible
   para distribuir Arii si el clúster la admite. R y sus paquetes viajan en una
   imagen versionada. Docker normalmente no se ejecuta directamente en nodos HPC
   por requerir un modelo de privilegios diferente.

La distribución inicial aprobada por Arii es un runtime Linux x86-64 relocatable
creado con `conda-pack`. Se publica como un artefacto opcional y claramente
identificado para **servidor/clúster**, separado del instalador de escritorio.
El usuario lo descomprime una vez en una carpeta versionada, ejecuta
`install-runtime.sh` y configura la ruta resultante de `bin/Rscript`. Un
contenedor Apptainer continúa siendo una alternativa futura para instituciones
que prefieran imágenes administradas.

La extracción inicial puede tardar decenas de minutos cuando `$HOME` reside en
NFS, aunque el archivo comprimido mida bastante menos que el entorno instalado.
Debe dejarse terminar una vez; los trabajos posteriores reutilizan el runtime.

En clústeres sin módulos ni contenedores, Arii puede instalar Micromamba en el
home del usuario y crear un entorno versionado desde
`cluster/environment-linux-64.yml`. La especificación inicial se convierte en un
lock explícito después de resolverla y verificarla; de ese modo una actualización
del repositorio de paquetes no cambia silenciosamente el runtime ya aprobado.

El paquete relocatable no contiene direcciones, usuarios, claves, datasets ni
resultados. Puede instalarse privadamente dentro de `$HOME` sin privilegios o,
con intervención administrativa, una sola vez en un directorio institucional de
sólo lectura. La futura opción **Instalar motor de cálculo en servidor/clúster…**
automatizará transferencia, SHA-256, extracción, `conda-unpack`, prueba Slurm y
registro de la ruta remota.

## Configuración gráfica

La ventana está en **Ejecución > Configurar recursos y Slurm…** y guarda un perfil local no
secreto. Después se elige **Clúster Slurm** en el campo **Ejecutar en** de la
pantalla principal. Arii ya incluye conexión, carpeta, recursos, envío, seguimiento
y recuperación. El asistente crecerá hasta automatizar la detección de límites,
la prueba de salud de R y la validación guiada de la huella del servidor.

La implementación admite OpenSSH integrado (incluido en Windows moderno), alias
de configuración OpenSSH y, por compatibilidad, PuTTY/Pageant. El perfil y los
recursos se guardan localmente; las claves privadas y contraseñas nunca se
incluyen en el proyecto `.arii`. Todos los modelos y permutaciones pueden enviarse.

La opción recomendada es **Clave administrada por Arii**. El usuario completa
servidor, puerto, usuario y carpeta remota y pulsa **Configurar acceso automático
con contraseña…**. En el primer acceso Arii:

1. muestra la huella SHA-256 del servidor para que el usuario la confirme;
2. usa la contraseña únicamente para esa conexión;
3. genera una clave Ed25519 cifrada e instala su parte pública en
   `~/.ssh/authorized_keys`;
4. guarda la frase aleatoria de la clave en el almacén de credenciales del
   sistema operativo; y
5. verifica inmediatamente un nuevo ingreso sin contraseña.

Cada investigador debe realizar este alta con su propia cuenta del clúster. Las
sesiones posteriores, transferencias SFTP y órdenes Slurm se gestionan dentro de
Arii y no requieren PuTTY ni Pageant.

## Campos que verá el usuario

- **Servidor de acceso:** dirección o alias entregado por la institución.
- **Usuario:** cuenta personal; no debe compartirse.
- **Carpeta remota:** espacio privado, normalmente en `scratch`, `work` o el home.
- **Cuenta Slurm:** proyecto al que se contabiliza el consumo; no es una contraseña.
- **Partición:** conjunto o cola de nodos, por ejemplo CPU o memoria alta.
- **QOS:** política de prioridad o límites; muchos centros no exigen indicarla.
- **CPU/memoria/tiempo:** petición máxima por trabajo, no garantía de uso continuo.

Los campos opcionales pueden dejarse vacíos: Slurm aplicará los valores
predeterminados del centro.

Solicitar más CPU no acelera por sí solo un programa secuencial. Arii distribuye
los folds PLS-DA y las respuestas permutadas entre los CPU solicitados, limita a
un hilo las bibliotecas BLAS y conserva semillas reproducibles. Las permutaciones
pueden dividirse además entre varios trabajos Slurm y reunirse automáticamente.
Esta alternativa funciona incluso en centros donde `srun` multinodo no puede
resolver la identidad del usuario.

La RAM se limita por nodo. Más memoria no acelera el álgebra si el trabajo ya
cabe, pero evita paginación o fallos al ejecutar varios procesos. Arii recomienda
reservar margen para el sistema y no multiplicar procesos por encima de la RAM.

Una partición o una GPU disponible tampoco acelera automáticamente `mixOmics`:
el motor actual ejecuta PLS-DA en CPU. Arii puede detectar y documentar GPU, pero
no solicita GRES ni declara aceleración hasta disponer de un backend CUDA validado
contra los resultados científicos de referencia.

## Seguridad y distribución

El perfil se guarda por usuario en la configuración local de la aplicación y no
en el proyecto `.arii`. Arii puede solicitar la contraseña durante el alta de
la clave administrada, pero la usa únicamente para esa conexión: no la guarda ni
la serializa junto con tokens o claves privadas. Un proyecto compartido puede
abrirse en otra computadora sin llevar consigo acceso al clúster del autor.

Cada persona necesita una cuenta SSH institucional propia y un par de claves
propio. La clave pública se registra en su cuenta del clúster y la privada nunca
sale de su computadora. Esto se hace una vez por usuario y dispositivo, no en
cada análisis. En una computadora adicional conviene generar otra clave para
poder revocarla de forma independiente. Sólo quienes elijan la alternativa
PuTTY/Pageant deben cargar su clave en Pageant al iniciar la sesión de Windows.

Para ofrecer el clúster a compañeros, la solución correcta sigue siendo que el
centro les cree cuentas individuales asociadas al mismo proyecto Slurm. Una
instalación institucional con identidad única sólo debería existir como servicio
administrado, autorizado y auditado.

## Información que falta para conectar el primer clúster

No hace falta conocerla de memoria. Puede obtenerse de la documentación interna
o preguntando al administrador:

- servidor o alias de acceso SSH;
- ubicación recomendada para trabajos y datasets;
- nombre del módulo de R, si se usa uno;
- disponibilidad de Apptainer/Singularity;
- si cuenta, partición o QOS son obligatorias;
- posibilidad de acceder a repositorios de R desde los nodos de instalación.
