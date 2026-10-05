args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) {
  stop("Uso: Rscript runtime_manifest.R <salida.json>")
}

roots <- c("mixOmics", "jsonlite")
installed <- installed.packages()
missing <- setdiff(roots, rownames(installed))
if (length(missing) > 0L) {
  stop("Paquetes requeridos ausentes: ", paste(missing, collapse = ", "))
}

dependencies <- tools::package_dependencies(
  roots, db = installed, recursive = TRUE
)
packages <- sort(unique(c(roots, unlist(dependencies, use.names = FALSE))))
packages <- packages[packages %in% rownames(installed)]
records <- lapply(packages, function(package) {
  description <- utils::packageDescription(package)
  list(
    name = package,
    version = as.character(description$Version),
    license = as.character(description$License),
    priority = if (is.null(description$Priority)) NA_character_ else as.character(description$Priority),
    # Record the location inside the relocatable runtime, never the build
    # machine's absolute installation path.
    path = file.path("lib", "R", "library", package)
  )
})

manifest <- list(
  schema_version = "1.0",
  generated_at = format(Sys.time(), tz = "UTC", usetz = TRUE),
  platform = R.version$platform,
  r_version = R.version.string,
  r_home = file.path("lib", "R"),
  root_packages = roots,
  packages = records
)
jsonlite::write_json(manifest, args[[1]], pretty = TRUE, auto_unbox = TRUE, na = "null")
