# Runtime remoto de Arii

`environment-linux-64.yml` define el entorno candidato para clústeres Linux
x86_64. Sus versiones no sustituyen automáticamente el entorno científico local:
primero deben superar los workers de salud, la suite numérica y comparaciones de
tolerancia con resultados de referencia. Después de resolverlo en el clúster se
exportará un lock explícito con las URLs y hashes exactos de los paquetes.

OPLS-DA se implementa sobre `mixOmics`; `ropls` no forma parte del runtime.

`runtime/` contiene los scripts usados para producir el artefacto de servidor
`Arii-<versión>-cluster-runtime-linux-x86_64.tar.gz`. El archivo se construye
con `conda-pack`, conserva un único directorio raíz y se acompaña de manifiesto,
lock explícito, licencias, instalador y prueba de salud Slurm. Nunca debe
construirse comprimiendo directamente el directorio personal de un usuario.

La prioridad de canales sigue la recomendación actual de Bioconda: `conda-forge`
primero, `bioconda` después y prioridad estricta. Arii no modifica `.condarc`; los
canales y la prioridad se indican en cada creación de entorno.

El runtime se instala en el espacio privado del usuario. Una instalación pública
posterior deberá ser de sólo lectura y mantenida por administradores; los trabajos
y resultados permanecerán separados por identidad.

`install-server.sh` es el instalador de consola dirigido al usuario final. Descarga
el runtime y su checksum desde una release, verifica la plataforma y la integridad,
extrae el entorno en una carpeta versionada y ejecuta `conda-unpack`. No requiere
privilegios de administrador ni instala dependencias en el sistema operativo.

En Windows, `scripts/stage_cluster_release.ps1` reúne los archivos de construcción,
el lock explícito y un smoke test PCA en un único kit temporal para transferir al
clúster. El kit no se publica: el asset de la release es únicamente el runtime
producido por `runtime/build-runtime.sbatch` y su checksum SHA-256.
