# Diseño provisional de ejecución local y en clúster

## Decisiones de seguridad

- Arii no almacena contraseñas, frases de paso, claves privadas, JWT ni tokens
  dentro de proyectos `.arii` o perfiles exportables.
- Cada persona debe usar una cuenta individual autorizada por la institución.
  Varias cuentas pueden compartir el mismo proyecto, cuenta contable o QOS del
  planificador sin compartir una identidad SSH.
- La opción recomendada genera una clave Ed25519 cifrada de Arii después de una
  única autenticación con contraseña. También se admiten OpenSSH, `ssh-agent`,
  alias SSH y Pageant. El perfil sólo contiene metadatos no secretos.
- No habrá host, usuario, partición ni política de la universidad codificados en
  la distribución pública.

## Contrato inicial

La ejecución local ya usa `RJob`, compuesto por el worker R, la especificación
JSON y la ruta de resultado. `LocalRBackend` traduce ese contrato a un proceso
Rscript. El adaptador remoto acepta el mismo trabajo y se limita a:

1. preparar una carpeta remota exclusiva del trabajo;
2. transferir entradas con comprobación de huella;
3. generar un script cerrado para el planificador;
4. enviar y devolver un identificador de trabajo;
5. consultar estado y recuperar resultados y registros;
6. reservar la futura cancelación al trabajo creado por Arii.

El adaptador no ofrece una consola remota ni acepta comandos arbitrarios
desde el archivo de proyecto. El ejemplo
[`execution-profile.example.json`](execution-profile.example.json) contiene
únicamente campos públicos de conexión y planificación.

## Adaptador Slurm

Slurm es el planificador confirmado para el primer despliegue. Arii ya puede
construir un script `sbatch` cerrado a partir de CPU, memoria y tiempo solicitados.
El script sólo puede invocar workers R conocidos, crea rutas bajo
`remote_workspace/jobs/<job-id>`, exige un resultado no vacío y restringe sus
permisos a la cuenta propietaria. No acepta módulos, prólogos ni comandos libres
procedentes de la GUI o de un proyecto `.arii`.

El transporte SSH integrado —o PuTTY/Pageant como alternativa— abre la conexión
sin prompts interactivos, transfiere las entradas, llama a `sbatch`, consulta
`squeue` y descarga `result.json`. La GUI muestra el estado durante todo el
ciclo. Las permutaciones pueden dividirse en trabajos independientes,
ejecutarse en varios nodos y reunirse con validación de índices. Se evita `srun`
cuando el clúster no puede resolver la identidad del usuario en nodos
secundarios. La cancelación segura y la reanudación continúan fuera del alcance
de la versión 1.0.0.

## CPU, memoria y GPU

La validación PLS-DA y las permutaciones usan procesos independientes. En local
se reservan al menos tres CPU lógicas y se aplica un límite adicional estimado a
partir de la RAM disponible y del tamaño de la matriz. En Slurm, CPU y memoria son
por trabajo y por nodo; las bibliotecas BLAS se limitan a un hilo para evitar
sobresuscripción.

Las GPU registradas por Slurm no se solicitan actualmente. `mixOmics` no ofrece
un backend CUDA equivalente, por lo que usar otro algoritmo requeriría una etapa
independiente de implementación y validación numérica.

## Trabajo posterior a la versión 1.0.0

La conexión actual confirma la huella SSH y puede instalar la clave administrada
por Arii. Una versión posterior podrá transferir e instalar el runtime desde la
GUI, ejecutar su prueba de salud y detectar límites de cada centro. Para una
instalación compartida sin cuentas SSH de los usuarios sería necesario un
servicio institucional administrado, con SSO, autorización acotada y auditoría;
no debe construirse sobre la cuenta personal de un investigador.
