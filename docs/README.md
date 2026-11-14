# Documentación de Arii

Esta carpeta separa la documentación según su propósito y mantiene una fuente
canónica para cada documento. El manual y la documentación científica incluidos
en esta rama corresponden a **Arii 1.1.0** y el README principal está preparado
para la publicación de esa misma versión.

## Documentos principales

- [Manual de usuario](main.tex): fuente LaTeX canónica del manual. Se edita y
  compila en Overleaf para producir el PDF publicado con cada versión.
- [Manual de usuario en PDF](pdf/Arii-manual-de-usuario-versión1.1.0.pdf).
- [Documentación científica en LaTeX](scientific_documentation.tex): fuente
  editorial canónica del PDF científico, con ecuaciones y bibliografía.
- [Documentación científica en Markdown](SCIENTIFIC_DOCUMENTATION.md): versión
  complementaria navegable directamente desde GitHub.
- [Documentación científica en PDF](pdf/Arii-documentacion-cientifica-versión1.1.0.pdf).
- [Referencia rápida](QUICK_REFERENCE.md): recorrido corto para ejecutar y
  revisar un análisis.
- [Requisitos por sistema operativo](OS-Requirements.md).
- [Guía del clúster Slurm](cluster-user-guide.md).

## Documentos técnicos especializados

- [Contrato científico](scientific-contract.md).
- [Test de permutaciones](permutation-test-guide.md).
- [Contrato de datos ómicos](omics-data-contract.md).
- [Diseño de ejecución local y remota](cluster-execution-design.md).

## PDF

Los PDF publicados se guardan en `docs/pdf/`. Tanto el manual como la
documentación científica se compilan desde sus archivos LaTeX mediante:

```bash
python docs/build_pdfs.py
```

Si no se encuentra `latexmk` o `pdflatex`, los dos `.tex` se compilan en
Overleaf. La versión Markdown científica se revisa junto con la fuente LaTeX.

La versión del runtime de clúster es independiente de la aplicación de
escritorio. Arii 1.1.0 utiliza actualmente el runtime remoto 1.0.0.
