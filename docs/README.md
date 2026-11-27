# Documentación de Arii

Esta carpeta separa la documentación según su propósito y mantiene una fuente
canónica para cada documento. El manual y la documentación científica incluidos
en esta rama corresponden a **Arii 1.2.0**. Las fuentes y los PDF exportados
desde Overleaf se revisan juntos antes de cada publicación.

## Documentos principales

- [Manual de usuario](manual.tex): fuente LaTeX canónica del manual. Se edita y
  compila en Overleaf para producir el PDF publicado con cada versión.
- [Manual de usuario en PDF, versión 1.2.0](pdf/Arii-manual-de-usuario-versión1.2.0.pdf).
- [Documentación científica en LaTeX](scientific_documentation.tex): fuente
  editorial canónica del PDF científico, con ecuaciones y bibliografía.
- [Documentación científica en Markdown](SCIENTIFIC_DOCUMENTATION.md): versión
  complementaria navegable directamente desde GitHub.
- [Documentación científica en PDF, versión 1.2.0](pdf/Arii-documentacion-cientifica-versión1.2.0.pdf).
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

Los PDF publicados se guardan en `docs/pdf/` con su versión en el nombre. El
flujo editorial se realiza en Overleaf a partir de `manual.tex` y
`scientific_documentation.tex`. Después de la revisión visual, se incorpora el
PDF de la versión nueva sin confundirlo con los documentos históricos. La versión
Markdown científica se sincroniza con la fuente LaTeX aprobada.

La versión del runtime de clúster es independiente de la aplicación de
escritorio. El flujo remoto con SIMPLS requiere runtime 1.1.0 o posterior porque
el artefacto 1.0.0 publicado no contiene el paquete R `pls`.
