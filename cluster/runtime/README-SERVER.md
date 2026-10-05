# Motor de cálculo de Arii para servidor/clúster

Este paquete **no es la aplicación de escritorio** y no contiene una interfaz
gráfica. Está destinado a servidores o clústeres Linux x86-64 cuyos nodos de
cálculo sean compatibles con glibc 2.28 o posterior.

No contiene usuarios, contraseñas, claves SSH, direcciones institucionales,
datasets, resultados ni configuraciones Slurm. Cada investigador debe usar su
propia cuenta SSH/Slurm.

## Instalación automática por consola

Desde una sesión SSH en el servidor o nodo de acceso:

```bash
ARII_VERSION=1.0.0
wget -O install-arii-server.sh \
  "https://raw.githubusercontent.com/EXCI5ION/Arii/v${ARII_VERSION}/cluster/install-server.sh"
less install-arii-server.sh
ARII_VERSION="$ARII_VERSION" bash install-arii-server.sh
```

Si `wget` no está disponible, la descarga inicial puede hacerse con:

```bash
curl -fLo install-arii-server.sh \
  "https://raw.githubusercontent.com/EXCI5ION/Arii/v1.0.0/cluster/install-server.sh"
```

El script instala el runtime bajo
`$HOME/arii/runtime/releases/Arii-1.0.0-cluster-runtime-linux-x86_64`, sin
`sudo` y sin modificar R, Python o Conda del sistema. Antes de extraerlo verifica
el checksum publicado. Puede elegirse otra ruta absoluta mediante
`ARII_INSTALL_BASE`.

## Instalación manual o sin acceso a Internet

Descomprima el archivo en una carpeta versionada dentro de su espacio personal:

```bash
mkdir -p "$HOME/arii/runtime/releases"
tar -xzf Arii-1.0.0-cluster-runtime-linux-x86_64.tar.gz \
  -C "$HOME/arii/runtime/releases"
cd "$HOME/arii/runtime/releases/Arii-1.0.0-cluster-runtime-linux-x86_64"
./install-runtime.sh
```

El último comando corrige las rutas internas del entorno y ejecuta una prueba
directa de R. Debe ejecutarse una sola vez después de mover o descomprimir el
runtime. En un `$HOME` compartido por NFS, la primera extracción puede tardar
decenas de minutos por la cantidad de archivos pequeños; esto no implica que el
trabajo se haya detenido.

Configure en Arii la ruta remota:

```text
/home/USUARIO/arii/runtime/releases/Arii-1.0.0-cluster-runtime-linux-x86_64/bin/Rscript
```

## Prueba mediante Slurm

Desde la raíz del runtime:

```bash
sbatch share/arii/health.sbatch
```

Cuando termine, `arii-runtime-health-<JOBID>.json` debe indicar `"status": "ok"`.

Una instalación institucional compartida puede ubicarse en `/opt` o en un
filesystem de software del clúster, pero debe ser instalada por sus
administradores y permanecer en modo de solo lectura para los usuarios.

## Integridad

Compruebe el SHA-256 publicado junto al archivo antes de instalarlo:

```bash
sha256sum -c SHA256SUMS-cluster-1.0.0.txt
```
